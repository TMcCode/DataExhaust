"""Google Trends (monthly CSV) vs workbook **PeerSSSIndex** — raw + fixed 3-month trailing average."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_dashboard.data_loader import get_dashboard_bundle_or_stop
from streamlit_dashboard.gtrends_loader import gtrends_csv_path, load_gtrends_monthly_csv
from streamlit_dashboard.peer_gtrends_utils import (
    GTRENDS_VS_PEER_SPECS,
    RECIPE_YOY_INVERTED_COL,
    add_recipe_inv_ma_forward_one_quarter,
    add_recipe_yoy_inverted,
    append_gtrends_trailing_moving_avg,
    filter_recent_months,
    gtrends_numeric_base_columns,
    is_recipe_yoy_inverted_raw_spec,
    line_chart_with_peer,
    merge_gtrends_by_calendar_month,
    merge_peer_on_monthly,
    monthly_macro_with_index,
    peer_sss_by_month_end,
    recipe_inv_ma_fwd1q_column,
    render_peer_vs_macro_stats,
)

ROLL_MONTHS = 3


def main() -> None:
    st.title("Google Trends vs peer")
    st.caption(
        "Monthly macro **month_end** joined to Google Trends CSV **`month`** (YYYY-MM). "
        "**PeerSSSIndex** (ppt, dashed) is the median across tickers on each calendar month from the "
        "fiscal×macro month panel. Each chart shows **raw** Trends plus a **3-month trailing average** "
        "(same left axis). **Recipe** block plots **inverted** (−`recipe_yoy_pct`) **and** **raw** YoY together; "
        "the **inverted 3-month average** is shifted **+1 quarter** on the time axis (and in the MA stats table) "
        "to peek at peer lag vs recipe. "
        "Tables under each chart: **r**, **R²**, **MAPE** for raw series and again for 3-month averages vs peer."
    )

    bundle = get_dashboard_bundle_or_stop()
    monthly = monthly_macro_with_index(bundle)
    if monthly.empty:
        st.warning("Macro monthly frame is empty — check data load.")
        return

    feat_tables = bundle.get("feature_tables") or {}
    feat_m = feat_tables.get("fiscal_wide_x_macro_calendar_month")
    if feat_m is None or not isinstance(feat_m, pd.DataFrame):
        feat_m = pd.DataFrame()

    years = st.slider("Years of history (from latest month)", 1, 35, 12, key="gt_peer_years")

    gt = load_gtrends_monthly_csv()
    if gt.empty:
        st.info(
            f"No Google Trends CSV at **{gtrends_csv_path()}**. "
            "Run `python gtrends_monthly_brands.py` (use `--start-date 2018-01-01` for long history), "
            "or set **`MLP_GTRENDS_CSV`** / optional **`MLP_GTRENDS_APPEND_CSV`** for stitched GCS history."
        )
        return

    peer_by_m = peer_sss_by_month_end(feat_m)
    m_win = filter_recent_months(monthly, years)
    work = merge_peer_on_monthly(m_win, peer_by_m)
    work_gt = merge_gtrends_by_calendar_month(work, gt)
    work_gt = add_recipe_yoy_inverted(work_gt)
    bases = gtrends_numeric_base_columns(work_gt)
    work_gt = append_gtrends_trailing_moving_avg(work_gt, bases, window=ROLL_MONTHS)
    work_gt = add_recipe_inv_ma_forward_one_quarter(work_gt, window=ROLL_MONTHS)
    # Stats must use the same frame as charts so **PeerSSSIndex** exists (was: merge on ``m_win`` only).

    first = True
    for gt_title, gt_cols in GTRENDS_VS_PEER_SPECS:
        have = [c for c in gt_cols if c in work_gt.columns]
        if not have:
            continue

        recipe_yoy_dual = is_recipe_yoy_inverted_raw_spec(tuple(gt_cols))
        fwd_inv_ma = recipe_inv_ma_fwd1q_column(ROLL_MONTHS)
        chart_cols = list(have)
        for c in have:
            ma = f"{c}_ma{ROLL_MONTHS}"
            if ma not in work_gt.columns:
                continue
            if recipe_yoy_dual and c == RECIPE_YOY_INVERTED_COL and fwd_inv_ma in work_gt.columns:
                chart_cols.append(fwd_inv_ma)
            else:
                chart_cols.append(ma)
        title = f"{gt_title} — raw + {ROLL_MONTHS}-mo avg"
        if recipe_yoy_dual and fwd_inv_ma in work_gt.columns:
            title += " (inverted MA +1 quarter)"

        if not first:
            st.divider()
        first = False

        line_chart_with_peer(
            work_gt,
            title,
            chart_cols,
            x="month_end",
            temporal_x=True,
            height=260,
            left_axis_title="Google Trends (left)",
        )
        render_peer_vs_macro_stats(
            work_gt,
            tuple(have),
            slider_years=years,
            x_col="month_end",
            feature_label="Trends (raw)",
        )

        ma_stats_list: list[str] = []
        for c in have:
            ma = f"{c}_ma{ROLL_MONTHS}"
            if ma not in work_gt.columns:
                continue
            if recipe_yoy_dual and c == RECIPE_YOY_INVERTED_COL and fwd_inv_ma in work_gt.columns:
                ma_stats_list.append(fwd_inv_ma)
            else:
                ma_stats_list.append(ma)
        ma_stats = tuple(ma_stats_list)
        if ma_stats:
            st.caption(f"**Peer vs {ROLL_MONTHS}-month trailing average** (same window)")
            render_peer_vs_macro_stats(
                work_gt,
                ma_stats,
                slider_years=years,
                x_col="month_end",
                feature_label=f"{ROLL_MONTHS}-mo average",
            )


main()
