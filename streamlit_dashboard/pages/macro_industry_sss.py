"""Macro- and industry-level fast casual view: peer SSS index vs tickers and quarterly detail."""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

import macro_data
from streamlit_dashboard.data_loader import dataframe_revision, get_dashboard_bundle_or_stop
from streamlit_dashboard.gtrends_loader import load_gtrends_monthly_csv
from streamlit_dashboard.peer_gtrends_utils import (
    peer_pricing_by_calendar_quarter_end_from_wide,
    peer_sss_by_calendar_quarter_end_from_wide,
    peer_traffic_by_calendar_quarter_end_from_wide,
)
from streamlit_dashboard.pages.peer_basket_metrics import (
    _DISPLAY_TICKERS,
    _DEFAULT_TABLE_START,
    _build_quarterly_peer_grid,
    _format_percent_table,
    _prd_sort_key,
    _reorder_index_default_start,
)

try:
    import altair as alt
except ImportError:
    alt = None  # type: ignore[misc, assignment]

# National chart: **USD levels** ``equiv_usd_1000_at_<year>avg_*`` (dollars today for a $1000 basket at that
# year’s average — see ``macro_data``). ``PeerSSSIndex`` (ppt) shares the x-axis with a **right-hand** y-axis.
# Bundle column names may use 2019, 2021, etc.; we resolve the best matching level column per series.
_MACRO_EQUIV_ANCHOR_YEAR = int(macro_data.SPEND_EQUIV_BASE_YEAR)
# (level suffix after ``avg_``, short legend label; include ``{}`` only if the year should appear)
_MACRO_EQUIV_CHART_META: tuple[tuple[str, str], ...] = (
    ("ppi_retail_shopping_rent_nsa", "Retail rent"),
    ("broilers_lb_paste", "Chicken"),
    ("limited_svc_hourly_sa", "Limited-service wage"),
    ("beef_cattle_cwt_paste", "Beef cattle"),
)
# Workbook peer SSS (ppt): one point per **Gregorian calendar quarter** (``Prd_End`` quarter join).
_MACRO_PEER_SSS_CHART_LABEL = "PeerSSSIndex"
_MACRO_PEER_PRICING_CHART_LABEL = "PeerPricingIndex"
_MACRO_PEER_TRAFFIC_CHART_LABEL = "PeerTrafficIndex"
_MACRO_PEER_LINE_COLOR = "#b83b5e"  # dashed pink / rose — peer SSS overlay (national + right charts)
_MACRO_PEER_PRICING_LINE_COLOR = "#6a1b9a"  # solid purple — peer ticket (ppt)
_MACRO_PEER_TRAFFIC_LINE_COLOR = "#76b7b2"  # solid teal — peer traffic (ppt)
# Tableau 10 — same order as Altair default for macro lines (peer uses ``_MACRO_PEER_LINE_COLOR``).
_MACRO_YOY_TAB10: tuple[str, ...] = (
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
)
# Section title (shown above chart; matches former Altair title styling).
_MACRO_INPUT_YOY_CHART_TITLE = (
    f"National inputs — spend-equiv USD, 3MMA ($1000 @{_MACRO_EQUIV_ANCHOR_YEAR} basket avg) + PeerSSSIndex (ppt)"
)
_PEER_INDICES_CHART_TITLE = "Peer SSS, ticket, and traffic (ppt)"

# Trailing months for macro national-inputs chart (no UI slider).
_MACRO_YOY_CHART_YEARS = 10
# Spend-equiv USD lines use a trailing **3-month moving average** (monthly series only; PeerSSS unchanged).
_MACRO_SPEND_EQUIV_INPUT_3MMA: int = 3
# Plot height; width follows the left Streamlit column (``width="container"`` in Altair).
_MACRO_INPUT_CHART_HEIGHT = 400
_CONSUMER_CHART_START = pd.Timestamp("2022-01-01")
_CONSUMER_CHART_HEIGHT = 330
_PEER_SSS_VIEW_HEIGHT = 380
_PEER_INDICES_CHART_START = pd.Timestamp("2022-03-31")
_ATTENTION_CHART_START = pd.Timestamp("2024-01-01")
_ATTENTION_CHART_HEIGHT = 330
_ATTENTION_TICKER_ORDER: tuple[str, ...] = ("CMG", "CAVA", "BROS", "SHAK", "WING", "SG")
_ATTENTION_TICKER_LABELS: dict[str, str] = {
    "CMG": "Chipotle",
    "CAVA": "CAVA",
    "BROS": "Dutch Bros",
    "SHAK": "Shake Shack",
    "WING": "Wingstop",
    "SG": "Sweetgreen",
}
_ATTENTION_TICKER_COLORS: dict[str, str] = {
    "CMG": "#4e79a7",
    "CAVA": "#f28e2b",
    "BROS": "#59a14f",
    "SHAK": "#e15759",
    "WING": "#6a1b9a",
    "SG": "#76b7b2",
}
_GTRENDS_BRAND_YOY_SPECS: dict[str, str] = {
    "CMG": "chipotle_yoy_pct",
    "CAVA": "cava_yoy_pct",
    "SHAK": "shake_shack_yoy_pct",
    "SG": "sweetgreen_yoy_pct",
}
_CONSUMER_METRIC_OPTIONS: dict[str, dict[str, Any]] = {
    "Restaurant Sales Growth": {
        "series": (
            ("Food services & drinking places", "retail_food_services_drinking_sales_millions_nsa_yoy_pct"),
            (
                "Limited-service eating places",
                "retail_sales_limited_service_eating_places_naics7222_millions_nsa_yoy_pct",
            ),
            (
                "Real restaurant demand spread (3MMA)",
                "real_restaurant_demand_sales_minus_faho_cpi_yoy_spread_pct",
            ),
        ),
        "y_title": "YoY growth (%)",
        "value_format": ".1f",
    },
    "OpenTable Seated Diners": {
        "series": (
            (
                "OpenTable fast-casual city index",
                "opentable_fast_casual_exposed_city_index_yoy_pct",
            ),
            (
                "OpenTable U.S. seated diners",
                "opentable_us_seated_diners_online_reservations_yoy_pct",
            ),
        ),
        "y_title": "YoY growth (%)",
        "value_format": ".1f",
    },
    "Metro Ridership at SF/NY Commercial Districts": {
        "series": (
            ("NYC Manhattan subway entries", "mta_manhattan_subway_entries_monthly_sum_yoy_pct"),
            ("SF financial district BART trips", "bart_sf_financial_district_origin_trips_monthly_yoy_pct"),
        ),
        "y_title": "YoY growth (%)",
        "value_format": ".1f",
    },
    "Worker Pay": {
        "series": (
            (
                "Median weekly wage/salary earnings",
                "cps_median_usual_weekly_nominal_ft_wage_salary_usd_yoy_pct",
            ),
            ("All-private hourly earnings", "fred_ces_all_private_avg_hourly_earnings_usd_sa_yoy_pct"),
            ("Headline CPI", "cpi_u_all_items_sa_index_yoy_pct"),
        ),
        "y_title": "YoY growth (%)",
        "value_format": ".1f",
    },
    "Unemployment": {
        "series": (("Unemployment rate", "unemployment_rate_pct"),),
        "y_title": "Unemployment rate (%)",
        "value_format": ".1f",
    },
    "Disposable Income": {
        "series": (("Disposable personal income", "disposable_personal_income_billion_sa_monthly_yoy_pct"),),
        "y_title": "YoY growth (%)",
        "value_format": ".1f",
    },
}
_CONSUMER_SERIES_COLORS: dict[str, str] = {
    "Food services & drinking places": "#4e79a7",
    "Limited-service eating places": "#f28e2b",
    "Real restaurant demand spread (3MMA)": "#59a14f",
    "OpenTable fast-casual city index": "#b83b5e",
    "OpenTable U.S. seated diners": "#76b7b2",
    "NYC Manhattan subway entries": "#59a14f",
    "SF financial district BART trips": "#76b7b2",
    "Median weekly wage/salary earnings": "#6a1b9a",
    "All-private hourly earnings": "#b07aa1",
    "Headline CPI": "#0a0a0a",
    "Unemployment rate": "#e15759",
    "Disposable personal income": "#edc948",
}
_CONSUMER_3MMA_COLUMNS: frozenset[str] = frozenset(
    {
        "real_restaurant_demand_sales_minus_faho_cpi_yoy_spread_pct",
        "opentable_fast_casual_exposed_city_index_yoy_pct",
        "opentable_us_seated_diners_online_reservations_yoy_pct",
    }
)
# Spread 3MMA needs a published monthly retail YoY for that month (Census/FRED); do not
# extrapolate from CPI-only rows or repeat the last valid month when retail is missing.
_CONSUMER_3MMA_REQUIRE_RAW_MONTH: frozenset[str] = frozenset(
    {"real_restaurant_demand_sales_minus_faho_cpi_yoy_spread_pct"}
)
_CONSUMER_3MMA_MIN_PERIODS: dict[str, int] = {
    "real_restaurant_demand_sales_minus_faho_cpi_yoy_spread_pct": 3,
}
_CONSUMER_DASHED_SERIES: frozenset[str] = frozenset({"Headline CPI"})
_CONSUMER_METRIC_CAPTIONS: dict[str, str] = {
    "Restaurant Sales Growth": "Traffic, measured by sales growth - pricing growth, remains above flat.",
    "OpenTable Seated Diners": "Dining remains elevated in key cities.",
    "Metro Ridership at SF/NY Commercial Districts": "Continued increases in rides into the city.",
    "Worker Pay": "Pay increases remain above inflation.",
    "Unemployment": "Ticked up but remains below 4.5%.",
    "Disposable Income": "Disposable income has grown MSD.",
}
_CONSUMER_METRIC_SOURCES: dict[str, str] = {
    "Restaurant Sales Growth": "FRED",
    "OpenTable Seated Diners": "OpenTable",
    "Metro Ridership at SF/NY Commercial Districts": "MTA, BART",
    "Worker Pay": "FRED, BLS API",
    "Unemployment": "FRED",
    "Disposable Income": "FRED",
}


def macro_yoy_series_label_to_hex(legend_order: list[str]) -> dict[str, str]:
    """Label → hex for the macro YoY Altair chart (fixed palette per series)."""
    out: dict[str, str] = {}
    i_macro = 0
    for lab in legend_order:
        if lab == _MACRO_PEER_SSS_CHART_LABEL:
            out[lab] = _MACRO_PEER_LINE_COLOR
        else:
            out[lab] = _MACRO_YOY_TAB10[i_macro % len(_MACRO_YOY_TAB10)]
            i_macro += 1
    return out


def _consumer_series_color(label: str) -> str:
    """Fixed color by consumer metric label, independent of chart position/dropdown choice."""
    if label in _CONSUMER_SERIES_COLORS:
        return _CONSUMER_SERIES_COLORS[label]
    return _MACRO_YOY_TAB10[len(label) % len(_MACRO_YOY_TAB10)]


def _naive_month_end_series(s: pd.Series) -> pd.Series:
    """Coerce to datetimes and normalize to midnight (month-end labels are date-only in practice)."""
    return pd.to_datetime(s, errors="coerce").dt.normalize()


def _filter_monthly_macro_yoy(m: pd.DataFrame, years: int) -> pd.DataFrame:
    if m.empty:
        return m
    work = m.copy()
    if isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()
    if "month_end" not in work.columns:
        return pd.DataFrame()
    work["month_end"] = _naive_month_end_series(work["month_end"])
    work = work.dropna(subset=["month_end"]).drop_duplicates(subset=["month_end"], keep="last")
    work = work.sort_values("month_end", kind="mergesort").reset_index(drop=True)
    end = work["month_end"].max()
    if pd.isna(end):
        return work
    start = end - pd.DateOffset(years=max(1, int(years)))
    return work.loc[work["month_end"] >= start].copy()


_LEVEL_SUFFIX_RE = re.compile(r"^equiv_usd_1000_at_(\d{4})avg_(.+)$")


def _equiv_anchor_years_try_order() -> tuple[int, ...]:
    y = int(macro_data.SPEND_EQUIV_BASE_YEAR)
    tail = tuple(x for x in (2021, 2019, 2020, 2022, 2023) if x != y)
    return (y, *tail)


def _find_equiv_level_column(all_cols: set[str], suffix: str) -> tuple[str, int] | None:
    for yr in _equiv_anchor_years_try_order():
        c = f"equiv_usd_1000_at_{yr}avg_{suffix}"
        if c in all_cols and not str(c).endswith("_yoy_pct"):
            return (c, yr)
    best: tuple[int, str] | None = None
    for c in all_cols:
        if str(c).endswith("_yoy_pct"):
            continue
        m = _LEVEL_SUFFIX_RE.match(str(c))
        if m and m.group(2) == suffix:
            yr = int(m.group(1))
            if best is None or yr > best[0]:
                best = (yr, str(c))
    return (best[1], best[0]) if best else None


def _build_equiv_macro_work_for_levels(
    work: pd.DataFrame,
) -> tuple[pd.DataFrame, list[tuple[str, str]]] | None:
    """Resolve spend-equiv **level** (USD) columns from the bundle (any anchor year in the column name)."""
    cols = set(work.columns)
    out_df = work.sort_values("month_end", kind="mergesort").copy().reset_index(drop=True)
    present: list[tuple[str, str]] = []
    for suffix, label_tpl in _MACRO_EQUIV_CHART_META:
        l_hit = _find_equiv_level_column(cols, suffix)
        if not l_hit:
            continue
        lvl, yr = l_hit
        lab = label_tpl.format(yr) if "{" in label_tpl else label_tpl
        present.append((lvl, lab))
    if not present:
        return None
    return out_df, present


def _prepare_macro_input_yoy_long(
    monthly: pd.DataFrame,
    *,
    years: int = 10,
) -> tuple[pd.DataFrame, list[str]] | None:
    """Return ``(long_df, legend_order)`` for spend-equiv **USD levels** + later ``PeerSSSIndex`` overlay."""
    if monthly.empty:
        return None
    work = _filter_monthly_macro_yoy(monthly, years)
    if work.empty:
        return None
    built = _build_equiv_macro_work_for_levels(work)
    if built is None:
        return None
    work2, present = built
    rows: list[dict[str, Any]] = []
    for _, r in work2.iterrows():
        me = r.get("month_end")
        for col, lab in present:
            v = pd.to_numeric(r.get(col), errors="coerce")
            if pd.notna(me) and pd.notna(v):
                me_n = _naive_month_end_series(pd.Series([me])).iloc[0]
                rows.append({"month_end": me_n, "series": lab, "value": float(v)})
    long_df = pd.DataFrame(rows)
    if long_df.empty:
        return None
    legend_order = [lab for _, lab in present]
    long_df["month_end"] = _naive_month_end_series(long_df["month_end"])
    long_df = long_df.drop_duplicates(subset=["month_end", "series"], keep="last")
    long_df = long_df.sort_values(["series", "month_end"], kind="mergesort").reset_index(drop=True)
    long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce")
    w = max(1, int(_MACRO_SPEND_EQUIV_INPUT_3MMA))
    long_df["value"] = long_df.groupby("series", sort=False)["value"].transform(
        lambda s: s.rolling(window=w, min_periods=1).mean()
    )
    return long_df, legend_order


def _append_peer_indexes_to_macro_long(
    long_df: pd.DataFrame,
    legend_order: list[str],
    brand_period_wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """Append **PeerSSSIndex** only (quarter-end ppt) for the national inputs chart."""
    if long_df.empty:
        return long_df, legend_order
    me_min = long_df["month_end"].min()
    me_max = long_df["month_end"].max()
    peer_m = peer_sss_by_calendar_quarter_end_from_wide(brand_period_wide, fiscal_dates)
    if peer_m.empty:
        return long_df, legend_order
    s = peer_m.copy()
    s["month_end"] = _naive_month_end_series(s["month_end"])
    s["series"] = _MACRO_PEER_SSS_CHART_LABEL
    s["value"] = pd.to_numeric(s["PeerSSSIndex"], errors="coerce")
    pl = s.dropna(subset=["month_end", "value"])[["month_end", "series", "value"]]
    pl = pl[(pl["month_end"] >= me_min) & (pl["month_end"] <= me_max)]
    if pl.empty:
        return long_df, legend_order
    lo = [*legend_order, _MACRO_PEER_SSS_CHART_LABEL]
    out = pd.concat([long_df, pl], ignore_index=True)
    out["month_end"] = _naive_month_end_series(out["month_end"])
    out = out.drop_duplicates(subset=["month_end", "series"], keep="last")
    return out.sort_values(["month_end", "series"], kind="mergesort").reset_index(drop=True), lo


def _prepare_peer_indices_long(
    monthly: pd.DataFrame,
    brand_period_wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
    *,
    years: int,
) -> tuple[pd.DataFrame, list[str]] | None:
    """Calendar quarter-end **PeerSSSIndex**, **PeerPricingIndex**, **PeerTrafficIndex** (ppt each)."""
    peer_s = peer_sss_by_calendar_quarter_end_from_wide(brand_period_wide, fiscal_dates)
    peer_p = peer_pricing_by_calendar_quarter_end_from_wide(brand_period_wide, fiscal_dates)
    peer_t = peer_traffic_by_calendar_quarter_end_from_wide(brand_period_wide, fiscal_dates)
    if peer_s.empty and peer_p.empty and peer_t.empty:
        return None
    work = _filter_monthly_macro_yoy(monthly, years)
    if not work.empty:
        me_min = work["month_end"].min()
        me_max = work["month_end"].max()
    else:
        ends: list[pd.Timestamp] = []
        for d in (peer_s, peer_p, peer_t):
            if not d.empty and "month_end" in d.columns:
                mx = pd.to_datetime(d["month_end"], errors="coerce").max()
                if pd.notna(mx):
                    ends.append(pd.Timestamp(mx).normalize())
        if not ends:
            return None
        me_max = max(ends)
        me_min = (me_max - pd.DateOffset(years=max(1, int(years)))).normalize()
    me_min = max(pd.Timestamp(me_min).normalize(), _PEER_INDICES_CHART_START)

    rows: list[dict[str, Any]] = []

    def _append_peer(df: pd.DataFrame, value_col: str, series_label: str) -> None:
        if df.empty or value_col not in df.columns:
            return
        p = df.copy()
        p["month_end"] = _naive_month_end_series(p["month_end"])
        for _, r in p.iterrows():
            me = r.get("month_end")
            v = pd.to_numeric(r.get(value_col), errors="coerce")
            if pd.notna(me) and pd.notna(v) and me_min <= me <= me_max:
                rows.append(
                    {
                        "month_end": pd.Timestamp(me).normalize(),
                        "series": series_label,
                        "yoy_pct": float(v),
                    }
                )

    _append_peer(peer_s, "PeerSSSIndex", _MACRO_PEER_SSS_CHART_LABEL)
    _append_peer(peer_p, "PeerPricingIndex", _MACRO_PEER_PRICING_CHART_LABEL)
    _append_peer(peer_t, "PeerTrafficIndex", _MACRO_PEER_TRAFFIC_CHART_LABEL)
    if not rows:
        return None
    long_df = pd.DataFrame(rows)
    long_df["month_end"] = _naive_month_end_series(long_df["month_end"])
    long_df = long_df.drop_duplicates(subset=["month_end", "series"], keep="last")
    order_pref = (
        _MACRO_PEER_SSS_CHART_LABEL,
        _MACRO_PEER_PRICING_CHART_LABEL,
        _MACRO_PEER_TRAFFIC_CHART_LABEL,
    )
    present = set(long_df["series"].astype(str).unique())
    leg = [lab for lab in order_pref if lab in present]
    long_df = long_df.sort_values(["month_end", "series"], kind="mergesort").reset_index(drop=True)
    return long_df, leg


def _peer_index_series_color(lab: str) -> str:
    if lab == _MACRO_PEER_SSS_CHART_LABEL:
        return _MACRO_PEER_LINE_COLOR
    if lab == _MACRO_PEER_PRICING_CHART_LABEL:
        return _MACRO_PEER_PRICING_LINE_COLOR
    if lab == _MACRO_PEER_TRAFFIC_CHART_LABEL:
        return _MACRO_PEER_TRAFFIC_LINE_COLOR
    return _MACRO_YOY_TAB10[0]


def _peer_indices_chart(
    plot_df: pd.DataFrame,
    legend_order: list[str],
    *,
    width: int | str = "container",
    height: int = _MACRO_INPUT_CHART_HEIGHT,
) -> alt.Chart | None:
    """Equal-weight peer **SSS** / **ticket** / **traffic** (ppt); dashed rose line matches national chart."""
    if plot_df.empty or alt is None:
        return None
    plot_df = plot_df.copy()
    plot_df["month_end"] = _naive_month_end_series(plot_df["month_end"])
    plot_df = plot_df.dropna(subset=["month_end", "series", "yoy_pct"])
    plot_df = plot_df.drop_duplicates(subset=["month_end", "series"], keep="last")
    plot_df = plot_df.sort_values(["series", "month_end"], kind="mergesort").reset_index(drop=True)
    y_vals = pd.to_numeric(plot_df["yoy_pct"], errors="coerce").dropna()
    if y_vals.empty:
        return None
    y_min, y_max = float(y_vals.min()), float(y_vals.max())
    pad = max((y_max - y_min) * 0.06, 0.75)
    y_lo = min(0.0, y_min - pad)
    y_hi = y_max + pad
    dash_peer = alt.FieldEqualPredicate(field="series", equal=_MACRO_PEER_SSS_CHART_LABEL)
    color_domain = list(legend_order)
    color_range = [_peer_index_series_color(lab) for lab in color_domain]
    leg = alt.Legend(
        orient="top",
        direction="horizontal",
        columns=max(len(legend_order), 1),
        title=None,
        labelLimit=0,
        labelFontSize=11,
        symbolSize=56,
        symbolStrokeWidth=2,
        padding=4,
        labelPadding=2,
        legendX=6,
        legendY=-6,
    )
    color_scale = alt.Scale(domain=color_domain, range=color_range)
    lines = (
        alt.Chart(plot_df)
        .mark_line(strokeWidth=2.25)
        .encode(
            x=alt.X(
                "month_end:T",
                title="Month-end",
                axis=alt.Axis(format="%Y", labelAngle=0, tickCount=_MACRO_YOY_CHART_YEARS + 2),
            ),
            y=alt.Y("yoy_pct:Q", title="Peer index (ppt)", scale=alt.Scale(domain=[y_lo, y_hi])),
            color=alt.Color("series:N", sort=legend_order, legend=leg, scale=color_scale),
            order=alt.Order("month_end:T"),
            strokeDash=alt.condition(dash_peer, alt.value([5, 3]), alt.value([1, 0])),
            tooltip=[
                alt.Tooltip("month_end:T", title="Month", format="%Y-%m-%d"),
                alt.Tooltip("series:N", title="What"),
                alt.Tooltip("yoy_pct:Q", title="ppt", format=".2f"),
            ],
        )
    )
    y_zero = (
        alt.Chart()
        .mark_rule(color="#0a0a0a", strokeWidth=4.25, opacity=1)
        .encode(y=alt.datum(0))
    )
    return (
        alt.layer(lines, y_zero)
        .properties(width=width, height=height, padding={"bottom": 44, "left": 2, "right": 6})
        .configure_view(strokeWidth=0, clip=False)
        .configure_axis(labelFontSize=11, titleFontSize=12)
    )


def _macro_input_yoy_chart(
    plot_df: pd.DataFrame,
    legend_order: list[str],
    *,
    width: int | str = "container",
    height: int = _MACRO_INPUT_CHART_HEIGHT,
) -> alt.Chart | None:
    """Spend-equiv **USD levels** (left y) + **PeerSSSIndex** ppt (right y)."""
    if plot_df.empty or alt is None:
        return None
    # Horizontal year ticks + padding — default VL sizing clips x labels/title in Streamlit.
    x_axis_bottom = alt.Axis(
        format="%Y",
        labelAngle=0,
        tickCount=_MACRO_YOY_CHART_YEARS + 2,
        titlePadding=10,
        labelPadding=6,
    )
    plot_df = plot_df.copy()
    plot_df["month_end"] = _naive_month_end_series(plot_df["month_end"])
    plot_df = plot_df.dropna(subset=["month_end", "series", "value"])
    plot_df = plot_df.drop_duplicates(subset=["month_end", "series"], keep="last")
    plot_df = plot_df.sort_values(["series", "month_end"], kind="mergesort").reset_index(drop=True)

    usd_df = plot_df[plot_df["series"] != _MACRO_PEER_SSS_CHART_LABEL].copy()
    peer_df = plot_df[plot_df["series"] == _MACRO_PEER_SSS_CHART_LABEL].copy()
    if usd_df.empty and peer_df.empty:
        return None

    leg_cols = max(len(legend_order), 1)
    leg = alt.Legend(
        orient="top",
        direction="horizontal",
        columns=leg_cols,
        title=None,
        labelLimit=0,
        labelFontSize=11,
        symbolSize=56,
        symbolStrokeWidth=2,
        padding=4,
        labelPadding=2,
        legendX=6,
        legendY=-6,
    )
    hex_by = macro_yoy_series_label_to_hex(legend_order)
    color_domain = list(legend_order)
    color_range = [hex_by[lab] for lab in color_domain]
    color_scale = alt.Scale(domain=color_domain, range=color_range)

    layers: list[Any] = []

    if not usd_df.empty:
        uval = pd.to_numeric(usd_df["value"], errors="coerce").dropna()
        if not uval.empty:
            uy_min, uy_max = float(uval.min()), float(uval.max())
            pad = max((uy_max - uy_min) * 0.06, 30.0)
            uy_lo = max(0.0, uy_min - pad)
            uy_hi = uy_max + pad
        else:
            uy_lo, uy_hi = 0.0, 1200.0

        lines_usd = (
            alt.Chart(usd_df)
            .mark_line(strokeWidth=2.25)
            .encode(
                x=alt.X("month_end:T", title="Month-end", axis=x_axis_bottom),
                y=alt.Y(
                    "value:Q",
                    title="Spend-equiv (USD)",
                    axis=alt.Axis(format="~s"),
                    scale=alt.Scale(domain=[uy_lo, uy_hi]),
                ),
                color=alt.Color("series:N", sort=legend_order, legend=leg, scale=color_scale),
                order=alt.Order("month_end:T"),
                tooltip=[
                    alt.Tooltip("month_end:T", title="Month", format="%Y-%m-%d"),
                    alt.Tooltip("series:N", title="What"),
                    alt.Tooltip("value:Q", title="USD", format=",.0f"),
                ],
            )
        )
        layers.append(lines_usd)

    if not peer_df.empty:
        peer_plot = peer_df.copy()
        # Separate field name from USD ``value`` — layered ``y: value`` + ``resolve_scale(y='independent')``
        # can otherwise bind both series to one scale and crush ppt into the bottom of the USD range.
        peer_plot["peer_ppt"] = pd.to_numeric(peer_plot["value"], errors="coerce")
        pv = peer_plot["peer_ppt"].dropna()
        if not pv.empty:
            py_min, py_max = float(pv.min()), float(pv.max())
            pad = max((py_max - py_min) * 0.06, 0.75)
            py_lo = min(0.0, py_min - pad)
            py_hi = py_max + pad
        else:
            py_lo, py_hi = -20.0, 60.0

        peer_stroke = hex_by.get(_MACRO_PEER_SSS_CHART_LABEL, _MACRO_PEER_LINE_COLOR)
        lines_peer = (
            alt.Chart(peer_plot)
            .mark_line(strokeWidth=2.25, stroke=peer_stroke, strokeDash=[5, 3])
            .encode(
                x=alt.X("month_end:T", title="Month-end", axis=x_axis_bottom),
                y=alt.Y(
                    "peer_ppt:Q",
                    title="Peer SSS (ppt)",
                    axis=alt.Axis(orient="right", format=".0f"),
                    scale=alt.Scale(domain=[py_lo, py_hi]),
                ),
                order=alt.Order("month_end:T"),
                tooltip=[
                    alt.Tooltip("month_end:T", title="Month", format="%Y-%m-%d"),
                    alt.Tooltip("series:N", title="What"),
                    alt.Tooltip("peer_ppt:Q", title="ppt", format=".2f"),
                ],
            )
        )
        layers.append(lines_peer)

    if not layers:
        return None
    return (
        alt.layer(*layers)
        .resolve_scale(x="shared", y="independent")
        .resolve_axis(x="shared")
        .properties(
            width=width,
            height=height,
            # Avoid ``autosize: {type: 'fit', contains: 'padding'}`` here — it can strip bottom x labels on layered dual-y charts in ``st.altair_chart``.
            padding={"bottom": 52, "left": 2, "right": 8},
        )
        .configure_view(strokeWidth=0, clip=False)
        .configure_axis(labelFontSize=11, titleFontSize=12)
    )


def _prepare_consumer_resilience_long(
    monthly: pd.DataFrame,
    metric_name: str,
) -> tuple[pd.DataFrame, list[str], str, str] | None:
    """Return monthly long data for the selected consumer-resilience metric, filtered to 2022+."""
    meta = _CONSUMER_METRIC_OPTIONS.get(metric_name)
    if monthly.empty or not meta:
        return None
    work = monthly.copy()
    if isinstance(work.index, pd.DatetimeIndex):
        work = work.reset_index()
    if "month_end" not in work.columns:
        return None
    work["month_end"] = _naive_month_end_series(work["month_end"])
    work = (
        work.dropna(subset=["month_end"])
        .drop_duplicates(subset=["month_end"], keep="last")
        .sort_values("month_end", kind="mergesort")
        .reset_index(drop=True)
    )
    work = work.loc[work["month_end"] >= _CONSUMER_CHART_START].copy()
    rows: list[dict[str, Any]] = []
    order: list[str] = []
    for label, col in meta["series"]:
        order.append(label)
        if col not in work.columns:
            continue
        raw = pd.to_numeric(work[col], errors="coerce")
        vals = raw
        if col in _CONSUMER_3MMA_COLUMNS:
            min_p = _CONSUMER_3MMA_MIN_PERIODS.get(col, 1)
            vals = raw.rolling(window=3, min_periods=min_p).mean()
            if col in _CONSUMER_3MMA_REQUIRE_RAW_MONTH:
                vals = vals.where(raw.notna())
        for me, value in zip(work["month_end"], vals):
            if pd.notna(value):
                rows.append({"month_end": me, "series": label, "value": float(value)})
    if not rows:
        return None
    out = pd.DataFrame(rows)
    out = out.drop_duplicates(subset=["month_end", "series"], keep="last")
    out = out.sort_values(["series", "month_end"], kind="mergesort").reset_index(drop=True)
    present = list(dict.fromkeys(out["series"].astype(str).tolist()))
    order = [label for label in order if label in present]
    return out, order, str(meta["y_title"]), str(meta["value_format"])


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_prepare_consumer_resilience_long(
    monthly_rev: str,
    metric_name: str,
    monthly: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], str, str] | None:
    del monthly_rev
    return _prepare_consumer_resilience_long(monthly, metric_name)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_prepare_macro_input_yoy_long(
    monthly_rev: str,
    years: int,
    monthly: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]] | None:
    del monthly_rev
    return _prepare_macro_input_yoy_long(monthly, years=years)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_prepare_peer_indices_long(
    monthly_rev: str,
    wide_rev: str,
    fd_rev: str,
    years: int,
    monthly: pd.DataFrame,
    brand_period_wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]] | None:
    del monthly_rev, wide_rev, fd_rev
    return _prepare_peer_indices_long(
        monthly, brand_period_wide, fiscal_dates, years=years
    )


@st.fragment
def _consumer_resilience_metric_panel(side: str, macro_monthly: pd.DataFrame, *, default_metric: str) -> None:
    """Rerun only this column when the consumer-metric dropdown changes."""
    consumer_options = list(_CONSUMER_METRIC_OPTIONS)
    monthly_rev = dataframe_revision(macro_monthly)
    default_idx = (
        consumer_options.index(default_metric) if default_metric in consumer_options else 0
    )
    picked = st.selectbox(
        f"{side.title()} consumer metric",
        options=consumer_options,
        index=default_idx,
        key=f"fc_consumer_{side}_metric_select",
        label_visibility="collapsed",
    )
    prepared = _cached_prepare_consumer_resilience_long(monthly_rev, picked, macro_monthly)
    if prepared is None:
        st.caption(f"No data available for **{picked}**.")
        return
    cons_df, cons_order, cons_y, cons_fmt = prepared
    ch = _consumer_resilience_chart(cons_df, cons_order, y_title=cons_y, value_format=cons_fmt)
    if ch is not None:
        st.altair_chart(ch, use_container_width=True)
        st.markdown(
            f"""
<div class="fc-under-chart">
<p class="fc-src">{_CONSUMER_METRIC_SOURCES.get(picked, "FRED")}</p>
<p class="fc-cap">{_CONSUMER_METRIC_CAPTIONS.get(picked, "")}</p>
</div>
""",
            unsafe_allow_html=True,
        )


def _consumer_resilience_chart(
    plot_df: pd.DataFrame,
    legend_order: list[str],
    *,
    y_title: str,
    value_format: str,
    width: int | str = "container",
    height: int = _CONSUMER_CHART_HEIGHT,
) -> alt.Chart | None:
    """Line chart for consumer-resilience measures."""
    if plot_df.empty or alt is None:
        return None
    plot_df = plot_df.copy()
    plot_df["month_end"] = _naive_month_end_series(plot_df["month_end"])
    plot_df["value"] = pd.to_numeric(plot_df["value"], errors="coerce")
    plot_df = plot_df.dropna(subset=["month_end", "series", "value"])
    if plot_df.empty:
        return None
    y_vals = plot_df["value"].dropna()
    y_min, y_max = float(y_vals.min()), float(y_vals.max())
    pad = max((y_max - y_min) * 0.08, 0.5)
    y_lo = min(0.0, y_min - pad) if "YoY" in y_title else y_min - pad
    y_hi = y_max + pad
    color_range = [_consumer_series_color(label) for label in legend_order]
    leg = alt.Legend(
        orient="top",
        direction="horizontal",
        columns=max(len(legend_order), 1),
        title=None,
        labelLimit=0,
        labelFontSize=11,
        symbolSize=56,
        symbolStrokeWidth=2,
        padding=4,
        labelPadding=2,
        legendX=6,
        legendY=-6,
    )
    lines = (
        alt.Chart(plot_df)
        .mark_line(strokeWidth=2.25)
        .encode(
            x=alt.X(
                "month_end:T",
                title="Month-end",
                axis=alt.Axis(format="%Y", labelAngle=0, tickCount=6),
            ),
            y=alt.Y("value:Q", title=y_title, scale=alt.Scale(domain=[y_lo, y_hi])),
            color=alt.Color(
                "series:N",
                sort=legend_order,
                legend=leg,
                scale=alt.Scale(domain=legend_order, range=color_range),
            ),
            order=alt.Order("month_end:T"),
            strokeDash=alt.condition(
                alt.FieldEqualPredicate(field="series", equal="Headline CPI"),
                alt.value([3, 3]),
                alt.value([1, 0]),
            ),
            tooltip=[
                alt.Tooltip("month_end:T", title="Month", format="%Y-%m-%d"),
                alt.Tooltip("series:N", title="What"),
                alt.Tooltip("value:Q", title=y_title, format=value_format),
            ],
        )
    )
    layers: list[Any] = [lines]
    if "YoY" in y_title:
        layers.append(alt.Chart().mark_rule(color="#0a0a0a", strokeWidth=2.0, opacity=0.5).encode(y=alt.datum(0)))
    return (
        alt.layer(*layers)
        .properties(width=width, height=height, padding={"bottom": 44, "left": 2, "right": 6})
        .configure_view(strokeWidth=0, clip=False)
        .configure_axis(labelFontSize=11, titleFontSize=12)
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _gdelt_csv_uri() -> str | None:
    v = os.environ.get("MLP_GDELT_CSV")
    if isinstance(v, str) and v.strip():
        return v.strip()
    try:
        if hasattr(st, "secrets") and "MLP_GDELT_CSV" in st.secrets:
            s = st.secrets["MLP_GDELT_CSV"]
            if s is not None and str(s).strip():
                return str(s).strip()
    except Exception:
        pass
    return None


def _read_csv_from_gcs_quiet(gs_uri: str) -> pd.DataFrame:
    try:
        from google.cloud import storage
        from google.oauth2.service_account import Credentials
    except ImportError:
        return pd.DataFrame()
    try:
        p = urlparse(str(gs_uri).strip())
        if p.scheme != "gs" or not p.netloc:
            return pd.DataFrame()
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
            "GOOGLE_SHEETS_CREDENTIALS"
        )
        if cred_path and Path(cred_path).is_file():
            creds = Credentials.from_service_account_file(
                str(cred_path), scopes=("https://www.googleapis.com/auth/devstorage.read_only",)
            )
            client = storage.Client(credentials=creds, project=creds.project_id)
        else:
            client = storage.Client()
        blob = client.bucket(p.netloc).blob(p.path.lstrip("/"))
        if not blob.exists():
            return pd.DataFrame()
        return pd.read_csv(io.BytesIO(blob.download_as_bytes()))
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _load_gdelt_monthly_wide() -> pd.DataFrame:
    """Load GDELT brand monthly wide CSV from env/secrets, GCS, or repo root."""
    uri = _gdelt_csv_uri()
    if uri:
        if uri.startswith("gs://"):
            df = _read_csv_from_gcs_quiet(uri)
        else:
            p = Path(uri).expanduser()
            df = pd.read_csv(p) if p.is_file() else pd.DataFrame()
        if not df.empty:
            return df
    p = _repo_root() / "gdelt_fast_casual_monthly.csv"
    if p.is_file():
        return pd.read_csv(p)
    return pd.DataFrame()


def _prepare_gdelt_attention_long() -> tuple[pd.DataFrame, list[str]] | None:
    """GDELT article-share YoY by ticker, using precomputed preprocessing columns."""
    df = _load_gdelt_monthly_wide()
    if df.empty or "month" not in df.columns:
        return None
    work = df.copy()
    work["month_end"] = (
        pd.to_datetime(work["month"], format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
    ).dt.normalize()
    work = work.loc[work["month_end"] >= _ATTENTION_CHART_START].copy()
    rows: list[dict[str, Any]] = []
    order: list[str] = []
    for ticker in _ATTENTION_TICKER_ORDER:
        col = f"{ticker.lower()}_gdelt_article_share_per_100k_yoy_pct"
        if col not in work.columns:
            continue
        label = _ATTENTION_TICKER_LABELS.get(ticker, ticker)
        order.append(label)
        vals = pd.to_numeric(work[col], errors="coerce").rolling(window=3, min_periods=1).mean()
        for me, value in zip(work["month_end"], vals):
            if pd.notna(me) and pd.notna(value):
                rows.append({"month_end": me, "series": label, "value": float(value), "ticker": ticker})
    if not rows:
        return None
    out = pd.DataFrame(rows).sort_values(["series", "month_end"], kind="mergesort")
    present = list(dict.fromkeys(out["series"].astype(str).tolist()))
    order = [label for label in order if label in present]
    return out.reset_index(drop=True), order


def _prepare_gtrends_attention_long() -> tuple[pd.DataFrame, list[str]] | None:
    """Google Trends brand YoY by ticker. Only columns present in the current Trends CSV are plotted."""
    df = load_gtrends_monthly_csv()
    if df.empty or "month" not in df.columns:
        return None
    work = df.copy()
    work["month_end"] = (
        pd.to_datetime(work["month"], format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
    ).dt.normalize()
    work = work.loc[work["month_end"] >= _ATTENTION_CHART_START].copy()
    rows: list[dict[str, Any]] = []
    order: list[str] = []
    for ticker in _ATTENTION_TICKER_ORDER:
        col = _GTRENDS_BRAND_YOY_SPECS.get(ticker)
        if not col or col not in work.columns:
            continue
        label = _ATTENTION_TICKER_LABELS.get(ticker, ticker)
        order.append(label)
        vals = pd.to_numeric(work[col], errors="coerce").rolling(window=3, min_periods=1).mean()
        for me, value in zip(work["month_end"], vals):
            if pd.notna(me) and pd.notna(value):
                rows.append({"month_end": me, "series": label, "value": float(value), "ticker": ticker})
    if not rows:
        return None
    out = pd.DataFrame(rows).sort_values(["series", "month_end"], kind="mergesort")
    present = list(dict.fromkeys(out["series"].astype(str).tolist()))
    order = [label for label in order if label in present]
    return out.reset_index(drop=True), order


def _attention_color(label: str) -> str:
    for ticker, lab in _ATTENTION_TICKER_LABELS.items():
        if lab == label:
            return _ATTENTION_TICKER_COLORS.get(ticker, "#4e79a7")
    return "#4e79a7"


def _brand_attention_chart(
    plot_df: pd.DataFrame,
    legend_order: list[str],
    *,
    y_title: str,
    width: int | str = "container",
    height: int = _ATTENTION_CHART_HEIGHT,
) -> alt.Chart | None:
    if plot_df.empty or alt is None:
        return None
    work = plot_df.copy()
    work["month_end"] = _naive_month_end_series(work["month_end"])
    work["value"] = pd.to_numeric(work["value"], errors="coerce")
    work = work.dropna(subset=["month_end", "series", "value"])
    if work.empty:
        return None
    y_vals = work["value"].dropna()
    y_min, y_max = float(y_vals.min()), float(y_vals.max())
    pad = max((y_max - y_min) * 0.08, 2.0)
    y_lo = min(0.0, y_min - pad)
    y_hi = y_max + pad
    leg = alt.Legend(
        orient="top",
        direction="horizontal",
        columns=max(len(legend_order), 1),
        title=None,
        labelLimit=0,
        labelFontSize=11,
        symbolSize=56,
        symbolStrokeWidth=2,
        padding=4,
        labelPadding=2,
        legendX=6,
        legendY=-6,
    )
    lines = (
        alt.Chart(work)
        .mark_line(strokeWidth=2.15)
        .encode(
            x=alt.X(
                "month_end:T",
                title="Month-end",
                axis=alt.Axis(format="%Y", labelAngle=0, tickCount=4),
            ),
            y=alt.Y("value:Q", title=y_title, scale=alt.Scale(domain=[y_lo, y_hi])),
            color=alt.Color(
                "series:N",
                sort=legend_order,
                legend=leg,
                scale=alt.Scale(
                    domain=legend_order,
                    range=[_attention_color(label) for label in legend_order],
                ),
            ),
            order=alt.Order("month_end:T"),
            tooltip=[
                alt.Tooltip("month_end:T", title="Month", format="%Y-%m-%d"),
                alt.Tooltip("series:N", title="Ticker"),
                alt.Tooltip("value:Q", title=y_title, format=".1f"),
            ],
        )
    )
    zero = alt.Chart().mark_rule(color="#0a0a0a", strokeWidth=2.0, opacity=0.45).encode(y=alt.datum(0))
    return (
        alt.layer(lines, zero)
        .properties(width=width, height=height, padding={"bottom": 44, "left": 2, "right": 6})
        .configure_view(strokeWidth=0, clip=False)
        .configure_axis(labelFontSize=11, titleFontSize=12)
    )


def _pick_cell(grid: pd.DataFrame, prd: object, col: str) -> float:
    if grid.empty or col not in grid.columns or prd not in grid.index:
        return float("nan")
    v = grid.loc[prd, col]
    return float(v) if pd.notna(v) else float("nan")


def _long_sss_traffic_ticket(dfs: dict[str, Any]) -> pd.DataFrame:
    """One row per fiscal quarter × ticker with ``sss`` / ``traffic`` / ``ticket`` (percent points)."""
    g_sss = _build_quarterly_peer_grid(dfs, common_name="sss")
    if g_sss.empty:
        return pd.DataFrame()
    g_tr = _build_quarterly_peer_grid(dfs, common_name="traffic")
    g_ti = _build_quarterly_peer_grid(dfs, common_name="ticket")
    rows: list[dict[str, Any]] = []
    for prd in g_sss.index:
        prd_s = str(prd).strip()
        for t in _DISPLAY_TICKERS:
            rows.append(
                {
                    "prd_nm": prd_s,
                    "Quarter": prd_s,
                    "ticker": t,
                    "sss": _pick_cell(g_sss, prd, t),
                    "traffic": _pick_cell(g_tr, prd, t) if not g_tr.empty else float("nan"),
                    "ticket": _pick_cell(g_ti, prd, t) if not g_ti.empty else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def _peer_bar_with_dots(long_df: pd.DataFrame, grid_sss: pd.DataFrame, *, x_order: list[str]) -> alt.Chart:
    peer_df = (
        grid_sss.reset_index()
        .rename(columns={"Prd_Nm": "Quarter"})
        .assign(Quarter=lambda d: d["Quarter"].astype(str).str.strip())
    )
    pts = long_df.dropna(subset=["sss"]).copy()
    # Legend click toggles ticker visibility (Vega-Lite legend binding — bars unchanged).
    ticker_pick = alt.selection_point(fields=["ticker"], bind="legend", empty="all")
    bars = (
        alt.Chart(peer_df)
        .mark_bar(color="#4a6fa5", opacity=0.85)
        .encode(
            x=alt.X("Quarter:N", title="Fiscal quarter", sort=x_order),
            y=alt.Y("PeerIndex:Q", title="SSS (%, peer mean)"),
            tooltip=[
                alt.Tooltip("Quarter:N", title="Period"),
                alt.Tooltip("PeerIndex:Q", title="Peer SSS index", format=".2f"),
            ],
        )
    )
    dots = (
        alt.Chart(pts)
        .mark_point(filled=True, size=90, stroke="#1a1816", strokeWidth=0.5)
        .encode(
            x=alt.X("Quarter:N", sort=x_order),
            y=alt.Y("sss:Q", title="SSS (%, peer mean)"),
            color=alt.Color("ticker:N", title="Ticker", sort=list(_DISPLAY_TICKERS)),
            opacity=alt.condition(ticker_pick, alt.value(1.0), alt.value(0.0)),
            tooltip=[
                alt.Tooltip("prd_nm:N", title="Period"),
                alt.Tooltip("ticker:N", title="Ticker"),
                alt.Tooltip("sss:Q", title="SSS (%)", format=".2f"),
                alt.Tooltip("traffic:Q", title="Traffic (%)", format=".2f"),
                alt.Tooltip("ticket:Q", title="Ticket (%)", format=".2f"),
            ],
        )
        .add_params(ticker_pick)
    )
    return (
        alt.layer(bars, dots)
        .resolve_scale(color="independent")
        .properties(height=_PEER_SSS_VIEW_HEIGHT, title="Equal-weighted Peer SSS index vs tickers (dots = ticker SSS)")
        # Tighter plot chrome so captions can sit closer to the x-axis title.
        .configure_view(strokeWidth=0)
        .configure_axisX(titlePadding=4, labelPadding=4)
    )


def main() -> None:
    # Pull narrative subhead up under the page title: theme uses h1 margin-bottom + h2 margin-top (large gap).
    st.markdown(
        """
<style>
div[data-testid="stMarkdownContainer"] h1:has(+ h2) {
  margin-bottom: 0.35rem !important;
  padding-bottom: 0.35rem !important;
}
div[data-testid="stMarkdownContainer"] h1 + h2 {
  margin-top: 0.25rem !important;
}
</style>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        """# Macro & industry

## Fast Casual Fatigue Has Set In
""",
    )
    st.markdown(
        """
Fast casual SSS has moved from reopening / inflation-aided growth into straight up fatigue. The fast casual SSS
average was **-1.6%** in **2026Q1**, the weakest point in the available dashboard history (since **2021Q1**) and
the **8th** straight quarter of deterioration. While traffic had held up through price increases in **2023** and
**2024**, it softened in **2025**.

The group's stocks have followed down—the group, on average, is down **44.3%** since the start of **2025**. The
move has been uniform: all are down, and the only name down less than **30%** is sugar drink dealer **BROS**. In fact,
according to [stockthemes.ai](https://stockthemes.ai)—a trusted source that tracks over **1,900** unique, vetted
themes—the **Fast Casual Restaurants** group, which includes the six companies in this dashboard, is in the top
**5%** of worst-performing themes since the start of **2025**.

At the same time, the U.S. consumer has remained resilient and active. With easier **2025** comparisons ahead,
the back half of the year could create opportunities for brands that can defend traffic without giving back too
much on price.
"""
    )

    if alt is None:
        st.error("Altair is required for this page. Install with `pip install altair`.")
        st.stop()

    bundle = get_dashboard_bundle_or_stop(include_feature_tables=False)
    dfs = bundle["mlp_sheets"]
    brand_wide = bundle.get("brand_period_wide")
    if not isinstance(brand_wide, pd.DataFrame):
        brand_wide = pd.DataFrame()
    fd = dfs.get("fiscal_dates")
    if not isinstance(fd, pd.DataFrame):
        fd = pd.DataFrame()
    macro_monthly = bundle.get("macro", {}).get("monthly")
    if macro_monthly is None or not isinstance(macro_monthly, pd.DataFrame):
        macro_monthly = pd.DataFrame()

    grid_sss = _build_quarterly_peer_grid(dfs, common_name="sss")
    if grid_sss.empty:
        st.warning("No **sss** (SSS) rows for the peer tickers. Check **MetricNames** / **HistoricalValues**.")
        st.stop()

    long_df = _long_sss_traffic_ticket(dfs)
    x_order = sorted(long_df["Quarter"].astype(str).unique(), key=_prd_sort_key)

    grid_view = _reorder_index_default_start(grid_sss, start_prd=_DEFAULT_TABLE_START)
    show = grid_view.reset_index().rename(columns={"Prd_Nm": "Quarter"})
    display_df = _format_percent_table(show)
    col_cfg: dict[str, Any] = {"Quarter": st.column_config.TextColumn("Quarter")}
    for t in _DISPLAY_TICKERS:
        if t in display_df.columns:
            col_cfg[t] = st.column_config.TextColumn(t)
    col_cfg["PeerIndex"] = st.column_config.TextColumn("PeerIndex")
    st.session_state.setdefault("fc_peer_sss_view_toggle", "Chart")
    if hasattr(st, "segmented_control"):
        peer_view = st.segmented_control(
            "Peer SSS view",
            options=("Chart", "Table"),
            key="fc_peer_sss_view_toggle",
            label_visibility="collapsed",
        )
    else:
        peer_view = st.select_slider(
            "Peer SSS view",
            options=("Chart", "Table"),
            key="fc_peer_sss_view_toggle",
            label_visibility="collapsed",
        )
    if peer_view == "Table":
        st.markdown(
            """
<div style="font-family: sans-serif; font-size: 18px; font-weight: 700; line-height: 1.2; margin: 0 0 0.4rem 0; padding: 0;">
SSS Growth by Ticker
</div>
""",
            unsafe_allow_html=True,
        )
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=_PEER_SSS_VIEW_HEIGHT,
            column_config=col_cfg,
        )
        peer_caption_extra_class = " fc-under-chart-table"
    else:
        st.altair_chart(_peer_bar_with_dots(long_df, grid_sss, x_order=x_order), use_container_width=True)
        peer_caption_extra_class = ""
    st.markdown(
        f"""
<style>
.fc-under-chart {{ margin-top: -2.1rem !important; margin-bottom: 0.35rem !important; }}
.fc-under-chart.fc-under-chart-table {{ margin-top: 0.35rem !important; }}
.fc-under-chart p {{ padding: 0 !important; }}
.fc-under-chart .fc-src {{
  font-size: 0.5rem !important;
  font-style: italic !important;
  color: #6b6357 !important;
  line-height: 1.2 !important;
  margin: 0 0 0.1rem 0 !important;
}}
.fc-under-chart .fc-cap {{
  font-size: 0.82rem !important;
  color: #5c5449 !important;
  margin: 0 !important;
  line-height: 1.35 !important;
}}
</style>
<div class="fc-under-chart{peer_caption_extra_class}">
<p class="fc-src">Company Filings</p>
<p class="fc-cap">Growth has deteriorated over the last several quarters.</p>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<style>
.fc-macro-impact-heading {
  margin-bottom: 0.25rem !important;
}
.fc-macro-impact-subheading {
  margin-top: 0 !important;
}
</style>
<h2 class="fc-macro-impact-heading">What Macroeconomic Factors Have Impacted Fast Casual Sales?</h2>
<h3 class="fc-macro-impact-subheading">Pricing has been the dominant macroeconomic factor...</h3>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
Post-COVID fast casual sales were supported by a strong consumer and unusually large pricing power. That pricing
was also a response to real cost pressure: labor, proteins, rent, and broad CPI all reset higher versus the
pre-pandemic baseline. In **2023** and **2024**, price increases helped offset softer traffic and kept SSS positive
for much of the group. By **2025**, however, the benefit started to fade as traffic softened and consumers became
more selective, leaving brands with less room to push price without hurting demand.
"""
    )

    st.markdown(
        '<div class="fc-macro-chart-spacer" style="height:1.35rem;" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    monthly_rev = dataframe_revision(macro_monthly)
    wide_rev = dataframe_revision(brand_wide)
    fd_rev = dataframe_revision(fd)

    col_macro_yoy, col_macro_right = st.columns(2, gap="medium")
    with col_macro_yoy:
        prepared = _cached_prepare_macro_input_yoy_long(
            monthly_rev, _MACRO_YOY_CHART_YEARS, macro_monthly
        )
        if prepared is not None:
            long_df, legend_order = prepared
            long_df, legend_order = _append_peer_indexes_to_macro_long(
                long_df, legend_order, brand_wide, fd
            )
            st.markdown(
                f"""
<style>
.fc-macro-yoy-chart-title {{
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 0.4rem 0;
  padding: 0;
  line-height: 1.25;
}}
</style>
<div class="fc-macro-yoy-chart-title">{_MACRO_INPUT_YOY_CHART_TITLE}</div>
""",
                unsafe_allow_html=True,
            )
            ch = _macro_input_yoy_chart(long_df, legend_order)
            if ch is not None:
                st.altair_chart(ch, use_container_width=True)
                st.markdown(
                    """
<div class="fc-under-chart">
<p class="fc-src">NASS USDA, BLS API</p>
<p class="fc-cap">Input prices have jumped drastically since 2019.</p>
</div>
""",
                    unsafe_allow_html=True,
                )
        elif macro_monthly.empty:
            st.caption("Macro monthly frame is empty — check data load / GCS snapshot.")
        else:
            st.caption(
                "No spend-equiv series to plot — macro monthly needs ``equiv_usd_1000_at_<year>avg_*`` **level** "
                "columns (from ``macro_data`` spend-equiv). Re-run `load_mlp_master.py` / refresh the bundle; "
                "or clear Streamlit cache if macro is updated on disk."
            )
    with col_macro_right:
        st.markdown(
            f"""
<style>
.fc-macro-yoy-chart-title {{
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 0.4rem 0;
  padding: 0;
  line-height: 1.25;
}}
</style>
<div class="fc-macro-yoy-chart-title">{_PEER_INDICES_CHART_TITLE}</div>
""",
            unsafe_allow_html=True,
        )
        prep_pi = _cached_prepare_peer_indices_long(
            monthly_rev,
            wide_rev,
            fd_rev,
            _MACRO_YOY_CHART_YEARS,
            macro_monthly,
            brand_wide,
            fd,
        )
        if prep_pi is None:
            st.caption(
                "No peer index series — ``brand_period_wide`` needs **PeerSSSIndex** / **PeerPricingIndex** / "
                "**PeerTrafficIndex** (from `sheets_client.build_mlp_brand_period_wide_df`) plus **FiscalDates** "
                "join keys for calendar quarter-end alignment (re-run master load)."
            )
        else:
            long_pi, leg_pi = prep_pi
            ch_r = _peer_indices_chart(long_pi, leg_pi)
            if ch_r is not None:
                st.altair_chart(ch_r, use_container_width=True)
                st.markdown(
                    """
<div class="fc-under-chart">
<p class="fc-src">Workbook peers (wide panel)</p>
<p class="fc-cap">Pricing increases had held up until 2025.</p>
</div>
""",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("Peer index data could not be charted (all values missing after filter).")

    st.markdown(
        """
### ...But by most metrics the U.S. consumer remains resilient and active
"""
    )
    st.markdown(
        """
Restaurant sales, worker pay, employment, and urban activity are still generally supportive. Nominal restaurant
sales growth has slowed from the reopening surge, but it remains positive, and the real restaurant demand spread
is still a useful check that away-from-home spending has not collapsed after adjusting for food-away-from-home
inflation. Worker pay is also still growing faster than headline CPI, giving consumers some offset to higher menu
prices. Unemployment has ticked up, but remains below recessionary levels, while commuter activity in New York and
San Francisco continues to recover from the post-COVID trough. The consumer is mostly strong and the data
does not point to a broader pullback in away-from-home spending. So, there could be an opportunity for fast casual brands that are able to earn positive attention. 
"""
    )
    col_consumer_left, col_consumer_right = st.columns(2, gap="medium")
    with col_consumer_left:
        _consumer_resilience_metric_panel(
            "left", macro_monthly, default_metric="Restaurant Sales Growth"
        )
    with col_consumer_right:
        _consumer_resilience_metric_panel(
            "right", macro_monthly, default_metric="OpenTable Seated Diners"
        )

    st.markdown(
        """
No single one of these indicators can reasonably forecast fast casual SSS on its own. Taken together, however,
they paint a clearer picture: the consumer is still out, active, employed, and has money to spend. The issue for
fast casual is therefore less about a consumer that has disappeared and more about brands needing to reattract
visits in a more selective environment, especially after several years of price-led growth.

### Fast casual brands that capture consumer attention should see opportunity

To frame which brands are still earning consumer attention, 
I compared GDELT media attention and Google Trends search interest across the six fast casual names.
Though very noisy, these datasets can provide a view into which brands are earning consumer attention.
Paid data is much more helpful, but these free sources are a useful check.
"""
    )

    col_attention_left, col_attention_right = st.columns(2, gap="medium")
    with col_attention_left:
        st.markdown(
            """
<style>
.fc-attention-chart-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--wb-text);
  margin: 0 0 0.2rem 0;
  line-height: 1.25;
}
</style>
<div class="fc-attention-chart-title">GDELT media attention by brand (3MMA YoY)</div>
""",
            unsafe_allow_html=True,
        )
        gdelt_prepared = _prepare_gdelt_attention_long()
        if gdelt_prepared is None:
            st.caption("No GDELT brand-buzz data available. Re-run `gdelt_monthly_brands.py`.")
        else:
            gdelt_df, gdelt_order = gdelt_prepared
            gdelt_chart = _brand_attention_chart(
                gdelt_df,
                gdelt_order,
                y_title="Article share YoY (%)",
            )
            if gdelt_chart is not None:
                st.altair_chart(gdelt_chart, use_container_width=True)
                st.markdown(
                    """
<div class="fc-under-chart">
<p class="fc-src">GDELT DOC 2.0</p>
<p class="fc-cap">Media attention is normalized by total GDELT article volume.</p>
</div>
""",
                    unsafe_allow_html=True,
                )
    with col_attention_right:
        st.markdown(
            """
<div class="fc-attention-chart-title">Google Trends brand interest (3MMA YoY)</div>
""",
            unsafe_allow_html=True,
        )
        gtrends_prepared = _prepare_gtrends_attention_long()
        if gtrends_prepared is None:
            st.caption("No Google Trends brand data available. Re-run `gtrends_monthly_brands.py`.")
        else:
            gt_df, gt_order = gtrends_prepared
            gt_chart = _brand_attention_chart(
                gt_df,
                gt_order,
                y_title="Search interest YoY (%)",
            )
            if gt_chart is not None:
                st.altair_chart(gt_chart, use_container_width=True)
                missing = [
                    _ATTENTION_TICKER_LABELS[t]
                    for t in _ATTENTION_TICKER_ORDER
                    if t not in _GTRENDS_BRAND_YOY_SPECS
                ]
                note = (
                    "Current Trends pull excludes " + ", ".join(missing) + "."
                    if missing
                    else "Search interest uses brand-term YoY fields."
                )
                st.markdown(
                    f"""
<div class="fc-under-chart">
<p class="fc-src">Google Trends</p>
<p class="fc-cap">{note}</p>
</div>
""",
                    unsafe_allow_html=True,
                )

    st.markdown(
        """
The clearest takeaway is that **CAVA** is the positive outlier. **CAVA** has held the strongest and most persistent search-interest / media attention
growth in the current brand set, while the other available brands look more muted. This suggests the brand is still earning incremental
consumer mindshare.
"""
    )

main()
