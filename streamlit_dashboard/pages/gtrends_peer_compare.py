"""One place to scan **PeerSSSIndex** vs every Google Trends column: raw, 3-mo trailing MA, and MA YoY %."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from streamlit_dashboard.data_loader import get_dashboard_bundle_or_stop
from streamlit_dashboard.gtrends_loader import gtrends_csv_path, load_gtrends_monthly_csv
from streamlit_dashboard.peer_gtrends_utils import (
    PEER_COL,
    RECIPE_YOY_INVERTED_COL,
    add_recipe_inv_ma_forward_one_quarter,
    add_recipe_yoy_inverted,
    append_gtrends_ma_yoy12,
    append_gtrends_trailing_moving_avg,
    corr_r2_mape_xy,
    filter_recent_months,
    gtrends_numeric_base_columns,
    line_chart_with_peer,
    merge_gtrends_by_calendar_month,
    merge_peer_on_monthly,
    monthly_macro_with_index,
    peer_sss_by_month_end,
    recipe_inv_ma_fwd1q_column,
)

ROLL_MONTHS = 3


def _peer_gtrends_frame(
    *,
    bundle: dict,
    feat_m: pd.DataFrame,
    years: int,
) -> pd.DataFrame | None:
    """Merged monthly **PeerSSSIndex** + Google Trends + MA + MA YoY12 (same window as **Google Trends vs peer**)."""
    monthly = monthly_macro_with_index(bundle)
    if monthly.empty:
        return None
    gt = load_gtrends_monthly_csv()
    if gt.empty:
        return None
    peer_by_m = peer_sss_by_month_end(feat_m)
    m_win = filter_recent_months(monthly, years)
    work = merge_peer_on_monthly(m_win, peer_by_m)
    work_gt = merge_gtrends_by_calendar_month(work, gt)
    work_gt = add_recipe_yoy_inverted(work_gt)
    bases = gtrends_numeric_base_columns(work_gt)
    work_gt = append_gtrends_trailing_moving_avg(work_gt, bases, window=ROLL_MONTHS)
    work_gt = add_recipe_inv_ma_forward_one_quarter(work_gt, window=ROLL_MONTHS)

    ma_cols: list[str] = []
    for b in bases:
        mc = f"{b}_ma{ROLL_MONTHS}"
        if mc in work_gt.columns:
            ma_cols.append(mc)
    ma_cols = list(dict.fromkeys(ma_cols))
    fwd = recipe_inv_ma_fwd1q_column(ROLL_MONTHS)
    if fwd in work_gt.columns and fwd not in ma_cols:
        ma_cols.append(fwd)

    return append_gtrends_ma_yoy12(work_gt, ma_cols)


def _stats_vs_peer(work: pd.DataFrame, *, roll: int) -> pd.DataFrame:
    if work.empty or PEER_COL not in work.columns or "month_end" not in work.columns:
        return pd.DataFrame()
    bases = [b for b in gtrends_numeric_base_columns(work) if b in work.columns and str(b) != PEER_COL]
    ma_cols: list[str] = []
    for b in gtrends_numeric_base_columns(work):
        mc = f"{b}_ma{roll}"
        if mc in work.columns:
            ma_cols.append(mc)
    ma_cols = list(dict.fromkeys(ma_cols))
    fwd = recipe_inv_ma_fwd1q_column(roll)
    if fwd in work.columns and fwd not in ma_cols:
        ma_cols.append(fwd)

    y_peer = pd.to_numeric(work[PEER_COL], errors="coerce").to_numpy(dtype=float)
    rows: list[dict[str, str | float | int]] = []

    def _add_row(transform: str, col: str) -> None:
        if col not in work.columns:
            return
        xv = pd.to_numeric(work[col], errors="coerce").to_numpy(dtype=float)
        r, r2, mape = corr_r2_mape_xy(xv, y_peer)
        nn = int(np.sum(np.isfinite(xv) & np.isfinite(y_peer)))
        rows.append(
            {
                "transform": transform,
                "gtrends_column": col,
                "r": r,
                "R2": r2,
                "MAPE_pct": mape,
                "n": nn,
            }
        )

    for b in bases:
        _add_row("raw", b)
    for mc in ma_cols:
        _add_row(f"{roll}m MA", mc)
        yc = f"{mc}_yoy12_pct"
        _add_row(f"{roll}m MA YoY %", yc)

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["abs_r"] = out["r"].abs()
    return out.sort_values(["abs_r", "gtrends_column"], ascending=[False, True]).drop(columns=["abs_r"])


def main() -> None:
    st.title("GTrends vs peer — compare all")
    st.caption(
        f"**{PEER_COL}** vs every merged Google Trends column: **raw**, **{ROLL_MONTHS}-month trailing average**, "
        f"and **YoY % on that average** (12-month percent change on the smoothed series). "
        "Stats use the **years** slider only. Same joins as **Google Trends vs peer**."
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

    years = st.slider("Years of history (from latest month)", 1, 35, 12, key="gt_compare_years")

    work_win = _peer_gtrends_frame(bundle=bundle, feat_m=feat_m, years=years)
    if work_win is None:
        st.info(
            f"No Google Trends CSV at **{gtrends_csv_path()}**. "
            "Run `python gtrends_monthly_brands.py` or `load_mlp_master.py --gtrends`, "
            "or set **`MLP_GTRENDS_CSV`** / **`MLP_GTRENDS_APPEND_CSV`**."
        )
        return

    tab_stats, tab_chart = st.tabs(["All series vs peer (table)", "Pick series — chart"])

    with tab_stats:
        stats_df = _stats_vs_peer(work_win, roll=ROLL_MONTHS)
        if stats_df.empty:
            st.warning("No overlapping stats — widen the years slider or check Trends CSV columns.")
        else:
            st.dataframe(
                stats_df,
                use_container_width=True,
                hide_index=True,
                height=min(720, 28 + 36 * len(stats_df)),
                column_config={
                    "transform": st.column_config.TextColumn("View"),
                    "gtrends_column": st.column_config.TextColumn("GTrends column"),
                    "r": st.column_config.NumberColumn("r", format="%.3f"),
                    "R2": st.column_config.NumberColumn("R²", format="%.3f"),
                    "MAPE_pct": st.column_config.NumberColumn("MAPE %", format="%.1f"),
                    "n": st.column_config.NumberColumn("n", format="%d"),
                },
            )
            st.download_button(
                "Download table as CSV",
                data=stats_df.to_csv(index=False).encode("utf-8"),
                file_name="gtrends_peer_compare_stats.csv",
                mime="text/csv",
            )

    with tab_chart:
        bases = [b for b in gtrends_numeric_base_columns(work_win) if b in work_win.columns]
        ma_cols = [f"{b}_ma{ROLL_MONTHS}" for b in bases if f"{b}_ma{ROLL_MONTHS}" in work_win.columns]
        ma_cols = list(dict.fromkeys(ma_cols))
        fwd = recipe_inv_ma_fwd1q_column(ROLL_MONTHS)
        if fwd in work_win.columns and fwd not in ma_cols:
            ma_cols.append(fwd)
        ma_yoy = [f"{m}_yoy12_pct" for m in ma_cols if f"{m}_yoy12_pct" in work_win.columns]
        choices = list(dict.fromkeys([*bases, *ma_cols, *ma_yoy]))
        default: list[str] = []
        for d in ("fast_casual_index_yoy_pct", RECIPE_YOY_INVERTED_COL, "chipotle_yoy_pct"):
            if d in choices and len(default) < 4:
                default.append(d)

        picked = st.multiselect(
            "GTrends columns (left axis; PeerSSSIndex dashed on right)",
            choices,
            default=default or choices[: min(3, len(choices))],
            key="gt_compare_pick",
        )
        if not picked:
            st.caption("Select at least one column.")
        else:
            line_chart_with_peer(
                work_win,
                "PeerSSSIndex vs selected Google Trends columns",
                picked,
                x="month_end",
                temporal_x=True,
                height=380,
                left_axis_title="Google Trends (left)",
            )


main()
