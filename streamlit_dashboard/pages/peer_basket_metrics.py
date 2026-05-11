"""Quarterly peer-basket grid (SG, SHAK, CMG, CAVA, WING, BROS) + equal-weight peer mean — SSS only (``CommonName`` ``sss``)."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
import streamlit as st

import sheets_client

try:
    import altair as alt
except ImportError:
    alt = None  # type: ignore[misc, assignment]

# Same basket as ``_MLP_PEER_SSS_TICKERS``; column order matches typical spreadsheet layout.
_DISPLAY_TICKERS: tuple[str, ...] = ("SG", "SHAK", "CMG", "CAVA", "WING", "BROS")

# First rows in the table = this quarter onward (older quarters still below when you scroll).
_DEFAULT_TABLE_START = "2022Q1"


def _prd_sort_key(s: object) -> int:
    m = re.match(r"^(\d{4})Q([1-4])$", str(s).strip())
    if not m:
        return 0
    return int(m.group(1)) * 10 + int(m.group(2))


def _coerce_for_common_name(raw: Any, common_name: str) -> float:
    """Match wide-panel treatment: % metrics → percent points; dollars / units → ``_coerce_number``."""
    if common_name in ("sss", "traffic", "ticket", "digital_mix"):
        return float(sheets_client._coerce_percent_points(raw))
    return float(sheets_client._coerce_number(raw))


def _build_quarterly_peer_grid(
    dfs: dict[str, Any],
    *,
    common_name: str,
) -> pd.DataFrame:
    """Rows = ``Prd_Nm``, columns = display tickers + ``PeerIndex`` (equal-weight mean, NaN-aware)."""
    hist = dfs["historical_values"].copy()
    m = dfs["metric_names"].copy()
    for col in ("Ticker", "Prd_Nm", "Metric", "MetricValue"):
        if col in hist.columns:
            hist[col] = hist[col].astype(str).str.strip()
    m["Ticker"] = m["Ticker"].astype(str).str.strip().str.upper()
    m["Metric"] = m["Metric"].astype(str).str.strip()
    m["CommonName"] = m["CommonName"].astype(str).str.strip()

    mh = m[
        (m["Ticker"].isin(_DISPLAY_TICKERS)) & (m["CommonName"] == common_name.strip())
    ][["Ticker", "Metric"]]
    if mh.empty:
        return pd.DataFrame()

    j = hist.merge(mh, on=["Ticker", "Metric"], how="inner")
    if j.empty:
        return pd.DataFrame()

    j["_v"] = j["MetricValue"].map(lambda x: _coerce_for_common_name(x, common_name))
    peer = j.groupby("Prd_Nm", sort=False)["_v"].mean()

    piv = j.pivot_table(index="Prd_Nm", columns="Ticker", values="_v", aggfunc="first")
    for t in _DISPLAY_TICKERS:
        if t not in piv.columns:
            piv[t] = pd.NA
    piv = piv[list(_DISPLAY_TICKERS)]
    piv["PeerIndex"] = peer.reindex(piv.index)
    piv = piv.sort_index(key=lambda idx: pd.Series([_prd_sort_key(x) for x in idx], index=idx))
    return piv


def _reorder_index_default_start(grid: pd.DataFrame, *, start_prd: str) -> pd.DataFrame:
    """Put ``start_prd`` and later first, then earlier quarters (so the table opens on ~2022 without losing history)."""
    if grid.empty:
        return grid
    start_k = _prd_sort_key(start_prd)
    idx = list(grid.index)
    recent = sorted([x for x in idx if _prd_sort_key(x) >= start_k], key=_prd_sort_key)
    older = sorted([x for x in idx if _prd_sort_key(x) < start_k], key=_prd_sort_key)
    return grid.reindex(recent + older)


def _is_percent_common_name(common_name: str) -> bool:
    return common_name in ("sss", "traffic", "ticket", "digital_mix")


def _format_percent_table(show: pd.DataFrame) -> pd.DataFrame:
    """Human-readable % strings; em dash for missing."""
    d = show.copy()
    for c in list(_DISPLAY_TICKERS) + ["PeerIndex"]:
        if c not in d.columns:
            continue
        d[c] = d[c].map(lambda v: "—" if pd.isna(v) else f"{float(v):.2f}%")
    return d


def main() -> None:
    st.title("Peer basket (quarterly)")
    st.caption(
        "Values come from **HistoricalValues** joined to **MetricNames** by ``Ticker`` + ``Metric``. "
        "**PeerIndex** = equal-weight mean across the six tickers for that ``Prd_Nm`` (missing tickers "
        "are **excluded** from the mean for that quarter — same behavior as a spreadsheet `AVERAGE`). "
        "This view does **not** apply the 2021Q1 blanking used on the published **PeerSSSIndex** wide column. "
        f"The table **opens on {_DEFAULT_TABLE_START}** (scroll down for earlier quarters). "
        "**% metrics** show with a % sign."
    )

    common_options = list(sheets_client._MLP_COMMON_TO_COL.keys())
    choice = st.selectbox(
        "Metric (MetricNames **CommonName**)",
        options=common_options,
        index=common_options.index("sss") if "sss" in common_options else 0,
        format_func=lambda k: f"{k}  →  `{sheets_client._MLP_COMMON_TO_COL[k]}`",
        key="peer_basket_common_name",
    )
    wide_col = sheets_client._MLP_COMMON_TO_COL[choice]

    sid = st.session_state.get("spreadsheet_id")
    if isinstance(sid, str):
        sid = sid.strip() or None
    elif sid is not None:
        sid = str(sid).strip() or None

    try:
        dfs = sheets_client.load_mlp_fast_casual_dataframes(sid)
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:
        st.error(f"**Sheets load failed:** `{type(e).__name__}` — {e}")
        st.stop()

    grid = _build_quarterly_peer_grid(dfs, common_name=choice)
    if grid.empty:
        st.warning(
            f"No rows for **CommonName** `{choice}` / wide column `{wide_col}` on the six tickers. "
            "Check **MetricNames** for that CommonName and peer tickers."
        )
        st.stop()

    st.subheader(f"Quarterly values — `{wide_col}`")
    grid_view = _reorder_index_default_start(grid, start_prd=_DEFAULT_TABLE_START)
    show = grid_view.reset_index().rename(columns={"Prd_Nm": "Quarter"})
    pct = _is_percent_common_name(choice)
    display_df = _format_percent_table(show) if pct else show

    col_cfg: dict[str, Any] = {"Quarter": st.column_config.TextColumn("Quarter")}
    if pct:
        for t in _DISPLAY_TICKERS:
            if t in display_df.columns:
                col_cfg[t] = st.column_config.TextColumn(t)
        col_cfg["PeerIndex"] = st.column_config.TextColumn("PeerIndex")
    else:
        for t in _DISPLAY_TICKERS:
            if t in display_df.columns:
                col_cfg[t] = st.column_config.NumberColumn(t, format="%.2f")
        col_cfg["PeerIndex"] = st.column_config.NumberColumn("PeerIndex", format="%.2f")

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=480,
        column_config=col_cfg,
    )

    st.subheader("PeerIndex by quarter")
    chart_df = (
        grid.sort_index(key=lambda idx: pd.Series([_prd_sort_key(x) for x in idx], index=idx))
        .reset_index()
        .rename(columns={"Prd_Nm": "Quarter"})
    )
    x_order = sorted(chart_df["Quarter"].astype(str).unique(), key=_prd_sort_key)
    y_title = "PeerIndex (%)" if pct else "PeerIndex (equal-weight mean)"
    if alt is not None:
        ch = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=alt.X("Quarter:N", title="Fiscal quarter", sort=x_order),
                y=alt.Y("PeerIndex:Q", title=y_title),
                tooltip=[
                    "Quarter",
                    alt.Tooltip("PeerIndex:Q", title="PeerIndex", format=",.2f"),
                ],
            )
            .properties(height=360)
        )
        st.altair_chart(ch, use_container_width=True)
    else:
        st.bar_chart(chart_df.set_index("Quarter")["PeerIndex"], use_container_width=True)


# Only run when this file is the active Streamlit page (exec'd as ``__main__``). When another
# page imports this module for helpers, ``__name__`` is the package path — skip ``main()`` so
# we do not paint Peer basket UI during that page's run (e.g. Macro & industry).
if __name__ == "__main__":
    main()
