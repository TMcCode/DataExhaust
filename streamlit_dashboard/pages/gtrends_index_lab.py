"""Temporary lab — mix Google Trends columns into a custom index vs PeerSSSIndex."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from streamlit_dashboard.data_loader import get_dashboard_bundle_or_stop
from streamlit_dashboard.gtrends_loader import gtrends_csv_path, load_gtrends_monthly_csv
from streamlit_dashboard.peer_gtrends_utils import (
    add_recipe_yoy_inverted,
    filter_recent_months,
    line_chart_with_peer,
    merge_gtrends_by_calendar_month,
    merge_peer_on_monthly,
    monthly_macro_with_index,
    peer_sss_by_month_end,
    render_peer_vs_macro_stats,
)


def _zscore_series(s: pd.Series) -> pd.Series:
    """Match ``gtrends_monthly_brands.zscore`` (population std; flat if no variance)."""
    x = pd.to_numeric(s, errors="coerce").astype(float)
    std = float(x.std(ddof=0))
    if not np.isfinite(std) or std == 0.0:
        return pd.Series(0.0, index=x.index)
    return (x - float(x.mean())) / std


def build_custom_gt_index(
    df: pd.DataFrame,
    cols: list[str],
    *,
    invert: frozenset[str],
    window: int,
    z_mean: bool,
) -> pd.DataFrame:
    """Sort by ``month_end``, apply invert → rolling → optional z-score → equal-weight mean → ``custom_gt_index``."""
    if not cols:
        out = df.copy()
        out["custom_gt_index"] = np.nan
        return out

    s = df.sort_values("month_end", kind="mergesort").copy()
    miss = [c for c in cols if c not in s.columns]
    if miss:
        out = df.copy()
        out["custom_gt_index"] = np.nan
        return out

    block = pd.DataFrame({c: pd.to_numeric(s[c], errors="coerce").astype(float) for c in cols}, index=s.index)
    for c in cols:
        if c in invert:
            block[c] *= -1.0
    w = max(1, int(window))
    for c in cols:
        block[c] = block[c].rolling(window=w, min_periods=1).mean()
    if z_mean:
        for c in cols:
            block[c] = _zscore_series(block[c])
    s["custom_gt_index"] = block.mean(axis=1, skipna=True)
    return s


def main() -> None:
    st.title("GTrends index lab (temp)")
    st.caption(
        "Pick any **Trends columns** from your CSV (levels or YoY %), optionally **invert** some (×−1), "
        "set a **rolling window** on each input (then combine), and choose **Z-mean** (like the shipped "
        "composite) or a **plain mean**. The result is plotted vs **PeerSSSIndex** with quick correlation "
        "stats. Remove this page when you settle on a recipe."
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

    gt = load_gtrends_monthly_csv()
    if gt.empty:
        st.info(
            f"No Google Trends CSV at **{gtrends_csv_path()}**. "
            "Run `python gtrends_monthly_brands.py` (e.g. `--start-date 2018-01-01`), set **`MLP_GTRENDS_CSV`**, "
            "and/or **`MLP_GTRENDS_APPEND_CSV`** for archived months from GCS."
        )
        return

    base_cols = [c for c in gt.columns if str(c) != "month"]
    peer_by_m = peer_sss_by_month_end(feat_m)
    years = st.slider("Years of history (from latest month)", 1, 35, 12, key="lab_years")
    m_win = filter_recent_months(monthly, years)
    work = merge_peer_on_monthly(m_win, peer_by_m)
    work_gt = merge_gtrends_by_calendar_month(work, gt)
    work_gt = add_recipe_yoy_inverted(work_gt)

    opts = sorted({c for c in base_cols if c in work_gt.columns})
    if "recipe_yoy_pct_inv" in work_gt.columns:
        opts = sorted(set(opts) | {"recipe_yoy_pct_inv"})

    default_pick = [c for c in ("chipotle", "fast_casual", "food_near_me", "restaurants_near_me", "delivery") if c in opts][
        :5
    ] or (opts[:3] if opts else [])

    selected = st.multiselect(
        "Trends columns to mix",
        options=opts,
        default=default_pick,
        key="lab_gt_cols",
        help="Levels (0–100 vs own peak) and YoY % columns from the CSV; inverted recipe YoY if present.",
    )
    invert = st.multiselect(
        "Invert (multiply by −1) before rolling",
        options=selected,
        key="lab_invert",
        help="Use for substitution-style terms (e.g. recipe, meal prep) if you want “more search = headwind”.",
    )
    roll_w = st.slider("Rolling window on each input (months)", 1, 12, 3, key="lab_roll")
    z_mean = st.radio(
        "Combine",
        ("Z-mean (like shipped composite)", "Simple mean (no z-score)"),
        horizontal=True,
        key="lab_combine",
    ) == "Z-mean (like shipped composite)"
    overlay = st.checkbox(
        "Overlay official **fast_casual_index** (left axis, second line)",
        value=False,
        key="lab_overlay",
    )

    if not selected:
        st.warning("Choose at least one Trends column.")
        return

    built = build_custom_gt_index(
        work_gt,
        selected,
        invert=frozenset(invert),
        window=roll_w,
        z_mean=z_mean,
    )

    if built["custom_gt_index"].notna().sum() == 0:
        st.error("Custom index is all NaN — check that selected columns have numeric data in this window.")
        return

    ycols = ["custom_gt_index"]
    title = "Custom GTrends mix vs PeerSSSIndex"
    if overlay and "fast_casual_index" in built.columns:
        ycols.append("fast_casual_index")
        title += " (with official composite)"

    line_chart_with_peer(
        built,
        title,
        ycols,
        x="month_end",
        temporal_x=True,
        height=320,
        left_axis_title="Custom index (left)",
    )

    st.subheader("Peer vs custom index (stats)")
    render_peer_vs_macro_stats(
        built,
        ("custom_gt_index",),
        slider_years=years,
        x_col="month_end",
        feature_label="custom index",
    )
    if len(ycols) > 1:
        st.caption("Official **fast_casual_index** (for eyeball only — stats above are vs **custom**).")
        render_peer_vs_macro_stats(
            built,
            ("fast_casual_index",),
            slider_years=years,
            x_col="month_end",
            feature_label="official composite",
        )

    with st.expander("Builder recipe (copy)"):
        st.code(
            "columns:\n"
            + "\n".join(f"  - {c}{'  (inverted)' if c in invert else ''}" for c in selected)
            + f"\nrolling_months: {roll_w}\n"
            + f"combine: {'z_mean' if z_mean else 'simple_mean'}\n",
            language="yaml",
        )


main()
