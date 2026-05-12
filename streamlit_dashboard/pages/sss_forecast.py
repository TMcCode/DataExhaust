"""Same-store-sales forecast page with all-ticker history and a model-style bridge."""

from __future__ import annotations

import html
import re
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import sheets_client
from streamlit_dashboard.data_loader import get_dashboard_bundle_or_stop

try:
    import altair as alt
except ImportError:
    alt = None  # type: ignore[misc, assignment]


_TICKERS: tuple[str, ...] = ("CMG", "CAVA", "BROS", "WING", "SHAK", "SG")
# Focus brands the editable bottom-section model is scoped to. The forecast summary
# table and chart at the top still render all `_TICKERS` for cohort context.
_MODELABLE_TICKERS: tuple[str, ...] = ("CMG", "BROS", "CAVA")
_DEFAULT_TICKER = "CMG"
_CHART_START_PRD = "2022Q1"
_HISTORICAL_QUARTERS = 8
_FORECAST_QUARTERS = 4
_DRIVER_STATE_VERSION = "v5"
_CHART_METRICS: dict[str, tuple[str, str, str]] = {
    "SSS": ("sss", "Same-store sales (%)", ".1f"),
    "Traffic": ("traffic", "Traffic / transactions (%)", ".1f"),
    "Ticket": ("ticket", "Ticket / average check (%)", ".1f"),
    "Digital mix": ("digitalmix", "Digital mix (%)", ".1f"),
    "AUV": ("auv", "AUV", ".2f"),
    "Restaurant revenue": ("restaurant_rev", "Restaurant revenue ($m)", ".1f"),
    "Company revenue": ("company_rev", "Company revenue ($m)", ".1f"),
    "Franchise revenue": ("franchise_rev", "Franchise revenue ($m)", ".1f"),
}
_PERCENT_ROWS = {
    "sss",
    "sss_2yr_stack",
    "traffic",
    "traffic_2yr_stack",
    "ticket",
    "ticket_2yr_stack",
    "menu_price",
    "check_mix",
    "digitalmix",
    "unit_growth_yoy",
}
_MODEL_ROWS: tuple[tuple[str, str, bool], ...] = (
    ("sss", "SSS", False),
    ("sss_2yr_stack", "2-yr SSS stack", False),
    ("traffic", "Traffic", True),
    ("traffic_2yr_stack", "2-yr traffic stack", False),
    ("ticket", "Ticket", False),
    ("ticket_2yr_stack", "2-yr ticket stack", False),
    ("menu_price", "Menu pricing", True),
    ("check_mix", "Product / check mix", True),
    ("digitalmix", "Digital mix", False),
    ("days", "Fiscal days", False),
    ("units_entering_comp_base", "Estimated units entering comp base *", False),
    ("total_units_begin", "Total units begin", False),
    ("total_units_open", "Total units open", False),
    ("total_units_closed", "Total units closed", False),
    ("total_units_end", "Total units end", False),
    ("auv", "AUV", False),
    ("restaurant_rev", "Restaurant revenue", False),
    ("company_rev", "Company revenue", False),
    ("franchise_rev", "Franchise revenue", False),
    ("sss_dollars", "Comparable restaurant dollars", False),
    ("new_dollars", "New restaurant dollars", False),
    ("restaurant_rev_yoy_bridge_residual", "Bridge residual / other", False),
)
_DEFAULT_FORECASTS: dict[str, dict[str, list[float]]] = {
    "CMG": {
        "traffic": [0.3, -0.5, -1.5, 0.2],
        "menu_price": [1.5, 1.4, 1.3, 1.3],
        "check_mix": [-0.8, -0.9, -0.8, -0.6],
    },
    "CAVA": {
        "traffic": [4.8, 4.1, 3.4, 3.1],
        "menu_price": [2.6, 2.5, 2.3, 2.2],
        "check_mix": [0.8, 0.7, 0.6, 0.5],
    },
    "BROS": {
        "traffic": [1.4, 1.9, 2.3, 2.6],
        "menu_price": [2.8, 2.6, 2.4, 2.2],
        "check_mix": [0.3, 0.3, 0.3, 0.3],
    },
    "WING": {
        "traffic": [0.4, 0.7, 1.0, 1.2],
        "menu_price": [2.0, 1.9, 1.8, 1.7],
        "check_mix": [0.5, 0.5, 0.4, 0.4],
    },
    "SHAK": {
        "traffic": [1.2, 1.6, 2.0, 2.2],
        "menu_price": [2.6, 2.4, 2.2, 2.0],
        "check_mix": [0.4, 0.4, 0.4, 0.4],
    },
    "SG": {
        "traffic": [-0.5, 0.0, 0.5, 1.0],
        "menu_price": [2.4, 2.3, 2.2, 2.0],
        "check_mix": [0.5, 0.5, 0.4, 0.4],
    },
}
_SYSTEMWIDE_REVENUE_TICKERS = {"BROS", "WING", "SHAK"}
_COMP_BASE_LAG_QTRS = {
    "CMG": 5,
    "CAVA": 4,
    "SG": 5,
    "WING": 4,
    "SHAK": 8,
}
_ROW_STYLE_CLASS = {
    "SSS": "sss-row",
    "Traffic *": "driver-row",
    "Menu pricing *": "driver-row",
    "Product / check mix *": "driver-row",
}
_NOTES: dict[str, str] = {
    "CMG": "- Estimated units entering comp base uses company-owned restaurants open for at least 13 full calendar months; approximated with openings from five quarters earlier.",
    "CAVA": "- Estimated units entering comp base uses CAVA restaurants open 365 days or longer, including converted Zoes Kitchen locations open 365 days or longer after conversion; approximated with openings from four quarters earlier.",
    "BROS": "- BROS has system same-shop sales and the best comparable-base coverage history. Coverage is useful for the dollar bridge but is not itself an SSS percentage.",
    "WING": "- Estimated units entering comp base uses restaurants open for at least 52 full weeks; approximated with openings from four quarters earlier.",
    "SHAK": "- Estimated units entering comp base uses Company-operated Shacks open for 24 full fiscal months or longer; approximated with openings from eight quarters earlier.",
    "SG": "- Estimated units entering comp base uses shops open for 15 complete months or longer as of the first day of the reporting period; approximated with openings from five quarters earlier.",
}
_FORECAST_RATIONALE: dict[str, str] = {
    "CMG": (
        "CMG forecast logic: Q1 2026 returned to modestly positive comps, but management commentary framed Q2 "
        "near +1% and full-year 2026 as roughly flat. The forecast keeps price positive but lower than the "
        "2024/2025 inflation cycle, assumes product/check mix remains a modest drag, and lets traffic fade in "
        "the back half so the two-year stack normalizes rather than implying a sharp reacceleration."
    ),
    "CAVA": (
        "CAVA forecast logic: defaults assume positive traffic and check contribution, but with deceleration as "
        "the brand laps stronger awareness, new-market trial, and elevated recent same-restaurant sales growth."
    ),
    "BROS": (
        "BROS forecast logic: defaults assume gradual traffic improvement as the store base matures, with check "
        "growth supported by pricing and mix but not returning to the strongest inflation-period contribution."
    ),
    "WING": (
        "WING forecast logic: defaults assume steady low-single-digit SSS from modest traffic and check, with "
        "pricing/mix contribution normalizing as value, delivery, and chicken-wing cost dynamics remain important."
    ),
    "SHAK": (
        "SHAK forecast logic: defaults assume gradual traffic recovery and moderating check growth, consistent "
        "with a concept exposed to urban demand, delivery behavior, and company-operated unit maturity."
    ),
    "SG": (
        "SG forecast logic: defaults are conservative on traffic with some menu/check support, reflecting a "
        "more volatile comp base and continued dependence on digital, office lunch, and menu innovation."
    ),
}


@st.cache_data(ttl=3600, show_spinner=False)
def _live_sss_forecasts_fallback() -> pd.DataFrame:
    """Used only when an older snapshot does not yet include the SSSForecasts tab."""
    try:
        dfs = sheets_client.load_mlp_fast_casual_dataframes()
        fc = dfs.get("sss_forecasts")
        return fc if isinstance(fc, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _workbook_dfs_with_forecasts(bundle: dict[str, Any]) -> dict[str, Any]:
    dfs = dict(bundle.get("mlp_sheets", {}))
    fc = dfs.get("sss_forecasts")
    if isinstance(fc, pd.DataFrame) and not fc.empty:
        return dfs
    fallback = _live_sss_forecasts_fallback()
    if not fallback.empty:
        dfs["sss_forecasts"] = fallback
    return dfs


def _prd_sort_key(value: object) -> int:
    match = re.match(r"^(\d{4})Q([1-4])$", str(value).strip())
    if not match:
        return -1
    return int(match.group(1)) * 10 + int(match.group(2))


def _next_prd(value: object) -> str:
    match = re.match(r"^(\d{4})Q([1-4])$", str(value).strip())
    if not match:
        return "2026Q2"
    year, quarter = int(match.group(1)), int(match.group(2)) + 1
    if quarter > 4:
        year += 1
        quarter = 1
    return f"{year}Q{quarter}"


def _next_prds(last_prd: object) -> list[str]:
    out: list[str] = []
    current = last_prd
    for _ in range(_FORECAST_QUARTERS):
        current = _next_prd(current)
        out.append(current)
    return out


def _prior_year_prd(value: object) -> str | None:
    match = re.match(r"^(\d{4})Q([1-4])$", str(value).strip())
    if not match:
        return None
    return f"{int(match.group(1)) - 1}Q{match.group(2)}"


def _shift_prd(value: object, quarters: int) -> str | None:
    match = re.match(r"^(\d{4})Q([1-4])$", str(value).strip())
    if not match:
        return None
    year = int(match.group(1))
    quarter = int(match.group(2))
    ordinal = year * 4 + (quarter - 1) + quarters
    out_year, q0 = divmod(ordinal, 4)
    return f"{out_year}Q{q0 + 1}"


def _to_number(value: object) -> float:
    if pd.isna(value):
        return float("nan")
    if isinstance(value, str):
        clean = value.replace("%", "").replace(",", "").replace("$", "").strip()
        if clean in {"", "-", "—", "nan", "None"}:
            return float("nan")
        return float(pd.to_numeric(clean, errors="coerce"))
    return float(pd.to_numeric(value, errors="coerce"))


def _fmt(value: object, row_key: str) -> str:
    if row_key == "__estimate_marker":
        return str(value) if isinstance(value, str) else ""
    if row_key == "__blank":
        return ""
    if row_key == "Prd_End":
        ts = pd.to_datetime(value, errors="coerce")
        return "—" if pd.isna(ts) else ts.strftime("%Y-%m-%d")
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(v):
        return "—"
    if row_key in _PERCENT_ROWS:
        return f"{v:.1f}%"
    if row_key in {
        "days",
        "units_entering_comp_base",
        "total_units_begin",
        "total_units_open",
        "total_units_closed",
        "total_units_end",
    }:
        return f"{v:,.0f}"
    if row_key in {
        "restaurant_rev",
        "company_rev",
        "franchise_rev",
        "sss_dollars",
        "new_dollars",
        "restaurant_rev_yoy_bridge_residual",
    }:
        return f"${v:,.1f}m"
    return f"{v:,.2f}"


def _clean_wide(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Ticker"] = out["Ticker"].astype(str).str.strip().str.upper()
    out["Prd_Nm"] = out["Prd_Nm"].astype(str).str.strip()
    for col in out.columns:
        if col not in {"Ticker", "peer_or_focus", "Prd_Nm", "Prd_End", "isEst"} and not col.endswith("_footnote"):
            out[col] = out[col].map(_to_number)
    if "Prd_End" in out.columns:
        out["Prd_End"] = pd.to_datetime(out["Prd_End"], errors="coerce")
    return out


def _extra_common_name_wide(dfs: dict[str, Any], common_names: tuple[str, ...]) -> pd.DataFrame:
    hist = dfs.get("historical_values")
    metrics = dfs.get("metric_names")
    if not isinstance(hist, pd.DataFrame) or not isinstance(metrics, pd.DataFrame):
        return pd.DataFrame(columns=["Ticker", "Prd_Nm", *common_names])
    h = hist.copy()
    m = metrics.copy()
    for col in ("Ticker", "Metric"):
        h[col] = h[col].astype(str).str.strip()
        m[col] = m[col].astype(str).str.strip()
    h["Ticker"] = h["Ticker"].str.upper()
    m["Ticker"] = m["Ticker"].str.upper()
    m["CommonName"] = m["CommonName"].astype(str).str.strip()
    mapper = m[m["CommonName"].isin(common_names)][["Ticker", "Metric", "CommonName"]]
    if mapper.empty:
        return pd.DataFrame(columns=["Ticker", "Prd_Nm", *common_names])
    joined = h.merge(mapper, on=["Ticker", "Metric"], how="inner")
    joined["MetricValue"] = joined["MetricValue"].map(_to_number)
    return (
        joined.pivot_table(index=["Ticker", "Prd_Nm"], columns="CommonName", values="MetricValue", aggfunc="last")
        .reset_index()
        .rename_axis(columns=None)
    )


def _merge_extra_metrics(wide: pd.DataFrame, dfs: dict[str, Any]) -> pd.DataFrame:
    extra = _extra_common_name_wide(dfs, ("menu_price", "check_mix"))
    out = wide.copy()
    for col in ("menu_price", "check_mix"):
        if col not in out.columns:
            out[col] = float("nan")
    if extra.empty:
        return _merge_fiscal_days(out, dfs)
    merged = out.merge(extra, on=["Ticker", "Prd_Nm"], how="left", suffixes=("", "_extra"))
    for col in ("menu_price", "check_mix"):
        extra_col = f"{col}_extra"
        if extra_col in merged.columns:
            merged[col] = merged[extra_col].combine_first(merged[col])
            merged = merged.drop(columns=[extra_col])
    return _merge_fiscal_days(merged, dfs)


def _merge_fiscal_days(wide: pd.DataFrame, dfs: dict[str, Any]) -> pd.DataFrame:
    fiscal_dates = dfs.get("fiscal_dates")
    out = wide.copy()
    if "days" not in out.columns:
        out["days"] = float("nan")
    if not isinstance(fiscal_dates, pd.DataFrame) or fiscal_dates.empty:
        return out
    needed = {"Ticker", "Prd_Nm", "days"}
    if not needed.issubset(set(fiscal_dates.columns)):
        return out
    cols = ["Ticker", "Prd_Nm", "days"]
    if "Prd_End" in fiscal_dates.columns:
        cols.append("Prd_End")
    if "isEst" in fiscal_dates.columns:
        cols.append("isEst")
    days = fiscal_dates[cols].copy()
    days["Ticker"] = days["Ticker"].astype(str).str.strip().str.upper()
    days["Prd_Nm"] = days["Prd_Nm"].astype(str).str.strip()
    days = days.drop_duplicates(subset=["Ticker", "Prd_Nm"], keep="last")
    days["days"] = days["days"].map(_to_number)
    if "Prd_End" in days.columns:
        days["Prd_End"] = pd.to_datetime(days["Prd_End"], errors="coerce")
    merged = out.merge(days, on=["Ticker", "Prd_Nm"], how="left", suffixes=("", "_fiscal"))
    if "days_fiscal" in merged.columns:
        merged["days"] = merged["days_fiscal"].combine_first(merged["days"])
        merged = merged.drop(columns=["days_fiscal"])
    if "Prd_End_fiscal" in merged.columns:
        merged["Prd_End"] = merged["Prd_End_fiscal"].combine_first(pd.to_datetime(merged["Prd_End"], errors="coerce"))
        merged = merged.drop(columns=["Prd_End_fiscal"])
    if "isEst_fiscal" in merged.columns:
        merged["isEst"] = merged["isEst_fiscal"].combine_first(merged.get("isEst", ""))
        merged = merged.drop(columns=["isEst_fiscal"])
    return merged


def _available_tickers(wide: pd.DataFrame) -> tuple[str, ...]:
    present = set(wide["Ticker"].dropna().astype(str).str.upper())
    return tuple(t for t in _TICKERS if t in present)


def _ticker_actuals(wide: pd.DataFrame, ticker: str) -> pd.DataFrame:
    out = wide[wide["Ticker"] == ticker].copy()
    return out.sort_values("Prd_Nm", key=lambda s: s.map(_prd_sort_key), kind="stable")


def _sheet_forecast_defaults(dfs: dict[str, Any], ticker: str, periods: list[str]) -> pd.DataFrame:
    raw = dfs.get("sss_forecasts")
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame()
    need = {"Ticker", "Prd_Nm", "CommonName", "Value"}
    if not need.issubset(set(raw.columns)):
        return pd.DataFrame()
    df = raw.copy()
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["Prd_Nm"] = df["Prd_Nm"].astype(str).str.strip()
    df["CommonName"] = df["CommonName"].astype(str).str.strip()
    df = df[(df["Ticker"] == ticker) & df["Prd_Nm"].isin(periods)]
    if df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for key, label in (
        ("traffic", "Traffic"),
        ("menu_price", "Menu pricing"),
        ("check_mix", "Product / check mix"),
    ):
        row: dict[str, Any] = {"Driver": label, "_key": key}
        sub = df[df["CommonName"] == key].drop_duplicates(subset=["Prd_Nm"], keep="last")
        values = sub.set_index("Prd_Nm")["Value"].to_dict()
        for i, period in enumerate(periods):
            fallback = _driver_default_value(ticker, key, i)
            row[period] = _to_number(values.get(period, fallback))
        rows.append(row)
    return pd.DataFrame(rows)


def _forecast_default_footnotes(dfs: dict[str, Any], ticker: str) -> dict[tuple[str, str], str]:
    raw = dfs.get("sss_forecasts")
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return {}
    need = {"Ticker", "Prd_Nm", "CommonName", "Footnote"}
    if not need.issubset(set(raw.columns)):
        return {}
    df = raw.copy()
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["Prd_Nm"] = df["Prd_Nm"].astype(str).str.strip()
    df["CommonName"] = df["CommonName"].astype(str).str.strip()
    df = df[(df["Ticker"] == ticker) & (df["Footnote"].astype(str).str.strip() != "")]
    label_by_key = {
        "traffic": "Traffic *",
        "menu_price": "Menu pricing *",
        "check_mix": "Product / check mix *",
    }
    out: dict[tuple[str, str], str] = {}
    for _, row in df.iterrows():
        label = label_by_key.get(str(row["CommonName"]))
        if label:
            out[(label, str(row["Prd_Nm"]))] = str(row["Footnote"]).strip()
    return out


def _driver_default_value(ticker: str, key: str, idx: int) -> float:
    defaults = _DEFAULT_FORECASTS.get(ticker, _DEFAULT_FORECASTS[_DEFAULT_TICKER])
    values = defaults[key]
    return float(values[min(idx, len(values) - 1)])


def _default_driver_table(ticker: str, periods: list[str], dfs: dict[str, Any] | None = None) -> pd.DataFrame:
    if dfs is not None:
        sheet_defaults = _sheet_forecast_defaults(dfs, ticker, periods)
        if not sheet_defaults.empty:
            return sheet_defaults
    defaults = _DEFAULT_FORECASTS.get(ticker, _DEFAULT_FORECASTS[_DEFAULT_TICKER])
    rows: list[dict[str, Any]] = []
    for key, label in (
        ("traffic", "Traffic"),
        ("menu_price", "Menu pricing"),
        ("check_mix", "Product / check mix"),
    ):
        row: dict[str, Any] = {"Driver": label, "_key": key}
        values = defaults[key]
        for i, period in enumerate(periods):
            row[period] = values[min(i, len(values) - 1)]
        rows.append(row)
    return pd.DataFrame(rows)


def _driver_values(ticker: str, periods: list[str], *, selected_ticker: str, dfs: dict[str, Any] | None = None) -> pd.DataFrame:
    if ticker != selected_ticker:
        return _default_driver_table(ticker, periods, dfs)
    key = f"sss_model_driver_editor_{_DRIVER_STATE_VERSION}_{ticker}_{'_'.join(periods)}"
    stored = st.session_state.get(key)
    if isinstance(stored, pd.DataFrame):
        return stored.copy()
    return _default_driver_table(ticker, periods, dfs)


def _driver_lookup(drivers: pd.DataFrame, row_key: str, period: str) -> float:
    row = drivers[drivers["_key"] == row_key]
    if row.empty or period not in row.columns:
        return float("nan")
    return _to_number(row.iloc[0][period])


def _period_lookup(actuals: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Latest row per fiscal label; workbook joins can contain duplicate period rows."""
    if actuals.empty:
        return {}
    compact = actuals.drop_duplicates(subset=["Prd_Nm"], keep="last")
    return compact.set_index("Prd_Nm").to_dict("index")


def _forecast_frame(
    actuals: pd.DataFrame,
    ticker: str,
    periods: list[str],
    *,
    selected_ticker: str,
    dfs: dict[str, Any] | None = None,
) -> pd.DataFrame:
    drivers = _driver_values(ticker, periods, selected_ticker=selected_ticker, dfs=dfs)
    hist_lookup = _period_lookup(actuals)
    rows: list[dict[str, Any]] = []
    latest = actuals.iloc[-1]
    unit_open_lookup = {
        str(row["Prd_Nm"]): _to_number(row.get("total_units_open", float("nan")))
        for _, row in actuals.iterrows()
    }
    comp_lag = _COMP_BASE_LAG_QTRS.get(ticker)
    for period in periods:
        prior_period = _prior_year_prd(period)
        prior = hist_lookup.get(prior_period or "", {})
        traffic = _driver_lookup(drivers, "traffic", period)
        menu_price = _driver_lookup(drivers, "menu_price", period)
        check_mix = _driver_lookup(drivers, "check_mix", period)
        ticket = menu_price + check_mix
        sss = traffic + ticket
        prior_sss = _to_number(prior.get("sss", float("nan")))
        prior_traffic = _to_number(prior.get("traffic", float("nan")))
        prior_ticket = _to_number(prior.get("ticket", float("nan")))
        prior_rev = _to_number(prior.get("restaurant_rev", float("nan")))
        prior_company_rev = _to_number(prior.get("company_rev", float("nan")))
        prior_franchise_rev = _to_number(prior.get("franchise_rev", float("nan")))
        prior_auv = _to_number(prior.get("auv", float("nan")))
        prior_days = _to_number(prior.get("days", float("nan")))
        days = prior_days if pd.notna(prior_days) else _to_number(latest.get("days", float("nan")))
        prior_end = pd.to_datetime(prior.get("Prd_End", pd.NaT), errors="coerce")
        prd_end = prior_end + pd.DateOffset(years=1) if pd.notna(prior_end) else pd.NaT
        day_factor = days / prior_days if pd.notna(days) and pd.notna(prior_days) and prior_days else 1.0
        latest_units = _to_number(latest.get("total_units_end", float("nan")))
        prior_units_begin = _to_number(prior.get("total_units_begin", float("nan")))
        prior_units_open = _to_number(prior.get("total_units_open", float("nan")))
        prior_units_closed = _to_number(prior.get("total_units_closed", float("nan")))
        units_begin = latest_units
        units_open = prior_units_open
        units_closed = prior_units_closed
        units_end = (
            units_begin + units_open - units_closed
            if pd.notna(units_begin) and pd.notna(units_open) and pd.notna(units_closed)
            else float("nan")
        )
        if pd.isna(units_end):
            units_end = prior_units_begin
        unit_open_lookup[period] = units_open
        comp_coverage = _to_number(prior.get("SystemCompBaseCoverage", float("nan")))
        comp_units = _to_number(prior.get("units_entering_comp_base", float("nan")))
        if comp_lag is not None:
            entering_prd = _shift_prd(period, -comp_lag)
            entering_units = _to_number(unit_open_lookup.get(entering_prd, float("nan")))
            if pd.notna(entering_units):
                comp_units = entering_units
        restaurant_rev = prior_rev * day_factor * (1 + (sss / 100)) if pd.notna(prior_rev) else float("nan")
        company_rev = (
            prior_company_rev * day_factor * (1 + (sss / 100))
            if pd.notna(prior_company_rev)
            else float("nan")
        )
        franchise_rev = (
            prior_franchise_rev * day_factor * (1 + (sss / 100))
            if pd.notna(prior_franchise_rev)
            else float("nan")
        )
        auv = prior_auv * (1 + (sss / 100)) if pd.notna(prior_auv) else float("nan")
        comp_sales_base = prior_rev * day_factor if pd.notna(prior_rev) else float("nan")
        sss_dollars = comp_sales_base * (sss / 100) * comp_coverage if pd.notna(comp_sales_base) and pd.notna(comp_coverage) else float("nan")
        row = {
            "Ticker": ticker,
            "Prd_Nm": period,
            "Prd_End": prd_end,
            "isEst": "E",
            "is_forecast": True,
            "sss": sss,
            "sss_2yr_stack": sss + prior_sss if pd.notna(prior_sss) else float("nan"),
            "traffic": traffic,
            "traffic_2yr_stack": traffic + prior_traffic if pd.notna(prior_traffic) else float("nan"),
            "ticket": ticket,
            "ticket_2yr_stack": ticket + prior_ticket if pd.notna(prior_ticket) else float("nan"),
            "menu_price": menu_price,
            "check_mix": check_mix,
            "digitalmix": _to_number(latest.get("digitalmix", float("nan"))),
            "days": days,
            "SystemCompBaseCoverage": comp_coverage,
            "comparable_units": comp_units,
            "units_entering_comp_base": comp_units,
            "total_units_begin": units_begin,
            "total_units_open": units_open,
            "total_units_closed": units_closed,
            "total_units_end": units_end,
            "auv": auv,
            "restaurant_rev": restaurant_rev,
            "company_rev": company_rev,
            "franchise_rev": franchise_rev,
            "sss_dollars": sss_dollars,
            "new_dollars": restaurant_rev - prior_rev - sss_dollars
            if pd.notna(restaurant_rev) and pd.notna(prior_rev) and pd.notna(sss_dollars)
            else float("nan"),
            "restaurant_rev_yoy_bridge_residual": 0.0
            if pd.notna(restaurant_rev) and pd.notna(prior_rev) and pd.notna(sss_dollars)
            else float("nan"),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _full_model_for_ticker(
    wide: pd.DataFrame,
    ticker: str,
    *,
    selected_ticker: str,
    dfs: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    actuals = _ticker_actuals(wide, ticker)
    periods = _next_prds(actuals["Prd_Nm"].iloc[-1])
    forecast = _forecast_frame(actuals, ticker, periods, selected_ticker=selected_ticker, dfs=dfs)
    return actuals, forecast, periods


def _all_ticker_chart_frame(wide: pd.DataFrame, selected_ticker: str, dfs: dict[str, Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for ticker in _available_tickers(wide):
        actuals, forecast, _ = _full_model_for_ticker(wide, ticker, selected_ticker=selected_ticker, dfs=dfs)
        hist = actuals[actuals["Prd_Nm"].map(_prd_sort_key) >= _prd_sort_key(_CHART_START_PRD)].copy()
        hist["Type"] = "Actual"
        connector = actuals.tail(1).copy()
        connector["Type"] = "Forecast"
        fc = forecast.copy()
        fc["Type"] = "Forecast"
        frames.append(pd.concat([hist, connector, fc], ignore_index=True))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _line_chart(df: pd.DataFrame, metric_label: str) -> Any:
    if alt is None or df.empty:
        return None
    metric_col, y_title, fmt = _CHART_METRICS[metric_label]
    plot = df[["Ticker", "Prd_Nm", "Type", metric_col]].copy()
    plot = plot.rename(columns={metric_col: "value"}).dropna(subset=["value"])
    x_order = sorted(plot["Prd_Nm"].astype(str).unique(), key=_prd_sort_key)
    return (
        alt.Chart(plot)
        .mark_line(point=True, strokeWidth=2.25)
        .encode(
            x=alt.X("Prd_Nm:N", title="Fiscal quarter", sort=x_order),
            y=alt.Y("value:Q", title=y_title),
            color=alt.Color("Ticker:N", sort=list(_TICKERS)),
            strokeDash=alt.StrokeDash(
                "Type:N",
                legend=None,
                scale=alt.Scale(domain=["Actual", "Forecast"], range=[[1, 0], [5, 4]]),
            ),
            tooltip=[
                alt.Tooltip("Ticker:N"),
                alt.Tooltip("Prd_Nm:N", title="Quarter"),
                alt.Tooltip("Type:N"),
                alt.Tooltip("value:Q", title=metric_label, format=fmt),
            ],
        )
        .properties(height=390)
        .configure_view(strokeWidth=0)
    )


def _forecast_summary_table(
    wide: pd.DataFrame,
    tickers: tuple[str, ...],
    *,
    selected_ticker: str,
    dfs: dict[str, Any],
) -> pd.DataFrame:
    row_labels = ["Last Period", "Current Period", "Period+1", "Period+2", "Period+3"]
    rows: list[dict[str, str]] = [{"Period": label} for label in row_labels]
    for ticker in tickers:
        actuals, forecast, _ = _full_model_for_ticker(wide, ticker, selected_ticker=selected_ticker, dfs=dfs)
        values = [actuals.iloc[-1].get("sss", float("nan")), *forecast["sss"].tolist()]
        for row, value in zip(rows, values):
            row[ticker] = _fmt(value, "sss")
    return pd.DataFrame(rows)


def _model_display_table(
    actuals: pd.DataFrame,
    forecast: pd.DataFrame,
    ticker: str,
    dfs: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[tuple[str, str], int], list[str]]:
    hist = actuals[actuals["Prd_Nm"].map(_prd_sort_key) >= _prd_sort_key(_CHART_START_PRD)].copy()
    combined = pd.concat([hist, forecast], ignore_index=True)
    hist_lookup = _period_lookup(actuals)
    if "traffic_2yr_stack" not in combined.columns:
        combined["traffic_2yr_stack"] = float("nan")
    if "ticket_2yr_stack" not in combined.columns:
        combined["ticket_2yr_stack"] = float("nan")
    combined["traffic_2yr_stack"] = combined["traffic_2yr_stack"].combine_first(
        combined.apply(
            lambda r: r["traffic"]
            + _to_number(hist_lookup.get(_prior_year_prd(r["Prd_Nm"]) or "", {}).get("traffic", float("nan")))
            if pd.notna(r.get("traffic", float("nan")))
            else float("nan"),
            axis=1,
        )
    )
    combined["ticket_2yr_stack"] = combined["ticket_2yr_stack"].combine_first(
        combined.apply(
            lambda r: r["ticket"]
            + _to_number(hist_lookup.get(_prior_year_prd(r["Prd_Nm"]) or "", {}).get("ticket", float("nan")))
            if pd.notna(r.get("ticket", float("nan")))
            else float("nan"),
            axis=1,
        )
    )
    rows: list[dict[str, str]] = []
    footnote_candidates: list[tuple[str, str, str]] = []

    def _add_footnote(label: str, period: str, note: object) -> None:
        if pd.isna(note):
            return
        note_s = str(note).strip()
        if not note_s or note_s.lower() in {"nan", "none", "<na>", "na", "null"}:
            return
        footnote_candidates.append((label, period, note_s))

    estimate_row: dict[str, str] = {"Metric": ""}
    prd_end_row: dict[str, str] = {"Metric": "Prd_End"}
    for _, period_row in combined.iterrows():
        prd = str(period_row["Prd_Nm"])
        is_est = str(period_row.get("isEst", "")).strip().upper() == "E"
        is_forecast = period_row.get("is_forecast", False) is True
        estimate_row[prd] = "E" if is_forecast or is_est else ""
        prd_end_row[prd] = _fmt(period_row.get("Prd_End", pd.NaT), "Prd_End")
    rows.extend([estimate_row, prd_end_row])
    for row_key, label, is_driver in _MODEL_ROWS:
        if row_key == "restaurant_rev" and ticker in _SYSTEMWIDE_REVENUE_TICKERS:
            label = "Systemwide sales"
        display_label = f"{label} *" if is_driver else label
        row: dict[str, str] = {"Metric": display_label}
        for _, period_row in combined.iterrows():
            prd = str(period_row["Prd_Nm"])
            row[prd] = _fmt(period_row.get(row_key, float("nan")), row_key)
            _add_footnote(display_label, prd, period_row.get(f"{row_key}_footnote", ""))
        rows.append(row)
    if dfs is not None:
        for (label, period), note in _forecast_default_footnotes(dfs, ticker).items():
            footnote_candidates.append((label, period, note))
    latest_notes = sorted(footnote_candidates, key=lambda item: _prd_sort_key(item[1]))
    footnote_cells = {
        (label, period): (i, note)
        for i, (label, period, note) in enumerate(latest_notes, start=1)
    }
    footnotes = [note for _, _, note in latest_notes]
    return pd.DataFrame(rows), footnote_cells, footnotes


def _italicize_two_year_rows(row: pd.Series) -> list[str]:
    style = "font-style: italic;" if str(row.get("Metric", "")).startswith("2-yr") else ""
    return [style] * len(row)


def _render_model_table(
    model_table: pd.DataFrame,
    footnote_cells: dict[tuple[str, str], tuple[int, str]],
    footnotes: list[str],
) -> None:
    estimate_cols = {
        str(col)
        for col in model_table.columns
        if col != "Metric" and str(model_table.loc[0, col]).strip().upper() == "E"
    }
    header_cells = "".join(
        f'<th class="{"estimate-col" if str(col) in estimate_cols else ""}">{html.escape(str(col))}</th>'
        for col in model_table.columns
    )
    body_rows: list[str] = []
    for _, row in model_table.iterrows():
        metric = str(row.get("Metric", ""))
        row_classes = []
        if metric.startswith("2-yr"):
            row_classes.append("two-year-row")
        if metric in _ROW_STYLE_CLASS:
            row_classes.append(_ROW_STYLE_CLASS[metric])
        row_class = " ".join(row_classes)
        cell_html: list[str] = []
        for col in model_table.columns:
            value = html.escape(str(row[col]))
            note = footnote_cells.get((metric, str(col)))
            cell_classes = []
            if note is not None:
                cell_classes.append("footnote-cell")
            if str(col).startswith("2026") or str(col).startswith("2027"):
                if metric == "SSS":
                    cell_classes.append("sss-estimate-cell")
                elif metric in {"Traffic *", "Menu pricing *", "Product / check mix *"}:
                    cell_classes.append("driver-estimate-cell")
            if str(col) in estimate_cols:
                cell_classes.append("estimate-col")
            cell_class = " ".join(cell_classes)
            if note is not None:
                note_num, note_text = note
                suffix = (
                    '<details class="cell-note">'
                    f"<summary>{note_num}</summary>"
                    f'<div class="cell-note-popover">{html.escape(note_text)}</div>'
                    "</details>"
                )
            else:
                suffix = ""
            cell_html.append(f'<td class="{cell_class}">{value}{suffix}</td>')
        cells = "".join(cell_html)
        body_rows.append(f'<tr class="{row_class}">{cells}</tr>')
    table_html = "\n".join(body_rows)
    components.html(
        f"""
<div id="model-scroll-wrap">
  <table class="model-table">
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{table_html}</tbody>
  </table>
</div>
<style>
  html,
  body {{
    margin: 0;
    padding: 0;
  }}
  #model-scroll-wrap {{
    width: 100%;
    height: 600px;
    overflow: auto;
    border: 1px solid #ded8cf;
    border-radius: 14px;
    background: #fbfaf8;
  }}
  .model-table {{
    border-collapse: separate;
    border-spacing: 0;
    min-width: max-content;
    width: max-content;
    font-family: Karla, Arial, sans-serif;
    color: #221f1c;
  }}
  .model-table th,
  .model-table td {{
    border-right: 1px solid #e2ddd5;
    border-bottom: 1px solid #e2ddd5;
    padding: 0.32rem 0.44rem;
    min-width: 64px;
    white-space: nowrap;
    text-align: left;
    font-size: 0.78rem;
  }}
  .model-table th {{
    position: sticky;
    top: 0;
    z-index: 2;
    background: #f6f4f0;
    color: #6b665f;
    font-weight: 700;
  }}
  .model-table th:first-child,
  .model-table td:first-child {{
    position: sticky;
    left: 0;
    z-index: 3;
    min-width: 220px;
    background: #fbfaf8;
    font-weight: 700;
  }}
  .model-table th:first-child {{
    z-index: 4;
    background: #f6f4f0;
  }}
  .model-table tr.two-year-row td {{
    font-style: italic;
  }}
  .model-table tr.sss-row td:first-child,
  .model-table tr.sss-row td:not(:first-child) {{
    color: #245b9e;
    font-weight: 800;
  }}
  .model-table tr.driver-row td:first-child,
  .model-table tr.driver-row td:not(:first-child) {{
    color: #6a1b9a;
    font-weight: 800;
  }}
  .model-table td.sss-estimate-cell {{
    color: #245b9e;
    font-weight: 800;
  }}
  .model-table td.driver-estimate-cell {{
    color: #6a1b9a;
    font-weight: 800;
  }}
  .model-table th.estimate-col,
  .model-table td.estimate-col {{
    background: #eef4ff;
  }}
  .model-table td.estimate-col.footnote-cell {{
    background: #fff3bf;
    box-shadow: inset 0 0 0 9999px rgba(255, 243, 191, 0.55);
  }}
  .model-table td.footnote-cell {{
    background: #fff3bf;
    box-shadow: inset 0 0 0 9999px rgba(255, 243, 191, 0.55);
  }}
  .cell-note {{
    display: inline-block;
    position: relative;
    margin-left: 3px;
  }}
  .cell-note summary {{
    display: inline;
    cursor: pointer;
    list-style: none;
    font-size: 0.66em;
    font-weight: 700;
    color: #7a4d00;
  }}
  .cell-note summary::-webkit-details-marker {{
    display: none;
  }}
  .cell-note-popover {{
    position: absolute;
    right: 0;
    top: 1.25em;
    z-index: 20;
    width: 270px;
    white-space: normal;
    padding: 0.55rem 0.65rem;
    border: 1px solid #c7aa52;
    border-radius: 8px;
    background: #fff9df;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
    color: #2f2921;
    font-size: 0.78rem;
    line-height: 1.35;
  }}
</style>
<script>
  const wrap = document.getElementById("model-scroll-wrap");
  if (wrap) {{
    requestAnimationFrame(() => {{
      wrap.scrollLeft = wrap.scrollWidth;
    }});
    document.addEventListener("click", (event) => {{
      wrap.querySelectorAll("details.cell-note[open]").forEach((detail) => {{
        if (!detail.contains(event.target)) {{
          detail.removeAttribute("open");
        }}
      }});
    }});
  }}
</script>
""",
        height=630,
        scrolling=True,
    )


def _render_driver_editor(ticker: str, periods: list[str], dfs: dict[str, Any]) -> None:
    key = f"sss_model_driver_editor_{_DRIVER_STATE_VERSION}_{ticker}_{'_'.join(periods)}"
    default = _default_driver_table(ticker, periods, dfs)
    if key not in st.session_state:
        st.session_state[key] = default
    display_df = st.session_state[key].copy()
    editor = st.data_editor(
        display_df.drop(columns=["_key"]),
        hide_index=True,
        use_container_width=True,
        key=f"{key}_widget",
        disabled=["Driver"],
        column_config={
            "Driver": st.column_config.TextColumn("Editable forecast driver"),
            **{
                period: st.column_config.NumberColumn(period, format="%.1f%%", step=0.1)
                for period in periods
            },
        },
    )
    edited = editor.merge(default[["Driver", "_key"]], on="Driver", how="left")
    st.session_state[key] = edited[["Driver", "_key", *periods]]


def main() -> None:
    st.title("SSS forecast")
    st.markdown(
        """
This page translates the historical SSS bridge into a forward view for each ticker. The default forecasts are
judgmental base cases built from recent reported traffic, ticket / price / mix disclosures, two-year stack
normalization, and available management commentary; the selected-company model below lets those assumptions be
changed directly.
"""
    )

    bundle = get_dashboard_bundle_or_stop(include_feature_tables=False)
    raw_wide = bundle.get("brand_period_wide")
    if not isinstance(raw_wide, pd.DataFrame) or raw_wide.empty:
        st.warning("No `brand_period_wide` data is available for the forecast page.")
        st.stop()
    workbook_dfs = _workbook_dfs_with_forecasts(bundle)
    wide = _merge_extra_metrics(_clean_wide(raw_wide), workbook_dfs)
    tickers = _available_tickers(wide)
    if not tickers:
        st.warning("No peer tickers are available in `brand_period_wide`.")
        st.stop()

    # Editable model below is scoped to focus brands (see _MODELABLE_TICKERS).
    # Peers (WING/SHAK/SG) still appear in the top summary table and chart for
    # cohort context, but their forecast models are not exposed.
    modelable_tickers = tuple(t for t in tickers if t in _MODELABLE_TICKERS)
    if not modelable_tickers:
        st.warning("No focus tickers (CMG / BROS / CAVA) are present in `brand_period_wide`.")
        st.stop()

    selected = str(st.session_state.get("sss_model_company", _DEFAULT_TICKER)).upper()
    if selected not in modelable_tickers:
        selected = _DEFAULT_TICKER if _DEFAULT_TICKER in modelable_tickers else modelable_tickers[0]
        # Reset stale session state so the selectbox below doesn't try to display
        # a now-hidden ticker as its initial value.
        st.session_state["sss_model_company"] = selected
    st.markdown("[Jump to the editable forecast model](#forecast-model)")
    st.subheader("Forecast summary")
    st.dataframe(
        _forecast_summary_table(wide, tickers, selected_ticker=selected, dfs=workbook_dfs),
        hide_index=True,
        use_container_width=True,
    )
    metric = st.selectbox("Chart metric", options=list(_CHART_METRICS), index=0)

    if st.session_state.get("sss_model_last_ticker") != selected:
        for key in list(st.session_state):
            if key.startswith("sss_model_driver_editor_"):
                del st.session_state[key]
        st.session_state["sss_model_last_ticker"] = selected

    actuals, forecast, forecast_periods = _full_model_for_ticker(
        wide,
        selected,
        selected_ticker=selected,
        dfs=workbook_dfs,
    )
    chart_df = _all_ticker_chart_frame(wide, selected, workbook_dfs)
    st.subheader(f"{metric} history and forecast")
    chart = _line_chart(chart_df, metric)
    if chart is not None:
        st.altair_chart(chart, use_container_width=True)
    else:
        st.line_chart(chart_df.pivot_table(index="Prd_Nm", columns="Ticker", values=_CHART_METRICS[metric][0]))

    st.markdown("---")
    selected = st.selectbox(
        "Model company",
        options=modelable_tickers,
        index=modelable_tickers.index(selected),
        key="sss_model_company",
        help="Editable forecast model is scoped to the focus brands (CMG, BROS, CAVA). "
        "Peers WING / SHAK / SG appear in the summary table and chart above for cohort context.",
    )
    actuals, forecast, forecast_periods = _full_model_for_ticker(
        wide,
        selected,
        selected_ticker=selected,
        dfs=workbook_dfs,
    )
    st.markdown('<div id="forecast-model"></div>', unsafe_allow_html=True)
    st.subheader(f"{selected} forecast model")
    st.caption(_FORECAST_RATIONALE.get(selected, "Forecast assumptions are judgmental and can be changed in the editable driver table."))
    _render_driver_editor(selected, forecast_periods, workbook_dfs)
    actuals, forecast, _ = _full_model_for_ticker(
        wide,
        selected,
        selected_ticker=selected,
        dfs=workbook_dfs,
    )

    model_table, footnote_cells, footnotes = _model_display_table(
        actuals,
        forecast,
        selected,
        workbook_dfs,
    )
    _render_model_table(model_table, footnote_cells, footnotes)

    st.subheader("Company notes")
    st.info(_NOTES.get(selected, "Definitions differ by company; the model keeps the same standardized rows across the peer set."))
    st.caption(
        "`menu_price` and `check_mix` are pulled from workbook CommonNames when present. Historical blanks mean the company did not have that metric mapped, not that the value is zero."
    )


main()
