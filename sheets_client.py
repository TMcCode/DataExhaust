"""Open Google Sheets using a service account JSON key.

Requires: pip install gspread

Set GOOGLE_SHEETS_CREDENTIALS to an absolute path to override the default
``data-exhaust-key.json`` next to this file.
"""

from __future__ import annotations

import os
import re
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Tuple

_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

# Schema of the empty fallback returned by load_mlp_fast_casual_dataframes when no
# credentials are available. Same column lists used by the success path so downstream
# code (build_mlp_brand_period_wide_df, dashboard pages) sees the expected shape.
_EMPTY_SHEETS_SCHEMA: dict[str, tuple[str, ...]] = {
    "historical_values": ("Ticker", "Prd_Nm", "Metric", "MetricValue", "Footnotes"),
    "fiscal_dates": ("Ticker", "Prd_Nm", "Prd_Strt", "Prd_End", "days", "isEst"),
    "metric_names": ("Ticker", "Metric", "CommonName"),
    "sss_forecasts": (
        "Ticker", "Prd_Nm", "CommonName", "Value", "Source", "Footnote", "UpdateDate",
    ),
}


def credentials_path() -> Path:
    override = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent / "data-exhaust-key.json"


def sheets_credentials_available() -> bool:
    """``True`` iff a Sheets service-account JSON is reachable on disk.

    Used by :func:`load_mlp_fast_casual_dataframes` for the graceful-skip path so the
    rest of the ETL (FRED, alt-data CSVs, etc.) can still run for a reviewer who has
    *no* Google credentials. See ``GOOGLE_SHEETS_CREDENTIALS`` env var for overrides.
    """
    return credentials_path().is_file()


def _empty_sheets_bundle() -> dict[str, Any]:
    """Schema-correct empty replacement for :func:`load_mlp_fast_casual_dataframes`.

    Empty DataFrames with the *right column names* let downstream code (wide-panel
    builder, dashboard pages) execute without ``KeyError`` even when no rows loaded.
    """
    import pandas as pd

    return {key: pd.DataFrame(columns=list(cols)) for key, cols in _EMPTY_SHEETS_SCHEMA.items()}


def get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    path = credentials_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Service account JSON not found: {path}. "
            "Copy the key here or set GOOGLE_SHEETS_CREDENTIALS."
        )
    creds = Credentials.from_service_account_file(str(path), scopes=_SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(spreadsheet_id: str):
    """Open by ID (the long string in the sheet URL)."""
    return get_gspread_client().open_by_key(spreadsheet_id)


def worksheet_as_records(
    spreadsheet_id: str,
    worksheet: str | int = 0,
) -> list[dict[str, Any]]:
    """Return rows as dicts using the first row as headers."""
    sh = open_spreadsheet(spreadsheet_id)
    if isinstance(worksheet, int):
        ws = sh.get_worksheet(worksheet)
    else:
        ws = sh.worksheet(worksheet)
    return ws.get_all_records()


# MLP_Fast_Casual workbook — ID is the segment between /d/ and /edit in the URL
MLP_FAST_CASUAL_SPREADSHEET_ID = "1GUwNP7ZzzwNbfaVT9pAalEYvDsF967jqlJNnvRqKWxY"


def load_mlp_fast_casual_dataframes(
    spreadsheet_id: str | None = None,
) -> dict[str, Any]:
    """Load the three analysis tabs as pandas DataFrames (one API workbook open).

    Tabs (titles match your workbook):
      - ``HistoricalValues`` — Ticker, Prd_nm, Metric, MetricValue, optional Footnotes
      - ``FiscalDates`` — Ticker, Prd_Nm, Prd_Strt, Prd_End, days, isEst
      - ``MetricNames`` — Ticker, Metric, CommonName
      - ``SSSForecasts`` — optional forecast defaults: Ticker, Prd_Nm, CommonName, Value, Source, Footnote.
        CommonName values: ``traffic``, ``menu_price``, ``check_mix`` (ppt), ``total_units_open`` (unit count).

    Requires: ``pip install gspread pandas``

    Graceful skip: if no service-account JSON is reachable (see
    :func:`sheets_credentials_available`), emits a warning and returns schema-correct
    *empty* DataFrames so the rest of the ETL can still run.
    """
    import pandas as pd

    if not sheets_credentials_available():
        warnings.warn(
            "Google Sheets skipped: no service-account JSON at "
            f"{credentials_path()} (set GOOGLE_SHEETS_CREDENTIALS or place "
            "data-exhaust-key.json next to sheets_client.py). Returning empty "
            "workbook frames so downstream macro / alt-data steps can proceed.",
            stacklevel=2,
        )
        return _empty_sheets_bundle()

    sid = spreadsheet_id or MLP_FAST_CASUAL_SPREADSHEET_ID
    sh = open_spreadsheet(sid)

    def _df(title: str) -> Any:
        return pd.DataFrame(sh.worksheet(title).get_all_records())

    def _df_historical_values() -> Any:
        """First row may have stray columns; preserve optional cell-level footnotes."""
        cols = ("Ticker", "Prd_Nm", "Metric", "MetricValue", "Footnotes")
        ws = sh.worksheet("HistoricalValues")
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return pd.DataFrame(columns=cols)
        header = [str(x).strip() for x in rows[0]]
        header_l = [h.lower() for h in header]

        def _idx(name: str, fallback: int) -> int:
            return header_l.index(name.lower()) if name.lower() in header_l else fallback

        ticker_i = _idx("Ticker", 0)
        prd_i = _idx("Prd_Nm", 1)
        metric_i = _idx("Metric", 2)
        value_i = _idx("MetricValue", 3)
        foot_i = next(
            (i for i, h in enumerate(header_l) if h in {"footnote", "footnotes", "note", "notes"}),
            None,
        )
        body = []
        for r in rows[1:]:
            r = list(r)
            padded = r + [""] * max(0, len(header) + 5 - len(r))
            body.append(
                [
                    padded[ticker_i],
                    padded[prd_i],
                    padded[metric_i],
                    padded[value_i],
                    padded[foot_i] if foot_i is not None else "",
                ]
            )
        return pd.DataFrame(body, columns=cols)

    def _df_optional(title: str, columns: tuple[str, ...]) -> Any:
        try:
            return _df(title)
        except Exception:
            return pd.DataFrame(columns=columns)

    # Round-trips in parallel (read-only); speeds cold dashboard loads vs sequential pulls.
    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_hist = pool.submit(_df_historical_values)
        fut_fd = pool.submit(_df, "FiscalDates")
        fut_mn = pool.submit(_df, "MetricNames")
        fut_fc = pool.submit(
            _df_optional,
            "SSSForecasts",
            ("Ticker", "Prd_Nm", "CommonName", "Value", "Source", "Footnote", "UpdateDate"),
        )
        historical_values = fut_hist.result()
        fiscal_dates = fut_fd.result()
        metric_names = fut_mn.result()
        sss_forecasts = fut_fc.result()

    out = {
        "historical_values": historical_values,
        "fiscal_dates": fiscal_dates,
        "metric_names": metric_names,
        "sss_forecasts": sss_forecasts,
    }
    # Sheets often have ``sg`` vs ``SG``; wide filter uses uppercase tickers only.
    for tbl in out.values():
        if "Ticker" in tbl.columns:
            tbl["Ticker"] = tbl["Ticker"].astype(str).str.strip().str.upper()
    return out


# Wide table: primary names vs peer panel (MetricsNames join ⇒ sparse columns ok for peers)
_MLP_FOCUS_TICKERS = ("CMG", "BROS", "CAVA")
_MLP_FOCUS_TICKER_SET = frozenset(_MLP_FOCUS_TICKERS)
# ``peer_or_focus`` in the wide CSV is ``peer`` for these (never add SG to ``_MLP_FOCUS_TICKERS`` unless intent changes).
_MLP_PEER_PANEL_TICKERS = ("WING", "SHAK", "SG")
_MLP_WIDE_TABLE_TICKERS = _MLP_FOCUS_TICKERS + _MLP_PEER_PANEL_TICKERS
# CLI / diagnostics (same order as focus + peer tuples).
MLP_WIDE_TABLE_TICKERS: tuple[str, ...] = _MLP_WIDE_TABLE_TICKERS
# Sheet CommonName → CSV column (your naming)
_MLP_COMMON_TO_COL = {
    "sss": "sss",
    "traffic": "traffic",
    "ticket": "ticket",
    "digital_mix": "digitalmix",
    "menu_price": "menu_price",
    "check_mix": "check_mix",
    "auv": "auv",
    "total_units_begin": "total_units_begin",
    "total_units_open": "total_units_open",
    "total_units_close": "total_units_closed",
    "total_units_end": "total_units_end",
    "restaurant_rev": "restaurant_rev",
    "company_rev": "company_rev",
    "franchise_rev": "franchise_rev",
    # Dollar bridge (workbook MetricNames CommonName → wide column): new vs comp buckets + residual vs total YoY $.
    "new_dollars": "new_dollars",
    "sss_dollars": "sss_dollars",
}
_MLP_WIDE_COL_ORDER = (
    "Ticker",
    "peer_or_focus",
    "Prd_Nm",
    "Prd_End",
    "isEst",
    "sss",
    "traffic",
    "ticket",
    "digitalmix",
    "menu_price",
    "check_mix",
    "auv",
    "total_units_begin",
    "total_units_open",
    "total_units_closed",
    "total_units_end",
    "restaurant_rev",
    "company_rev",
    "franchise_rev",
    "new_dollars",
    "sss_dollars",
)
_MLP_DERIV_COL_ORDER = (
    "sss_lq",
    "sss_ly",
    "sss_2yr_stack",
    "traffic_lq",
    "traffic_ly",
    "traffic_2yr_stack",
    "ticket_ly",
    "ticket_2yr_stack",
    "units_entering_comp_base",
    "auv_yoy",
    "unit_growth_yoy",
    "restaurant_rev_yoy_dollars",
    "new_plus_sss_dollars",
    "restaurant_rev_yoy_bridge_residual",
)
_MLP_PEER_SSS_TICKERS = ("BROS", "WING", "SHAK", "CMG", "CAVA", "SG")
# Peer indices (simple + weighted) are only populated for ``Prd_Nm`` >= this quarter.
_MLP_PEER_INDEX_START_YEAR_Q = (2021, 1)
# ``PeerPricingIndex`` / ``PeerTrafficIndex`` (ticket / traffic baskets) start later — sparser disclosure.
_MLP_PEER_PRICING_TRAFFIC_START_YEAR_Q = (2023, 1)
_MLP_COMP_BASE_LAG_QTRS = {
    "CMG": 5,  # at least 13 full calendar months
    "CAVA": 4,  # open 365 days or longer
    "BROS": 5,  # open 15 complete months or longer
    "SG": 5,  # open 15 complete months or longer
    "WING": 4,  # open at least 52 full weeks
    "SHAK": 8,  # open 24 full fiscal months or longer
}
_MLP_EXTRA_DERIVED_COL_ORDER = (
    "SSSCheck",
    "PeerSSSIndex",
    "PeerPricingIndex",
    "PeerTrafficIndex",
    "RelativeSSS",
    "WtdPeerSSSIndex",
    "RelativeWtdPeerSSSIndex",
    "PeerAUVIndex",
    "WtdPeerAUVIndex",
    "SystemCompBaseCoverage",
    "SystemSalesPerOperatingWeek",
)
_MLP_FOOTNOTE_COL_ORDER = tuple(f"{c}_footnote" for c in _MLP_WIDE_COL_ORDER[5:])
_MLP_ALL_COL_ORDER = (
    _MLP_WIDE_COL_ORDER + _MLP_FOOTNOTE_COL_ORDER + _MLP_DERIV_COL_ORDER + _MLP_EXTRA_DERIVED_COL_ORDER
)


def _parse_prd_nm(prd: Any) -> Tuple[int, int] | None:
    """Return (year, quarter) for strings like 2020Q3; else None."""
    m = re.match(r"^(\d{4})Q([1-4])$", str(prd).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _fmt_prd(y: int, q: int) -> str:
    return f"{y}Q{q}"


def _prd_at_or_after_year_q(
    prd: Any, year: int | None = None, quarter: int | None = None
) -> bool:
    """True iff ``prd`` parses as ``YYYYQ[1-4]`` and is >= (year, quarter)."""
    yy = _MLP_PEER_INDEX_START_YEAR_Q[0] if year is None else year
    qq = _MLP_PEER_INDEX_START_YEAR_Q[1] if quarter is None else quarter
    t = _parse_prd_nm(prd)
    if t is None:
        return False
    y, q = t
    if y > yy:
        return True
    if y < yy:
        return False
    return q >= qq


def _prd_prior_quarter(y: int, q: int) -> Tuple[int, int]:
    if q == 1:
        return y - 1, 4
    return y, q - 1


def _prd_prior_year_same_q(y: int, q: int) -> Tuple[int, int]:
    return y - 1, q


def _prd_shift(y: int, q: int, quarters: int) -> Tuple[int, int]:
    ordinal = y * 4 + (q - 1) + quarters
    out_y, out_q0 = divmod(ordinal, 4)
    return out_y, out_q0 + 1


def _coerce_number(x: Any) -> float:
    """Parse MetricValue-style cells: numbers, commas, percents, (neg)."""
    import math

    import pandas as pd

    if x is None or (isinstance(x, float) and math.isnan(x)):
        return float("nan")
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    s = str(x).strip()
    if s in ("", "nan", "NaN", "None", "<NA>"):
        return float("nan")
    s = s.replace(",", "")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s.endswith("%"):
        s = s[:-1].strip()
        try:
            v = float(s) / 100.0
        except ValueError:
            return float("nan")
        return -v if neg else v
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return float("nan")


def _coerce_percent_points(x: Any) -> float:
    """Like _coerce_number but values without % are taken as already in %% points (e.g. 2.2)."""
    import math

    s = str(x).strip() if x is not None and not (isinstance(x, float) and math.isnan(x)) else ""
    if s.endswith("%"):
        return _coerce_number(x) * 100.0
    v = _coerce_number(x)
    if math.isnan(v):
        return float("nan")
    # Plain number: treat as percent points (sheet often stores 2.2 for 2.2%)
    if abs(v) <= 1.0 and v != 0.0:
        return v * 100.0
    return v


def _peer_sss_index_by_period(hist: Any, m: Any) -> Any:
    """Mean ``sss`` (ppt) across peers by ``Prd_Nm``. Series indexed by ``Prd_Nm``."""
    import pandas as pd

    mh = m.copy()
    mh["Ticker"] = mh["Ticker"].astype(str).str.strip()
    mh["Metric"] = mh["Metric"].astype(str).str.strip()
    mh["CommonName"] = mh["CommonName"].astype(str).str.strip()
    mh = mh[
        (mh["Ticker"].isin(_MLP_PEER_SSS_TICKERS)) & (mh["CommonName"] == "sss")
    ][["Ticker", "Metric"]]
    hh = hist.copy()
    j = hh.merge(mh, on=["Ticker", "Metric"], how="inner")
    j["_ppt"] = j["MetricValue"].map(_coerce_percent_points)
    return j.groupby("Prd_Nm", sort=False)["_ppt"].mean()


def _peer_ticket_index_by_period(hist: Any, m: Any) -> Any:
    """Mean ``ticket`` (ppt, ticket / mix growth) across peers by ``Prd_Nm``. Series indexed by ``Prd_Nm``."""
    import pandas as pd

    mh = m.copy()
    mh["Ticker"] = mh["Ticker"].astype(str).str.strip()
    mh["Metric"] = mh["Metric"].astype(str).str.strip()
    mh["CommonName"] = mh["CommonName"].astype(str).str.strip()
    mh = mh[
        (mh["Ticker"].isin(_MLP_PEER_SSS_TICKERS)) & (mh["CommonName"] == "ticket")
    ][["Ticker", "Metric"]]
    hh = hist.copy()
    j = hh.merge(mh, on=["Ticker", "Metric"], how="inner")
    j["_ppt"] = j["MetricValue"].map(_coerce_percent_points)
    return j.groupby("Prd_Nm", sort=False)["_ppt"].mean()


def _peer_traffic_index_by_period(hist: Any, m: Any) -> Any:
    """Mean ``traffic`` (ppt) across peers by ``Prd_Nm``. Series indexed by ``Prd_Nm``."""
    import pandas as pd

    mh = m.copy()
    mh["Ticker"] = mh["Ticker"].astype(str).str.strip()
    mh["Metric"] = mh["Metric"].astype(str).str.strip()
    mh["CommonName"] = mh["CommonName"].astype(str).str.strip()
    mh = mh[
        (mh["Ticker"].isin(_MLP_PEER_SSS_TICKERS)) & (mh["CommonName"] == "traffic")
    ][["Ticker", "Metric"]]
    hh = hist.copy()
    j = hh.merge(mh, on=["Ticker", "Metric"], how="inner")
    j["_ppt"] = j["MetricValue"].map(_coerce_percent_points)
    return j.groupby("Prd_Nm", sort=False)["_ppt"].mean()


def _peer_weighted_sss_index_by_period(hist: Any, m: Any) -> Any:
    """Revenue-weighted mean ``sss`` (ppt) across peers by ``Prd_Nm``.

    Weights = ``restaurant_rev`` (same CommonName as the wide table) per peer-period;
    peers with missing SSS or non-positive weight are dropped from that quarter’s sum.
    """
    import pandas as pd

    mh = m.copy()
    mh["Ticker"] = mh["Ticker"].astype(str).str.strip()
    mh["Metric"] = mh["Metric"].astype(str).str.strip()
    mh["CommonName"] = mh["CommonName"].astype(str).str.strip()
    peers = _MLP_PEER_SSS_TICKERS

    m_sss = mh[(mh["Ticker"].isin(peers)) & (mh["CommonName"] == "sss")][["Ticker", "Metric"]]
    m_rev = mh[(mh["Ticker"].isin(peers)) & (mh["CommonName"] == "restaurant_rev")][
        ["Ticker", "Metric"]
    ]
    hh = hist.copy()
    s = hh.merge(m_sss, on=["Ticker", "Metric"], how="inner")
    s["ppt"] = s["MetricValue"].map(_coerce_percent_points)
    r = hh.merge(m_rev, on=["Ticker", "Metric"], how="inner")
    r["w"] = r["MetricValue"].map(_coerce_number)

    merged = s[["Ticker", "Prd_Nm", "ppt"]].merge(
        r[["Ticker", "Prd_Nm", "w"]],
        on=["Ticker", "Prd_Nm"],
        how="inner",
    )
    _ppt = pd.to_numeric(merged["ppt"], errors="coerce")
    _w = pd.to_numeric(merged["w"], errors="coerce")
    ok = _ppt.notna() & _w.notna() & (_w > 0)
    mq = merged.loc[ok].copy()
    mq["_xw"] = _w[ok] * _ppt[ok]
    num = mq.groupby("Prd_Nm", sort=False)["_xw"].sum()
    den = mq.groupby("Prd_Nm", sort=False)["w"].sum()
    return num / den


def _peer_auv_index_by_period(hist: Any, m: Any) -> Any:
    """Equal-weight mean ``auv`` (:func:`_coerce_number`) across peers by ``Prd_Nm``."""
    import pandas as pd

    mh = m.copy()
    mh["Ticker"] = mh["Ticker"].astype(str).str.strip()
    mh["Metric"] = mh["Metric"].astype(str).str.strip()
    mh["CommonName"] = mh["CommonName"].astype(str).str.strip()
    mk = mh[
        (mh["Ticker"].isin(_MLP_PEER_SSS_TICKERS)) & (mh["CommonName"] == "auv")
    ][["Ticker", "Metric"]]
    hh = hist.copy()
    j = hh.merge(mk, on=["Ticker", "Metric"], how="inner")
    j["_auv"] = j["MetricValue"].map(_coerce_number)
    return j.groupby("Prd_Nm", sort=False)["_auv"].mean()


def _peer_weighted_auv_index_by_period(hist: Any, m: Any) -> Any:
    """``total_units_close``-weighted mean ``auv`` across peers by ``Prd_Nm``.

    Weights use CommonName ``total_units_close`` (wide column ``total_units_closed``);
    rows with missing ``auv``, missing weight, or non-positive weight drop out of that quarter.
    """
    import pandas as pd

    mh = m.copy()
    mh["Ticker"] = mh["Ticker"].astype(str).str.strip()
    mh["Metric"] = mh["Metric"].astype(str).str.strip()
    mh["CommonName"] = mh["CommonName"].astype(str).str.strip()
    peers = _MLP_PEER_SSS_TICKERS

    m_auv = mh[(mh["Ticker"].isin(peers)) & (mh["CommonName"] == "auv")][["Ticker", "Metric"]]
    m_uc = mh[(mh["Ticker"].isin(peers)) & (mh["CommonName"] == "total_units_close")][
        ["Ticker", "Metric"]
    ]
    hh = hist.copy()
    a = hh.merge(m_auv, on=["Ticker", "Metric"], how="inner")
    a["auv_v"] = a["MetricValue"].map(_coerce_number)
    r = hh.merge(m_uc, on=["Ticker", "Metric"], how="inner")
    r["w"] = r["MetricValue"].map(_coerce_number)

    merged = a[["Ticker", "Prd_Nm", "auv_v"]].merge(
        r[["Ticker", "Prd_Nm", "w"]],
        on=["Ticker", "Prd_Nm"],
        how="inner",
    )
    _av = pd.to_numeric(merged["auv_v"], errors="coerce")
    _w = pd.to_numeric(merged["w"], errors="coerce")
    ok = _av.notna() & _w.notna() & (_w > 0)
    mq = merged.loc[ok].copy()
    mq["_xw"] = _w[ok] * _av[ok]
    num = mq.groupby("Prd_Nm", sort=False)["_xw"].sum()
    den = mq.groupby("Prd_Nm", sort=False)["w"].sum()
    return num / den


def _add_peer_ss_checks(
    wide: Any,
    peer_series: Any,
    peer_wtd_series: Any,
) -> Any:
    """SSSCheck; equal-weight and rev-weighted peer SSS indexes + relatives (ppt).

    ``PeerSSSIndex``, ``RelativeSSS``, ``WtdPeerSSSIndex``, and ``RelativeWtdPeerSSSIndex``
    are **NaN** for ``Prd_Nm`` strictly before ``_MLP_PEER_INDEX_START_YEAR_Q`` (default 2021Q1).
    """
    import numpy as np
    import pandas as pd

    w = wide.copy()
    ppt_t = w["traffic"].map(_coerce_percent_points)
    ppt_k = w["ticket"].map(_coerce_percent_points)
    ppt_s = w["sss"].map(_coerce_percent_points)
    with np.errstate(invalid="ignore"):
        w["SSSCheck"] = ppt_t + ppt_k

    peer_ok = w["Prd_Nm"].map(_prd_at_or_after_year_q)
    w["PeerSSSIndex"] = w["Prd_Nm"].map(peer_series)
    w["RelativeSSS"] = ppt_s - w["PeerSSSIndex"]
    w["WtdPeerSSSIndex"] = w["Prd_Nm"].map(peer_wtd_series)
    w["RelativeWtdPeerSSSIndex"] = ppt_s - w["WtdPeerSSSIndex"]

    for col in ("PeerSSSIndex", "RelativeSSS", "WtdPeerSSSIndex", "RelativeWtdPeerSSSIndex"):
        w.loc[~peer_ok.fillna(False), col] = np.nan
    return w


def _add_peer_pricing_index(wide: Any, peer_ticket_series: Any) -> Any:
    """Equal-weight peer **ticket** (ppt) basket — values only from ``2023Q1`` onward (see ``_MLP_PEER_PRICING_TRAFFIC_START_YEAR_Q``)."""
    import numpy as np

    w = wide.copy()
    yy, qq = _MLP_PEER_PRICING_TRAFFIC_START_YEAR_Q
    peer_ok = w["Prd_Nm"].map(lambda p: _prd_at_or_after_year_q(p, yy, qq))
    w["PeerPricingIndex"] = w["Prd_Nm"].map(peer_ticket_series)
    w.loc[~peer_ok.fillna(False), "PeerPricingIndex"] = np.nan
    return w


def _add_peer_traffic_index(wide: Any, peer_traffic_series: Any) -> Any:
    """Equal-weight peer **traffic** (ppt) basket — same ``2023Q1`` cutover as ``PeerPricingIndex``."""
    import numpy as np

    w = wide.copy()
    yy, qq = _MLP_PEER_PRICING_TRAFFIC_START_YEAR_Q
    peer_ok = w["Prd_Nm"].map(lambda p: _prd_at_or_after_year_q(p, yy, qq))
    w["PeerTrafficIndex"] = w["Prd_Nm"].map(peer_traffic_series)
    w.loc[~peer_ok.fillna(False), "PeerTrafficIndex"] = np.nan
    return w


def _add_peer_auv_indexes(
    wide: Any,
    peer_auv_eq: Any,
    peer_auv_wtd: Any,
) -> Any:
    """Equal- and ``total_units_close``-weighted peer **AUV** (same cutover as SSS peer cols)."""
    import numpy as np

    w = wide.copy()
    peer_ok = w["Prd_Nm"].map(_prd_at_or_after_year_q)
    w["PeerAUVIndex"] = w["Prd_Nm"].map(peer_auv_eq)
    w["WtdPeerAUVIndex"] = w["Prd_Nm"].map(peer_auv_wtd)
    for col in ("PeerAUVIndex", "WtdPeerAUVIndex"):
        w.loc[~peer_ok.fillna(False), col] = np.nan
    return w


def _add_bros_shop_sales_derived(wide: Any, hist: Any) -> Any:
    """BROS-only: SystemShopBase ÷ TotalUnitsEnd; SystemSales ÷ (Company + Franchise weeks)."""
    import numpy as np
    import pandas as pd

    w = wide.copy()
    hh = hist[(hist["Ticker"] == "BROS")]

    def _col(metric: str) -> dict[tuple[Any, Any], Any]:
        sub = hh[hh["Metric"] == metric][["Prd_Nm", "MetricValue"]]
        return dict(zip(sub["Prd_Nm"], sub["MetricValue"]))

    shop_base = _col("SystemShopBase")
    units_end = _col("TotalUnitsEnd")
    sys_sales = _col("SystemSales")
    cw = _col("CompanyWeeks")
    fw = _col("FranchiseWeeks")

    def ratio_for(row: pd.Series, num_d: dict, den_d: dict) -> float:
        prd = row["Prd_Nm"]
        n = num_d.get(prd)
        d = den_d.get(prd)
        _n = _coerce_number(n)
        _d = _coerce_number(d)
        if _d == 0 or np.isnan(_d) or np.isnan(_n):
            return float("nan")
        return _n / _d

    is_bros = w["Ticker"] == "BROS"
    cov = w.apply(lambda r: ratio_for(r, shop_base, units_end), axis=1)
    wks = []
    for _, r in w.iterrows():
        if r["Ticker"] != "BROS":
            wks.append(float("nan"))
            continue
        prd = r["Prd_Nm"]
        a = _coerce_number(cw.get(prd))
        b = _coerce_number(fw.get(prd))
        denom = (a + b) if not (np.isnan(a) and np.isnan(b)) else np.nan
        num = _coerce_number(sys_sales.get(prd))
        if denom == 0 or np.isnan(denom) or np.isnan(num):
            wks.append(float("nan"))
        else:
            wks.append(num / denom)
    w.loc[:, "SystemCompBaseCoverage"] = np.where(is_bros, cov, np.nan)
    w.loc[:, "SystemSalesPerOperatingWeek"] = np.where(is_bros, np.array(wks, dtype=float), np.nan)
    return w


def _add_mlp_brand_derivatives(wide: Any) -> Any:
    """Add lag / YoY columns (expects ``Prd_Nm`` as YYYYQN).

    Bridge (after wide includes ``restaurant_rev``, ``new_dollars``, ``sss_dollars`` from MetricNames):

    - ``restaurant_rev_yoy_dollars``: current-quarter ``restaurant_rev`` minus same fiscal quarter last year ($).
    - ``new_plus_sss_dollars``: ``new_dollars`` + ``sss_dollars`` ($; companies’ comp / new buckets).
    - ``restaurant_rev_yoy_bridge_residual``: YoY revenue $ change minus that sum — FX, other revenue,
      recon differences, rounding, etc. NaN when inputs are incomplete.
    """
    import numpy as np
    import pandas as pd

    w = wide.copy()
    parsed = w["Prd_Nm"].map(_parse_prd_nm)
    w["_y"] = parsed.map(lambda t: t[0] if t else np.nan)
    w["_q"] = parsed.map(lambda t: t[1] if t else np.nan)

    def _prev_prd_nm(row: Any) -> str | None:
        if pd.isna(row["_y"]) or pd.isna(row["_q"]):
            return None
        py, pq = _prd_prior_quarter(int(row["_y"]), int(row["_q"]))
        return _fmt_prd(py, pq)

    def _prev_y_prd_nm(row: Any) -> str | None:
        if pd.isna(row["_y"]) or pd.isna(row["_q"]):
            return None
        py, pq = _prd_prior_year_same_q(int(row["_y"]), int(row["_q"]))
        return _fmt_prd(py, pq)

    w["_prd_lq"] = w.apply(_prev_prd_nm, axis=1)
    w["_prd_ly"] = w.apply(_prev_y_prd_nm, axis=1)

    ref = w[
        ["Ticker", "Prd_Nm", "sss", "traffic", "ticket", "auv", "total_units_end", "restaurant_rev"]
    ].copy()
    lq = ref.rename(
        columns={
            "Prd_Nm": "_prd_lq",
            "sss": "sss_lq",
            "traffic": "_traffic_lq_cell",
        }
    )[["Ticker", "_prd_lq", "sss_lq", "_traffic_lq_cell"]]
    ly = ref.rename(
        columns={
            "Prd_Nm": "_prd_ly",
            "sss": "sss_ly",
            "traffic": "_traffic_ly_cell",
            "ticket": "ticket_ly",
            "auv": "_auv_ly_cell",
            "total_units_end": "_units_ly_cell",
            "restaurant_rev": "_restaurant_rev_ly_cell",
        }
    )[
        [
            "Ticker",
            "_prd_ly",
            "sss_ly",
            "_traffic_ly_cell",
            "ticket_ly",
            "_auv_ly_cell",
            "_units_ly_cell",
            "_restaurant_rev_ly_cell",
        ]
    ]
    w = w.merge(lq, on=["Ticker", "_prd_lq"], how="left")
    w = w.merge(ly, on=["Ticker", "_prd_ly"], how="left")

    w["sss_2yr_stack"] = w["sss"].map(_coerce_percent_points) + w["sss_ly"].map(
        _coerce_percent_points
    )

    w["traffic_lq"] = w["traffic"].map(_coerce_percent_points) - w[
        "_traffic_lq_cell"
    ].map(_coerce_percent_points)
    w["traffic_ly"] = w["traffic"].map(_coerce_percent_points) - w[
        "_traffic_ly_cell"
    ].map(_coerce_percent_points)
    w["traffic_2yr_stack"] = w["traffic"].map(_coerce_percent_points) + w[
        "_traffic_ly_cell"
    ].map(_coerce_percent_points)
    w["ticket_2yr_stack"] = w["ticket"].map(_coerce_percent_points) + w[
        "ticket_ly"
    ].map(_coerce_percent_points)

    open_lookup = (
        w.set_index(["Ticker", "Prd_Nm"])["total_units_open"].map(_coerce_number).to_dict()
        if "total_units_open" in w.columns
        else {}
    )

    def _units_entering_comp_base(row: Any) -> float:
        lag = _MLP_COMP_BASE_LAG_QTRS.get(str(row.get("Ticker", "")).strip().upper())
        if lag is None or pd.isna(row["_y"]) or pd.isna(row["_q"]):
            return np.nan
        py, pq = _prd_shift(int(row["_y"]), int(row["_q"]), -lag)
        return float(open_lookup.get((row["Ticker"], _fmt_prd(py, pq)), np.nan))

    w["units_entering_comp_base"] = w.apply(_units_entering_comp_base, axis=1)

    _auv = w["auv"].map(_coerce_number)
    _auv_ly = w["_auv_ly_cell"].map(_coerce_number)
    w["auv_yoy"] = np.where(
        (_auv_ly != 0) & ~np.isnan(_auv_ly) & ~np.isnan(_auv),
        (_auv / _auv_ly - 1.0) * 100.0,
        np.nan,
    )

    _u = w["total_units_end"].map(_coerce_number)
    _u_ly = w["_units_ly_cell"].map(_coerce_number)
    w["unit_growth_yoy"] = np.where(
        (_u_ly != 0) & ~np.isnan(_u_ly) & ~np.isnan(_u),
        (_u / _u_ly - 1.0) * 100.0,
        np.nan,
    )

    # Restaurant revenue YoY absolute $ and disclosure-style bridge residual (needs ``new_dollars`` +
    # ``sss_dollars`` in MetricNames for each ticker/quarter).
    _rv = w["restaurant_rev"].map(_coerce_number)
    _rv_ly = w["_restaurant_rev_ly_cell"].map(_coerce_number)
    with np.errstate(invalid="ignore"):
        w["restaurant_rev_yoy_dollars"] = _rv - _rv_ly

    _new = w["new_dollars"].map(_coerce_number)
    _sss = w["sss_dollars"].map(_coerce_number)
    with np.errstate(invalid="ignore"):
        w["new_plus_sss_dollars"] = _new + _sss
        w["restaurant_rev_yoy_bridge_residual"] = (
            w["restaurant_rev_yoy_dollars"] - w["new_plus_sss_dollars"]
        )

    drop_cols = [
        "_y",
        "_q",
        "_prd_lq",
        "_prd_ly",
        "_traffic_lq_cell",
        "_traffic_ly_cell",
        "_auv_ly_cell",
        "_units_ly_cell",
        "_restaurant_rev_ly_cell",
    ]
    w = w.drop(columns=[c for c in drop_cols if c in w.columns])
    return w


def build_mlp_brand_period_wide_df(
    spreadsheet_id: str | None = None,
    dfs: dict[str, Any] | None = None,
) -> Any:
    """One row per (Ticker, Prd_Nm) for CMG/BROS/CAVA plus peer panel WING/SHAK/SG where mapped.

    ``peer_or_focus`` is ``focus`` for CMG/BROS/CAVA and ``peer`` for WING/SHAK/SG.
    Joins ``HistoricalValues`` to ``MetricNames`` on ``Ticker`` + ``Metric``, renames
    ``digital_mix`` → ``digitalmix`` and ``total_units_close`` → ``total_units_closed``.

    Adds ``restaurant_rev`` (CommonName ``restaurant_rev``); optional disclosure bridge metrics
    ``new_dollars`` / ``sss_dollars`` map into the wide table. Derived YoY revenue $ delta,
    ``new_plus_sss_dollars``, and ``restaurant_rev_yoy_bridge_residual`` vs total YoY $ change.
    ``PeerSSSIndex`` = equal-weight mean ``sss`` (ppt); ``PeerPricingIndex`` = equal-weight mean
    ``ticket`` (ppt); ``PeerTrafficIndex`` = equal-weight mean ``traffic`` (ppt) across the same peers.
    ``PeerPricingIndex`` and ``PeerTrafficIndex`` are **blank before 2023Q1** (ticket/traffic disclosure timing).
    ``WtdPeerSSSIndex`` = ``restaurant_rev``-
    weighted mean over the same peers.     ``Relative*`` = ticker ``sss`` (ppt) minus each index.
    ``PeerAUVIndex`` / ``WtdPeerAUVIndex`` = equal-weight and ``total_units_close``-weighted peer
    basket **AUV** (CommonName ``auv`` / ``total_units_close``). Same **2021Q1** cutover as SSS peer cols.
    Peer SSS / AUV basket columns are **blank before 2021Q1**. ``SystemCompBaseCoverage`` =
    ``SystemShopBase`` / ``TotalUnitsEnd`` and ``SystemSalesPerOperatingWeek`` =
    ``SystemSales`` / (``CompanyWeeks`` + ``FranchiseWeeks``) for **BROS only**;

    Derivatives on lags require ``Prd_Nm`` as ``YYYYQ[1-4]`` (**fiscal** labels; calendars differ—e.g.
    CMG/BROS vs CAVA vs WING/SHAK/SG ~90‑day fiscals with differing year-ends and 53rd-week quarters).
    For national **calendar**-quarter macro joins, use :mod:`analytic_panel` with ``fiscal_dates``
    ``Prd_Strt`` / ``Prd_End``.
    """
    import pandas as pd

    if dfs is None:
        dfs = load_mlp_fast_casual_dataframes(spreadsheet_id)
    hist_full = dfs["historical_values"].copy()
    m = dfs["metric_names"].copy()

    for col in ("Ticker", "Prd_Nm", "Metric", "MetricValue"):
        hist_full[col] = hist_full[col].astype(str).str.strip()
    if "Footnotes" not in hist_full.columns:
        hist_full["Footnotes"] = ""
    hist_full["Footnotes"] = hist_full["Footnotes"].astype(str).str.strip()
    hist_full["Ticker"] = hist_full["Ticker"].str.upper()
    m["Ticker"] = m["Ticker"].astype(str).str.strip().str.upper()
    m["Metric"] = m["Metric"].astype(str).str.strip()
    m["CommonName"] = m["CommonName"].astype(str).str.strip()

    peer_sss_by_prd = _peer_sss_index_by_period(hist_full, m)
    peer_ticket_by_prd = _peer_ticket_index_by_period(hist_full, m)
    peer_traffic_by_prd = _peer_traffic_index_by_period(hist_full, m)
    peer_sss_wtd_by_prd = _peer_weighted_sss_index_by_period(hist_full, m)
    peer_auv_by_prd = _peer_auv_index_by_period(hist_full, m)
    peer_auv_wtd_by_prd = _peer_weighted_auv_index_by_period(hist_full, m)

    hist_wide = hist_full[hist_full["Ticker"].isin(_MLP_WIDE_TABLE_TICKERS)]
    m_wide = m[m["Ticker"].isin(_MLP_WIDE_TABLE_TICKERS)]

    long = hist_wide.merge(m_wide, on=["Ticker", "Metric"], how="inner", suffixes=("", "_map"))
    long = long[long["CommonName"] != ""]
    long["col"] = long["CommonName"].map(_MLP_COMMON_TO_COL)
    long = long[long["col"].notna()]
    footnotes = long[long["Footnotes"].astype(str).str.strip() != ""].copy()
    footnotes = footnotes.drop_duplicates(subset=["Ticker", "Prd_Nm", "col"], keep="last")
    long = long.drop_duplicates(subset=["Ticker", "Prd_Nm", "col"], keep="last")

    wide = long.pivot_table(
        index=["Ticker", "Prd_Nm"],
        columns="col",
        values="MetricValue",
        aggfunc="first",
    ).reset_index()
    if not footnotes.empty:
        footnotes["footnote_col"] = footnotes["col"].astype(str) + "_footnote"
        foot_wide = footnotes.pivot_table(
            index=["Ticker", "Prd_Nm"],
            columns="footnote_col",
            values="Footnotes",
            aggfunc="first",
        ).reset_index()
        wide = wide.merge(foot_wide, on=["Ticker", "Prd_Nm"], how="left")

    wide["peer_or_focus"] = "peer"
    wide.loc[wide["Ticker"].isin(_MLP_FOCUS_TICKER_SET), "peer_or_focus"] = "focus"

    fiscal_dates = dfs.get("fiscal_dates")
    if isinstance(fiscal_dates, pd.DataFrame) and {"Ticker", "Prd_Nm", "Prd_End"}.issubset(
        fiscal_dates.columns
    ):
        fd_cols = ["Ticker", "Prd_Nm", "Prd_End"]
        if "isEst" in fiscal_dates.columns:
            fd_cols.append("isEst")
        fd = fiscal_dates[fd_cols].copy()
        fd["Ticker"] = fd["Ticker"].astype(str).str.strip().str.upper()
        fd["Prd_Nm"] = fd["Prd_Nm"].astype(str).str.strip()
        fd = fd.drop_duplicates(subset=["Ticker", "Prd_Nm"], keep="last")
        wide = wide.merge(fd, on=["Ticker", "Prd_Nm"], how="left", validate="m:1")

    ticker_order = {t: i for i, t in enumerate(_MLP_WIDE_TABLE_TICKERS)}
    wide["_sort_t"] = wide["Ticker"].map(ticker_order)
    wide = wide.sort_values(["_sort_t", "Prd_Nm"], kind="stable").drop(columns=["_sort_t"])

    for c in _MLP_WIDE_COL_ORDER:
        if c not in wide.columns:
            wide[c] = pd.NA
    wide = wide[list(_MLP_WIDE_COL_ORDER) + [c for c in _MLP_FOOTNOTE_COL_ORDER if c in wide.columns]]
    wide = _add_mlp_brand_derivatives(wide)
    wide = _add_peer_ss_checks(wide, peer_sss_by_prd, peer_sss_wtd_by_prd)
    wide = _add_peer_pricing_index(wide, peer_ticket_by_prd)
    wide = _add_peer_traffic_index(wide, peer_traffic_by_prd)
    wide = _add_peer_auv_indexes(wide, peer_auv_by_prd, peer_auv_wtd_by_prd)
    wide = _add_bros_shop_sales_derived(wide, hist_full)

    for c in _MLP_ALL_COL_ORDER:
        if c not in wide.columns:
            wide[c] = pd.NA
    wide = wide[list(_MLP_ALL_COL_ORDER)]
    return wide


def export_mlp_brand_period_wide_csv(
    path: str | os.PathLike | None = None,
    spreadsheet_id: str | None = None,
    dfs: dict[str, Any] | None = None,
    wide: Any | None = None,
) -> Path:
    """Write :func:`build_mlp_brand_period_wide_df` to CSV; default path next to this file."""
    out = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parent / "mlp_cmg_bros_cava_wide.csv"
    )
    df = wide if wide is not None else build_mlp_brand_period_wide_df(spreadsheet_id, dfs)
    df.to_csv(out, index=False)
    return out


if __name__ == "__main__":
    import pandas as pd

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)
    pd.set_option("display.max_colwidth", 40)

    dfs = load_mlp_fast_casual_dataframes()
    historical_values = dfs["historical_values"]
    fiscal_dates = dfs["fiscal_dates"]
    metric_names = dfs["metric_names"]

    for name, df in (
        ("historical_values", historical_values),
        ("fiscal_dates", fiscal_dates),
        ("metric_names", metric_names),
    ):
        print(f"\n=== {name} — {df.shape[0]} rows × {df.shape[1]} cols ===")
        print(df.head(10).to_string())
        print()

    wide = build_mlp_brand_period_wide_df(dfs=dfs)
    csv_path = export_mlp_brand_period_wide_csv(dfs=dfs, wide=wide)
    print(f"\n=== wide (+ WING/SHAK/SG) — {wide.shape[0]} rows × {wide.shape[1]} cols ===")
    print(wide.head(12).to_string())
    print(f"\nWrote CSV: {csv_path}")
