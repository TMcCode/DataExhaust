"""Industry backdrop — macro + demand context. Draft charts section is disposable."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

try:
    import altair as alt
except ImportError:  # pragma: no cover — Streamlit normally installs altair
    alt = None  # type: ignore[misc, assignment]

import macro_data
import sheets_client
from streamlit_dashboard.data_loader import get_dashboard_bundle_or_stop
from streamlit_dashboard.peer_gtrends_utils import (
    line_chart_with_peer,
    merge_peer_on_monthly,
    monthly_macro_with_index,
    peer_sss_by_month_end,
    quarter_label_sort_key,
    render_peer_vs_macro_stats,
)


def _filter_recent(df: pd.DataFrame, years: int) -> pd.DataFrame:
    if df.empty or "month_end" not in df.columns:
        return df
    end = pd.to_datetime(df["month_end"], errors="coerce").max()
    if pd.isna(end):
        return df
    start = end - pd.DateOffset(years=years)
    return df[pd.to_datetime(df["month_end"], errors="coerce") >= start]


def _filter_recent_quarters(df: pd.DataFrame, years: int) -> pd.DataFrame:
    if df.empty or "quarter_end" not in df.columns:
        return df
    end = pd.to_datetime(df["quarter_end"], errors="coerce").max()
    if pd.isna(end):
        return df
    start = end - pd.DateOffset(years=int(years))
    return df[pd.to_datetime(df["quarter_end"], errors="coerce") >= start].copy()


def _peer_sss_by_calendar_quarter(feat_q: pd.DataFrame) -> pd.DataFrame:
    if feat_q.empty or "PeerSSSIndex" not in feat_q.columns or "macro_calendar_quarter_join" not in feat_q.columns:
        return pd.DataFrame(columns=["calendar_quarter", "PeerSSSIndex"])
    g = (
        feat_q.dropna(subset=["PeerSSSIndex", "macro_calendar_quarter_join"])
        .groupby("macro_calendar_quarter_join", as_index=False)["PeerSSSIndex"]
        .median()
    )
    g = g.rename(columns={"macro_calendar_quarter_join": "calendar_quarter"})
    g["calendar_quarter"] = g["calendar_quarter"].astype(str).str.strip()
    return g


def _merge_peer_on_quarterly(df: pd.DataFrame, peer_by_q: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "calendar_quarter" in out.columns:
        out["calendar_quarter"] = out["calendar_quarter"].astype(str).str.strip()
    if peer_by_q.empty:
        out["PeerSSSIndex"] = pd.NA
        return out
    return out.merge(peer_by_q, on="calendar_quarter", how="left")


# Census MRTS restaurant-related NSA levels (headline NAICS 722 + limited-service 7222).
_MRTS_CENSUS_COLS: tuple[str, ...] = (
    "retail_food_services_drinking_sales_millions_nsa",
    "retail_sales_limited_service_eating_places_naics7222_millions_nsa",
    "retail_food_services_drinking_sales_millions_nsa_yoy_pct",
    "retail_sales_limited_service_eating_places_naics7222_millions_nsa_yoy_pct",
)


def _any_numeric_in_cols(df: pd.DataFrame, cols: tuple[str, ...]) -> bool:
    present = [c for c in cols if c in df.columns]
    if not present:
        return False
    return bool(df[present].apply(pd.to_numeric, errors="coerce").notna().any().any())


def _last_non_null_month(df: pd.DataFrame, col: str) -> pd.Timestamp | None:
    if col not in df.columns or "month_end" not in df.columns:
        return None
    s = pd.to_numeric(df[col], errors="coerce")
    if not s.notna().any():
        return None
    return pd.Timestamp(df.loc[s.notna(), "month_end"].max())


def _expand_window_for_marts(full: pd.DataFrame, years: int) -> tuple[pd.DataFrame, int, str | None]:
    """Widen the slice from ``latest month`` until MRTS columns have at least one point (cap 25y)."""
    y0 = max(1, min(25, int(years)))
    m0 = _filter_recent(full, y0)
    if _any_numeric_in_cols(m0, _MRTS_CENSUS_COLS):
        return m0, y0, None
    bits: list[str] = []
    for c in _MRTS_CENSUS_COLS[:2]:
        if c in full.columns:
            t = _last_non_null_month(full, c)
            if t is not None:
                short = c.replace("retail_sales_", "").replace("_millions_nsa", "")
                bits.append(f"**{short}** last value **{t.date()}**")
    trail = "; ".join(bits) if bits else "No non-null MRTS values in the loaded macro frame."

    for y in range(y0 + 1, 26):
        m = _filter_recent(full, y)
        if _any_numeric_in_cols(m, _MRTS_CENSUS_COLS):
            return m, y, (
                f"Census MRTS restaurant columns had **no numeric rows** in the last **{y0}** year(s) from the latest "
                f"`month_end` (other series can still update). {trail} "
                f"Expanded the draft-tab window to **{y}** years so retail charts can render."
            )
    return _filter_recent(full, 25), 25, (
        f"Still no MRTS points after widening to **25** years. {trail} "
        "Re-pull macro (`load_mlp_master.py` / refresh the app cache) or verify FRED MRTSS series in `macro_data.py`."
    )


def _calendar_quarters_from_monthly_work(work: pd.DataFrame) -> set[str]:
    """Gregorian ``YYYYQk`` labels for every calendar quarter touched by ``month_end`` rows in ``work``."""
    if work.empty or "month_end" not in work.columns:
        return set()
    ts = pd.to_datetime(work["month_end"], errors="coerce").dropna()
    if ts.empty:
        return set()
    y = ts.dt.year.astype(str)
    q = ts.dt.quarter.astype(str)
    return set(y + "Q" + q)


def _feat_slice_calendar_quarter_sss(
    feat_q: pd.DataFrame,
    work: pd.DataFrame,
    *,
    macro_is_monthly: bool,
) -> pd.DataFrame:
    """Fiscal×macro **quarter** rows whose ``macro_calendar_quarter_join`` lies in the chart window.

    When macro charts are **monthly**, the window is still expressed as month-ends; we map those months
    to the set of **Gregorian calendar quarters** they touch so the SSS panel stays quarter-grain and
    the peer average is not mixing unrelated fiscal months in one bucket.
    """
    if feat_q.empty or "macro_calendar_quarter_join" not in feat_q.columns:
        return pd.DataFrame()
    if macro_is_monthly:
        cq_set = _calendar_quarters_from_monthly_work(work)
        if not cq_set:
            return pd.DataFrame()
        fs = feat_q.copy()
        fs["_cq"] = fs["macro_calendar_quarter_join"].astype(str).str.strip()
        return fs[fs["_cq"].isin(cq_set)].drop(columns=["_cq"], errors="ignore")
    return _feat_rows_in_work_window(feat_q, work, temporal=False)


def _feat_rows_in_work_window(
    feat: pd.DataFrame, work: pd.DataFrame, *, temporal: bool
) -> pd.DataFrame:
    """Rows from fiscal×macro join whose calendar join key falls in ``work``’s x-axis window."""
    if feat.empty or work.empty:
        return pd.DataFrame()
    if temporal:
        if "macro_month_end_join" not in feat.columns:
            return pd.DataFrame()
        keys = pd.to_datetime(work["month_end"], errors="coerce").dropna().dt.normalize()
        key_set = {pd.Timestamp(t).normalize() for t in keys}
        fs = feat.copy()
        fs["_k"] = pd.to_datetime(fs["macro_month_end_join"], errors="coerce").dt.normalize()
        return fs[fs["_k"].isin(key_set)].drop(columns=["_k"], errors="ignore")
    if "macro_calendar_quarter_join" not in feat.columns:
        return pd.DataFrame()
    key_set = set(work["calendar_quarter"].astype(str).str.strip().unique())
    fs = feat.copy()
    fs["_k"] = fs["macro_calendar_quarter_join"].astype(str).str.strip()
    return fs[fs["_k"].isin(key_set)].drop(columns=["_k"], errors="ignore")


def _sss_tickers_vs_peer_chart(feat_slice: pd.DataFrame, *, height: int = 360) -> None:
    """One line per ``Ticker`` for ``sss`` (ppt) on **Gregorian calendar quarters**, plus peer average.

    This chart always uses **calendar quarter** (`macro_calendar_quarter_join`) so each point is one
    fiscal row per ticker whose ``Prd_End`` falls in that quarter — the dashed peer line is the
    equal-weight **mean of peer-basket** ``sss`` in that **same** calendar quarter (not a mix of fiscal
    ``PeerSSSIndex`` columns and not month-bucket averages that blended incomparable fiscal periods).
    """
    st.subheader("Company SSS (`sss`) by ticker vs peer average (calendar quarters)")
    if feat_slice.empty:
        st.caption("No workbook rows in this date window.")
        return
    if "Ticker" not in feat_slice.columns or "sss" not in feat_slice.columns:
        st.caption("Wide panel missing `Ticker` or `sss`.")
        return
    xcol = "calendar_quarter"
    br = feat_slice.copy()
    if "macro_calendar_quarter_join" not in br.columns:
        st.caption("Missing `macro_calendar_quarter_join` (need fiscal×macro quarter join).")
        return
    br[xcol] = br["macro_calendar_quarter_join"].astype(str).str.strip()

    # Match workbook pipeline: plain numbers in (-1, 1) are decimal fractions → ×100 to ppt.
    br["sss"] = br["sss"].map(sheets_client._coerce_percent_points)
    tick_rows = br.dropna(subset=[xcol, "Ticker", "sss"]).copy()
    tick_rows["Ticker"] = tick_rows["Ticker"].astype(str).str.strip()
    if tick_rows.empty:
        st.warning("No numeric `sss` rows to plot in this window.")
        return

    long_t = tick_rows[[xcol, "Ticker", "sss"]].rename(columns={"sss": "value"})
    long_t = long_t.groupby([xcol, "Ticker"], as_index=False)["value"].median()
    tick_order = sorted(long_t["Ticker"].unique())

    peers = getattr(sheets_client, "_MLP_PEER_SSS_TICKERS", ())
    peer_set = {str(t).strip() for t in peers}
    peer_df = (
        long_t.loc[long_t["Ticker"].isin(peer_set), [xcol, "value"]]
        .groupby(xcol, as_index=False)["value"]
        .mean()
        .rename(columns={"value": "PeerSSSIndex"})
        .dropna(subset=["PeerSSSIndex"])
    )

    st.caption(
        "**Gregorian calendar quarter** (from each row’s ``Prd_End``). Dashed line = equal-weight mean of "
        f"peer-basket `sss` ({', '.join(sorted(peer_set))}) in that quarter. "
        "Macro charts above may be monthly or quarterly; this block is **always quarterly** so peer "
        "and tickers share one comparable time index. Workbook `PeerSSSIndex` (fiscal-`Prd_Nm`) is not used here."
    )

    if alt is None:
        for tkr in tick_order:
            g = long_t.loc[long_t["Ticker"] == tkr, [xcol, "value"]].sort_values(xcol)
            if not g.empty:
                st.caption(tkr)
                st.line_chart(g, x=xcol, y="value", height=120)
        if not peer_df.empty:
            st.caption("Peer avg (peer-set SSS)")
            st.line_chart(
                peer_df.rename(columns={"PeerSSSIndex": "value"}).sort_values(xcol),
                x=xcol,
                y="value",
                height=160,
            )
        return

    x_order = sorted(long_t[xcol].astype(str).unique(), key=quarter_label_sort_key)
    x_enc = alt.X(f"{xcol}:N", title="Calendar quarter (Prd_End)", sort=x_order)
    x_enc_p = alt.X(f"{xcol}:N", sort=x_order)
    x_tt = alt.Tooltip(xcol, title="quarter")

    left = (
        alt.Chart(long_t)
        .mark_line()
        .encode(
            x=x_enc,
            y=alt.Y("value:Q", title="SSS (ppt)", scale=alt.Scale(zero=False)),
            color=alt.Color("Ticker:N", sort=tick_order, legend=alt.Legend(labelLimit=120)),
            tooltip=[x_tt, "Ticker", alt.Tooltip("value:Q", format=",.2f", title="sss")],
        )
    )
    if peer_df.empty:
        st.altair_chart(left.properties(height=height), use_container_width=True)
        return

    peer_line = (
        alt.Chart(peer_df)
        .mark_line(strokeDash=[6, 4], strokeWidth=2.5, color="#b83b5e")
        .encode(
            x=x_enc_p,
            y=alt.Y("PeerSSSIndex:Q", title="SSS (ppt)", scale=alt.Scale(zero=False)),
            tooltip=[x_tt, alt.Tooltip("PeerSSSIndex:Q", title="Peer avg (ppt)", format=",.2f")],
        )
    )
    chart = alt.layer(left, peer_line).resolve_scale(y="shared").properties(height=height)
    st.altair_chart(chart, use_container_width=True)


# (title, macro column names[, optional kwargs for ``line_chart_with_peer``]) — ``PeerSSSIndex`` on each chart.
_DRAFT_CHART_SPECS: tuple[tuple[str, tuple[str, ...]] | tuple[str, tuple[str, ...], dict[str, Any]], ...] = (
    (
        "YoY % — food-away-from-home CPI vs PeerSSSIndex",
        ("cpi_food_away_from_home_index_yoy_pct",),
    ),
    (
        "YoY % — retail food services & drinking (NSA, NAICS 722) vs PeerSSSIndex",
        ("retail_food_services_drinking_sales_millions_nsa_yoy_pct",),
    ),
    (
        "“Real demand” spread: retail food services YoY − FAFH CPI YoY",
        ("real_restaurant_demand_sales_minus_faho_cpi_yoy_spread_pct",),
    ),
    (
        "YoY % — CPI-U all items (headline) vs PeerSSSIndex",
        ("cpi_u_all_items_sa_index_yoy_pct",),
    ),
    (
        "YoY % — CPI-U core (less food & energy) vs PeerSSSIndex",
        ("cpi_u_core_less_food_energy_sa_index_yoy_pct",),
    ),
    (
        "YoY % — CPI-U food at home vs PeerSSSIndex",
        ("cpi_u_food_at_home_sa_index_yoy_pct",),
    ),
    (
        "Spread: retail food services YoY − headline CPI-U YoY",
        ("real_restaurant_demand_sales_minus_headline_cpi_yoy_spread_pct",),
    ),
    ("Unemployment % (level)", ("unemployment_rate_pct",)),
    ("Gas — regular, US avg ($/gal)", ("gas_regular_us_avg_usd_per_gal",)),
    (
        "Retail sales: NAICS 722 (food services & drinking) vs limited-service 7222, millions NSA",
        (
            "retail_food_services_drinking_sales_millions_nsa",
            "retail_sales_limited_service_eating_places_naics7222_millions_nsa",
        ),
    ),
    (
        "YoY % — NAICS 722 vs 7222 retail sales (NSA)",
        (
            "retail_food_services_drinking_sales_millions_nsa_yoy_pct",
            "retail_sales_limited_service_eating_places_naics7222_millions_nsa_yoy_pct",
        ),
    ),
    (
        "BLS CES — limited-service restaurants (722513) employment (thousands, SA)",
        ("bls_ces_limited_service_restaurants_naics722513_employment_thousands_sa",),
    ),
    (
        "BLS CES — limited-service restaurants (722513) avg hourly earnings (USD, SA)",
        ("bls_ces_limited_service_restaurants_naics722513_avg_hourly_earnings_usd_sa",),
    ),
    (
        "YoY % — BLS CES limited-service (722513) avg hourly earnings (SA)",
        ("bls_ces_limited_service_restaurants_naics722513_avg_hourly_earnings_usd_sa_yoy_pct",),
    ),
    (
        "ECI wages & salaries — all civilian workers (SA index; quarterly expanded to months)",
        ("eci_wages_salaries_all_civilian_index_sa",),
    ),
    (
        "YoY % — ECI wages & salaries (all civilian, SA index)",
        ("eci_wages_salaries_all_civilian_index_sa_yoy_pct",),
    ),
    (
        "FRED CES — all private avg hourly earnings (USD, SA)",
        ("fred_ces_all_private_avg_hourly_earnings_usd_sa",),
    ),
    (
        "YoY % — FRED CES all private avg hourly earnings (SA)",
        ("fred_ces_all_private_avg_hourly_earnings_usd_sa_yoy_pct",),
    ),
    (
        "CPS — median usual weekly nominal earnings, full-time wage & salary (expanded to months)",
        ("cps_median_usual_weekly_nominal_ft_wage_salary_usd",),
    ),
    (
        "YoY % — CPS median usual weekly nominal (full-time wage & salary)",
        ("cps_median_usual_weekly_nominal_ft_wage_salary_usd_yoy_pct",),
    ),
    (
        "YoY % — workforce pay blend (mean of CES all-private AHE YoY + CPS median weekly YoY)",
        ("workforce_pay_ces_cps_avg_yoy_pct",),
    ),
    (
        "YoY % — PPI retail & shopping space rent",
        tuple(c for c, _ in macro_data.PPI_SHOPPING_RETAIL_RENT_YOY_CHART_SPECS),
    ),
    (
        f"USD to match $1000 of broilers ({macro_data.SPEND_EQUIV_BASE_YEAR} avg $/lb paste) — vs PeerSSSIndex",
        (macro_data.SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS[0][1],),
        {
            "left_axis_title": f"USD ({macro_data.SPEND_EQUIV_BASE_YEAR} basket)",
            "height": 280,
        },
    ),
    (
        f"USD to match $1000 of all-beef cattle ({macro_data.SPEND_EQUIV_BASE_YEAR} avg $/cwt paste) — vs PeerSSSIndex",
        (macro_data.SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS[1][1],),
        {
            "left_axis_title": f"USD ({macro_data.SPEND_EQUIV_BASE_YEAR} basket)",
            "height": 280,
        },
    ),
    (
        f"USD to match $1000 of limited-svc hourly wage ({macro_data.SPEND_EQUIV_BASE_YEAR} avg SA) — vs PeerSSSIndex",
        (macro_data.SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS[2][1],),
        {
            "left_axis_title": f"USD ({macro_data.SPEND_EQUIV_BASE_YEAR} wage basket)",
            "height": 280,
        },
    ),
    (
        f"USD to match $1000 of PPI retail & shopping-center rent index ({macro_data.SPEND_EQUIV_BASE_YEAR} avg) — vs PeerSSSIndex",
        (macro_data.SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS[3][1],),
        {
            "left_axis_title": f"USD ({macro_data.SPEND_EQUIV_BASE_YEAR} rent index basket)",
            "height": 280,
        },
    ),
)


st.title("Industry backdrop")

# ``st.tabs`` runs *every* tab’s body on each rerun, which forced a full workbook+macro load even when
# only the thesis markdown was visible. Use an explicit section control so we load data only for Draft.
_SECTION_THESIS = "Thesis (working)"
_SECTION_DRAFT = "Draft charts — delete later"
_section = st.radio(
    " ",
    (_SECTION_THESIS, _SECTION_DRAFT),
    horizontal=True,
    key="ib_active_section",
    label_visibility="collapsed",
)
st.divider()

if _section == _SECTION_THESIS:
    st.markdown(
        """
### Working thesis (edit as charts settle)

**1. Nominal vs “real” demand** — Restaurant top-line moves with **nominal** spending and **pricing**
(food-away-from-home CPI). The spread **Census NAICS 722 (NSA) retail YoY − FAFH CPI YoY** (already in the macro
panel as `real_restaurant_demand_sales_minus_faho_cpi_yoy_spread_pct`) is a blunt read on whether
**volume-ish** demand is running ahead or behind **price** in the national data. **Headline CPI-U**
(`cpi_u_all_items_sa_index_yoy_pct`) and **core** (`cpi_u_core_less_food_energy_sa_index_yoy_pct`) add
a pocketbook / policy backdrop; **food at home** (`cpi_u_food_at_home_sa_index_yoy_pct`) contrasts
grocery inflation with away-from-home. For SSS modeling, try **SSS YoY minus** one of those CPI YoYs
as a simple “real comp” read (same fiscal×calendar join as other macro features).

**2. Labor + pump prices as pressure gauges** — **Unemployment** and **gas** do not “forecast” CMG’s
next quarter, but they shape the **consumer pocketbook narrative** that shows up in discretionary
frequency and trade-down chatter.

**3. Restaurant retail (Census/FRED)** — **NAICS 722** headline food services & drinking (**NSA** levels and YoY) vs
**7222** limited-service eating places is a coarse **format mix** backdrop; Census no longer publishes
a current national **full-service-only** retail sales millions split on FRED.

**4. BLS CES + paste commodities + PPI retail rent** — **722513** hourly earnings (SA), **broiler / beef cattle** paste
prices, and **PPI shopping-center / retail-store lease rent** (NSA index) use **calendar-year average**
anchors for :obj:`macro_data.SPEND_EQUIV_BASE_YEAR` (default **2019**). Draft charts plot
``equiv_usd_1000_at_<year>avg_*``: dollars needed **today** for the same basket (or **hours of labor**
implied by \$1000 of that wage at the anchor year). For the rent index, read it as **how many current
dollars match \$1000 of that lease-rent index at the anchor year’s average level**. The **annual**
roll-up lives under ``macro[macro_data.spend_equiv_annual_dict_key()]`` and the matching
``mlp_macro_annual_<year>_spend_equiv.csv``.

---

When the draft charts look right, fold the strongest 2–3 into this tab (or a child section) and
**remove the Draft section** plus the helper functions at the top of this file if you inlined them.
"""
    )
else:
    st.caption(
        "Exploratory only — remove this branch (or the whole Draft section) once charts are "
        "promoted to the main narrative."
    )
    bundle = get_dashboard_bundle_or_stop()
    monthly = monthly_macro_with_index(bundle)
    cq = bundle["macro"].get("calendar_quarter")
    if cq is None or cq.empty:
        cq = pd.DataFrame()

    if monthly.empty:
        st.warning("Macro monthly frame is empty — check FRED key and data load.")
    else:
        feat_tables = bundle.get("feature_tables") or {}
        feat_m = feat_tables.get("fiscal_wide_x_macro_calendar_month")
        feat_q = feat_tables.get("fiscal_wide_x_macro_calendar_quarter")
        if feat_m is None or not isinstance(feat_m, pd.DataFrame):
            feat_m = pd.DataFrame()
        if feat_q is None or not isinstance(feat_q, pd.DataFrame):
            feat_q = pd.DataFrame()

        freq = st.radio(
            "Macro frequency",
            ["Monthly", "Quarterly"],
            horizontal=True,
            key="ib_macro_freq",
        )
        years = st.slider(
            "Years of history (from latest period)",
            1,
            25,
            12,
            key="ib_years",
        )

        peer_by_m = peer_sss_by_month_end(feat_m)
        peer_by_q = _peer_sss_by_calendar_quarter(feat_q)

        temporal = freq == "Monthly"
        if temporal:
            m_strict = _filter_recent(monthly, years)
            work_stats = merge_peer_on_monthly(m_strict, peer_by_m)
            m_base, _y_used, expand_note = _expand_window_for_marts(monthly, years)
            if expand_note:
                st.info(expand_note)
            work = merge_peer_on_monthly(m_base, peer_by_m)
            x_col = "month_end"
        else:
            if cq is None or cq.empty:
                st.warning("Macro calendar-quarter frame is empty.")
                work = pd.DataFrame()
            else:
                cq_full = cq.reset_index()
                cq_full = _merge_peer_on_quarterly(cq_full, peer_by_q)
                work = _filter_recent_quarters(cq_full, years)
            x_col = "calendar_quarter"
            work_stats = work

        st.caption(
            "Pink dashed line: **PeerSSSIndex** (ppt) from the workbook wide panel, aligned by each "
            "fiscal row’s calendar month-end or calendar quarter of **Prd_End** (median across tickers when "
            "several map to the same period)."
        )

        if not temporal and work.empty:
            st.warning("Macro calendar-quarter frame is empty — cannot plot quarterly charts.")
        elif work.empty:
            st.warning("No rows in the working frame for charts.")
        else:
            n_charts = len(_DRAFT_CHART_SPECS)
            for i, spec in enumerate(_DRAFT_CHART_SPECS):
                chart_title = spec[0]
                cols = spec[1]
                line_kw = dict(spec[2]) if len(spec) > 2 else {}
                line_kw.setdefault("height", 260)
                line_chart_with_peer(
                    work,
                    chart_title,
                    list(cols),
                    x=x_col,
                    temporal_x=temporal,
                    **line_kw,
                )
                render_peer_vs_macro_stats(
                    work_stats,
                    cols,
                    slider_years=years,
                    x_col=x_col,
                    caption_suffix=" Charts above may be wider if MRTS auto-expanded.",
                )
                if i < n_charts - 1:
                    st.divider()

            st.divider()
            if temporal:
                st.info(
                    "Google Trends vs **PeerSSSIndex** (raw + optional **trailing moving average**): "
                    "use the **Google Trends vs peer** page in the sidebar."
                )

            sss_work = work_stats if temporal else work
            sss_slice = _feat_slice_calendar_quarter_sss(feat_q, sss_work, macro_is_monthly=temporal)
            _sss_tickers_vs_peer_chart(sss_slice, height=360)

        with st.expander("Raw tail (debug)"):
            st.dataframe(work.tail(8) if not work.empty else monthly.tail(6), use_container_width=True, hide_index=True)
