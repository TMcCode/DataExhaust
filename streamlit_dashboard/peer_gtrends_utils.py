"""Shared helpers: macro month-end frame, PeerSSSIndex joins, Google Trends merge, dual-axis Altair charts."""

from __future__ import annotations

import re
from typing import Iterable, Sequence

import analytic_panel
import numpy as np
import pandas as pd
import streamlit as st

try:
    import altair as alt
except ImportError:  # pragma: no cover
    alt = None  # type: ignore[misc, assignment]

PEER_COL = "PeerSSSIndex"

# Synthetic: ``-recipe_yoy_pct`` so higher recipe interest reads like a “headwind” vs peer SSS.
RECIPE_YOY_INVERTED_COL = "recipe_yoy_pct_inv"
# Raw ``recipe_yoy_pct`` + inverted YoY (same chart block as ``RECIPE_YOY_INVERTED_COL``).
_RECIPE_YOY_INVERTED_RAW_COLS = frozenset({RECIPE_YOY_INVERTED_COL, "recipe_yoy_pct"})

GTRENDS_VS_PEER_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Composite + index delta
    (
        "Google Trends — fast casual composite (z-mean index) vs PeerSSSIndex",
        ("fast_casual_index",),
    ),
    (
        "Google Trends — composite index YoY change (index pts vs 12m ago) vs PeerSSSIndex",
        ("fast_casual_index_yoy_chg",),
    ),
    (
        "Google Trends YoY % — fast casual (category) vs PeerSSSIndex",
        ("fast_casual_yoy_pct",),
    ),
    # Recipe: inverted (−YoY) **and** raw Google YoY % on one chart + separate stats rows for each
    (
        "Google Trends YoY % — Recipe **inverted + raw** (left: −YoY vs Google YoY %; same 3-mo avg) vs PeerSSSIndex",
        (RECIPE_YOY_INVERTED_COL, "recipe_yoy_pct"),
    ),
    (
        "Google Trends YoY % — meal prep vs PeerSSSIndex",
        ("meal_prep_yoy_pct",),
    ),
    # Category / demand
    (
        "Google Trends YoY % — restaurants near me vs PeerSSSIndex",
        ("restaurants_near_me_yoy_pct",),
    ),
    (
        "Google Trends YoY % — food near me vs PeerSSSIndex",
        ("food_near_me_yoy_pct",),
    ),
    (
        "Google Trends YoY % — delivery vs PeerSSSIndex",
        ("delivery_yoy_pct",),
    ),
    (
        "Google Trends YoY % — takeout vs PeerSSSIndex",
        ("takeout_yoy_pct",),
    ),
    (
        "Google Trends YoY % — healthy fast food vs PeerSSSIndex",
        ("healthy_fast_food_yoy_pct",),
    ),
    (
        "Google Trends YoY % — salad near me vs PeerSSSIndex",
        ("salad_near_me_yoy_pct",),
    ),
    (
        "Google Trends YoY % — cheap eats vs PeerSSSIndex",
        ("cheap_eats_yoy_pct",),
    ),
    (
        "Google Trends YoY % — dollar menu vs PeerSSSIndex",
        ("dollar_menu_yoy_pct",),
    ),
    # Health / weight / at-home (extra pulls for testing)
    (
        "Google Trends YoY % — microwavable meals vs PeerSSSIndex",
        ("microwavable_meals_yoy_pct",),
    ),
    (
        "Google Trends YoY % — weight loss vs PeerSSSIndex",
        ("weight_loss_yoy_pct",),
    ),
    (
        "Google Trends YoY % — glp1 vs PeerSSSIndex",
        ("glp1_yoy_pct",),
    ),
    (
        "Google Trends YoY % — how to lose weight vs PeerSSSIndex",
        ("how_to_lose_weight_yoy_pct",),
    ),
    (
        "Google Trends YoY % — healthy food vs PeerSSSIndex",
        ("healthy_food_yoy_pct",),
    ),
    # Peer-set brands + benchmarks
    (
        "Google Trends YoY % — Chipotle vs PeerSSSIndex",
        ("chipotle_yoy_pct",),
    ),
    (
        "Google Trends YoY % — CAVA vs PeerSSSIndex",
        ("cava_yoy_pct",),
    ),
    (
        "Google Trends YoY % — Sweetgreen vs PeerSSSIndex",
        ("sweetgreen_yoy_pct",),
    ),
    (
        "Google Trends YoY % — Shake Shack vs PeerSSSIndex",
        ("shake_shack_yoy_pct",),
    ),
    (
        "Google Trends YoY % — Panera vs PeerSSSIndex",
        ("panera_bread_yoy_pct",),
    ),
    (
        "Google Trends YoY % — Jersey Mike's vs PeerSSSIndex",
        ("jersey_mikes_subs_yoy_pct",),
    ),
    (
        "Google Trends YoY % — McDonald's (benchmark) vs PeerSSSIndex",
        ("mcdonalds_yoy_pct",),
    ),
    # Levels (0–100 vs each term’s own peak in the pull window)
    (
        "Google Trends — Chipotle level vs PeerSSSIndex",
        ("chipotle",),
    ),
    (
        "Google Trends — CAVA level vs PeerSSSIndex",
        ("cava",),
    ),
    (
        "Google Trends — Sweetgreen level vs PeerSSSIndex",
        ("sweetgreen",),
    ),
    (
        "Google Trends — Shake Shack level vs PeerSSSIndex",
        ("shake_shack",),
    ),
    (
        "Google Trends — Panera level vs PeerSSSIndex",
        ("panera_bread",),
    ),
    (
        "Google Trends — Recipe level vs PeerSSSIndex",
        ("recipe",),
    ),
    (
        "Google Trends — food near me level vs PeerSSSIndex",
        ("food_near_me",),
    ),
    (
        "Google Trends — restaurants near me level vs PeerSSSIndex",
        ("restaurants_near_me",),
    ),
    (
        "Google Trends — delivery level vs PeerSSSIndex",
        ("delivery",),
    ),
    (
        "Google Trends — takeout level vs PeerSSSIndex",
        ("takeout",),
    ),
    (
        "Google Trends — microwavable meals level vs PeerSSSIndex",
        ("microwavable_meals",),
    ),
    (
        "Google Trends — weight loss level vs PeerSSSIndex",
        ("weight_loss",),
    ),
    (
        "Google Trends — glp1 level vs PeerSSSIndex",
        ("glp1",),
    ),
    (
        "Google Trends — how to lose weight level vs PeerSSSIndex",
        ("how_to_lose_weight",),
    ),
    (
        "Google Trends — healthy food level vs PeerSSSIndex",
        ("healthy_food",),
    ),
)


def monthly_macro_with_index(bundle: dict) -> pd.DataFrame:
    m = bundle["macro"]["monthly"]
    if m.empty:
        return pd.DataFrame()
    out = m.reset_index()
    if "month_end" not in out.columns and len(out.columns):
        out = out.rename(columns={out.columns[0]: "month_end"})
    out["month_end"] = pd.to_datetime(out["month_end"], errors="coerce")
    return out.sort_values("month_end")


def filter_recent_months(df: pd.DataFrame, years: int) -> pd.DataFrame:
    if df.empty or "month_end" not in df.columns:
        return df
    end = pd.to_datetime(df["month_end"], errors="coerce").max()
    if pd.isna(end):
        return df
    start = end - pd.DateOffset(years=years)
    return df[pd.to_datetime(df["month_end"], errors="coerce") >= start]


def peer_sss_by_month_end(feat_m: pd.DataFrame) -> pd.DataFrame:
    """One calendar ``month_end`` per row; ``PeerSSSIndex`` median across tickers."""
    if feat_m.empty or "PeerSSSIndex" not in feat_m.columns or "macro_month_end_join" not in feat_m.columns:
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    g = (
        feat_m.dropna(subset=["PeerSSSIndex", "macro_month_end_join"])
        .groupby("macro_month_end_join", as_index=False)["PeerSSSIndex"]
        .median()
    )
    g["month_end"] = pd.to_datetime(g["macro_month_end_join"], errors="coerce").dt.normalize()
    return g.drop(columns=["macro_month_end_join"], errors="ignore")


def _calendar_quarter_label_to_month_end(lab: object) -> pd.Timestamp:
    """Map ``YYYYQ[1-4]`` (Gregorian ``Q-DEC``) to that quarter's calendar **month-end** date."""
    s = str(lab).strip()
    m = re.match(r"^(\d{4})Q([1-4])$", s)
    if not m:
        return pd.NaT
    y, q = int(m.group(1)), int(m.group(2))
    per = pd.Period(year=y, quarter=q, freq="Q-DEC")
    return pd.Timestamp(per.to_timestamp(how="end")).normalize()


def peer_sss_by_calendar_quarter_end_from_wide(
    brand_period_wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
) -> pd.DataFrame:
    """One row per **Gregorian calendar quarter**; ``month_end`` = quarter-end (Mar/Jun/Sep/Dec).

    Aligns each fiscal row to ``macro_calendar_quarter_join`` from ``Prd_End`` (same rule as
    :func:`analytic_panel.fiscal_dates_macro_join_keys`), then **median** ``PeerSSSIndex`` across
    tickers within that quarter. Avoids duplicate intra-quarter months when different peers'
    ``Prd_End`` fall in adjacent calendar months (e.g. June vs July) for the same quarter.
    """
    if (
        brand_period_wide.empty
        or fiscal_dates.empty
        or "PeerSSSIndex" not in brand_period_wide.columns
    ):
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    need = ("Ticker", "Prd_Nm", "PeerSSSIndex")
    if any(c not in brand_period_wide.columns for c in need):
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    base = brand_period_wide[list(need)].copy()
    keys = analytic_panel.fiscal_dates_macro_join_keys(fiscal_dates)
    if keys.empty or "macro_calendar_quarter_join" not in keys.columns:
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    merged = base.merge(keys, on=["Ticker", "Prd_Nm"], how="inner", validate="m:1")
    if merged.empty:
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    g = (
        merged.dropna(subset=["PeerSSSIndex", "macro_calendar_quarter_join"])
        .groupby("macro_calendar_quarter_join", as_index=False)["PeerSSSIndex"]
        .median()
    )
    g["month_end"] = g["macro_calendar_quarter_join"].map(_calendar_quarter_label_to_month_end)
    out = g.dropna(subset=["month_end"]).drop(columns=["macro_calendar_quarter_join"], errors="ignore")
    return out[["month_end", "PeerSSSIndex"]].sort_values("month_end", kind="mergesort").reset_index(drop=True)


def peer_pricing_by_calendar_quarter_end_from_wide(
    brand_period_wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
) -> pd.DataFrame:
    """Like :func:`peer_sss_by_calendar_quarter_end_from_wide` but for ``PeerPricingIndex`` (peer ticket ppt)."""
    if (
        brand_period_wide.empty
        or fiscal_dates.empty
        or "PeerPricingIndex" not in brand_period_wide.columns
    ):
        return pd.DataFrame(columns=["month_end", "PeerPricingIndex"])
    need = ("Ticker", "Prd_Nm", "PeerPricingIndex")
    if any(c not in brand_period_wide.columns for c in need):
        return pd.DataFrame(columns=["month_end", "PeerPricingIndex"])
    base = brand_period_wide[list(need)].copy()
    keys = analytic_panel.fiscal_dates_macro_join_keys(fiscal_dates)
    if keys.empty or "macro_calendar_quarter_join" not in keys.columns:
        return pd.DataFrame(columns=["month_end", "PeerPricingIndex"])
    merged = base.merge(keys, on=["Ticker", "Prd_Nm"], how="inner", validate="m:1")
    if merged.empty:
        return pd.DataFrame(columns=["month_end", "PeerPricingIndex"])
    g = (
        merged.dropna(subset=["PeerPricingIndex", "macro_calendar_quarter_join"])
        .groupby("macro_calendar_quarter_join", as_index=False)["PeerPricingIndex"]
        .median()
    )
    g["month_end"] = g["macro_calendar_quarter_join"].map(_calendar_quarter_label_to_month_end)
    out = g.dropna(subset=["month_end"]).drop(columns=["macro_calendar_quarter_join"], errors="ignore")
    return out[["month_end", "PeerPricingIndex"]].sort_values("month_end", kind="mergesort").reset_index(drop=True)


def peer_traffic_by_calendar_quarter_end_from_wide(
    brand_period_wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
) -> pd.DataFrame:
    """Like :func:`peer_pricing_by_calendar_quarter_end_from_wide` but for ``PeerTrafficIndex`` (peer traffic ppt)."""
    if (
        brand_period_wide.empty
        or fiscal_dates.empty
        or "PeerTrafficIndex" not in brand_period_wide.columns
    ):
        return pd.DataFrame(columns=["month_end", "PeerTrafficIndex"])
    need = ("Ticker", "Prd_Nm", "PeerTrafficIndex")
    if any(c not in brand_period_wide.columns for c in need):
        return pd.DataFrame(columns=["month_end", "PeerTrafficIndex"])
    base = brand_period_wide[list(need)].copy()
    keys = analytic_panel.fiscal_dates_macro_join_keys(fiscal_dates)
    if keys.empty or "macro_calendar_quarter_join" not in keys.columns:
        return pd.DataFrame(columns=["month_end", "PeerTrafficIndex"])
    merged = base.merge(keys, on=["Ticker", "Prd_Nm"], how="inner", validate="m:1")
    if merged.empty:
        return pd.DataFrame(columns=["month_end", "PeerTrafficIndex"])
    g = (
        merged.dropna(subset=["PeerTrafficIndex", "macro_calendar_quarter_join"])
        .groupby("macro_calendar_quarter_join", as_index=False)["PeerTrafficIndex"]
        .median()
    )
    g["month_end"] = g["macro_calendar_quarter_join"].map(_calendar_quarter_label_to_month_end)
    out = g.dropna(subset=["month_end"]).drop(columns=["macro_calendar_quarter_join"], errors="ignore")
    return out[["month_end", "PeerTrafficIndex"]].sort_values("month_end", kind="mergesort").reset_index(drop=True)


def peer_sss_by_month_end_from_wide(
    brand_period_wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
) -> pd.DataFrame:
    """Same output shape as :func:`peer_sss_by_month_end` without the full fiscal×macro monthly join.

    Uses only ``PeerSSSIndex`` plus ``FiscalDates`` **month** keys (``macro_month_end_join``).
    Prefer :func:`peer_sss_by_calendar_quarter_end_from_wide` when peer should be **one point per
    calendar quarter** (e.g. macro YoY chart), not one per ``Prd_End`` calendar month.
    """
    if (
        brand_period_wide.empty
        or fiscal_dates.empty
        or "PeerSSSIndex" not in brand_period_wide.columns
    ):
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    need = ("Ticker", "Prd_Nm", "PeerSSSIndex")
    if any(c not in brand_period_wide.columns for c in need):
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    base = brand_period_wide[list(need)].copy()
    keys = analytic_panel.fiscal_dates_macro_month_join_keys(fiscal_dates)
    if keys.empty or "macro_month_end_join" not in keys.columns:
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    merged = base.merge(keys, on=["Ticker", "Prd_Nm"], how="inner", validate="m:1")
    if merged.empty:
        return pd.DataFrame(columns=["month_end", "PeerSSSIndex"])
    g = (
        merged.dropna(subset=["PeerSSSIndex", "macro_month_end_join"])
        .groupby("macro_month_end_join", as_index=False)["PeerSSSIndex"]
        .median()
    )
    g["month_end"] = pd.to_datetime(g["macro_month_end_join"], errors="coerce").dt.normalize()
    return g.drop(columns=["macro_month_end_join"], errors="ignore")


def merge_peer_on_monthly(df: pd.DataFrame, peer_by_m: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if peer_by_m.empty:
        out = df.copy()
        out["PeerSSSIndex"] = pd.NA
        return out
    return df.merge(peer_by_m, on="month_end", how="left")


def merge_gtrends_by_calendar_month(work: pd.DataFrame, gt: pd.DataFrame) -> pd.DataFrame:
    """Left-join **all** Google Trends CSV columns (except ``month``) onto ``work`` (YYYY-MM ↔ ``month_end``)."""
    if work.empty or gt.empty or "month_end" not in work.columns or "month" not in gt.columns:
        return work
    out = work.copy()
    cols = [c for c in gt.columns if c != "month"]
    if not cols:
        return out
    sub = gt[["month", *cols]].copy()
    sub["_per"] = pd.to_datetime(sub["month"], format="%Y-%m", errors="coerce").dt.to_period("M")
    sub = sub.drop(columns=["month"], errors="ignore").drop_duplicates(subset=["_per"])
    out["_per"] = pd.to_datetime(out["month_end"], errors="coerce").dt.to_period("M")
    merged = out.merge(sub, on="_per", how="left")
    merged = merged.drop(columns=["_per"], errors="ignore")
    prev = merged.attrs or {}
    merged.attrs = {**prev, "gtrends_cols": tuple(c for c in cols if c in merged.columns)}
    return merged


def add_recipe_yoy_inverted(df: pd.DataFrame) -> pd.DataFrame:
    """``recipe_yoy_pct_inv = -recipe_yoy_pct`` (same sign convention as inverted composite drivers)."""
    if df.empty or "recipe_yoy_pct" not in df.columns:
        return df
    out = df.copy()
    out[RECIPE_YOY_INVERTED_COL] = -pd.to_numeric(out["recipe_yoy_pct"], errors="coerce")
    prev = dict(out.attrs) if getattr(out, "attrs", None) else {}
    gc = list(prev.get("gtrends_cols", ()))
    if RECIPE_YOY_INVERTED_COL not in gc:
        gc.append(RECIPE_YOY_INVERTED_COL)
    prev["gtrends_cols"] = tuple(dict.fromkeys(gc))
    out.attrs = prev
    return out


def is_recipe_yoy_inverted_raw_spec(gt_cols: Sequence[str]) -> bool:
    """True for the dual-series Recipe YoY block (inverted + raw)."""
    return frozenset(gt_cols) == _RECIPE_YOY_INVERTED_RAW_COLS


def recipe_inv_ma_fwd1q_column(window: int) -> str:
    """Column name for inverted-recipe YoY MA shifted one quarter along ``month_end`` (lag experiment)."""
    return f"{RECIPE_YOY_INVERTED_COL}_ma{int(window)}_fwd1q"


def add_recipe_inv_ma_forward_one_quarter(df: pd.DataFrame, *, window: int) -> pd.DataFrame:
    """Shift ``{RECIPE_YOY_INVERTED_COL}_ma{window}`` one quarter to the right on the calendar.

    After sorting by ``month_end``, each row gets the moving-average value from ``window`` months
    earlier (``shift(window)``), so the line lines up with peer SSS if peer lags recipe by one quarter.
    """
    base = f"{RECIPE_YOY_INVERTED_COL}_ma{int(window)}"
    col_out = recipe_inv_ma_fwd1q_column(window)
    if df.empty or base not in df.columns or "month_end" not in df.columns:
        return df
    out = df.copy()
    s = out.sort_values("month_end", kind="mergesort")
    out[col_out] = s[base].shift(int(window))
    return out


def append_gtrends_trailing_moving_avg(
    df: pd.DataFrame,
    base_cols: Iterable[str],
    *,
    window: int,
    month_end_col: str = "month_end",
) -> pd.DataFrame:
    """Sort by ``month_end``; add ``{col}_ma{window}`` trailing rolling mean (``min_periods=1``)."""
    if df.empty or window <= 1:
        return df
    if month_end_col not in df.columns:
        return df
    out = df.sort_values(month_end_col).copy()
    for col in base_cols:
        if col not in out.columns:
            continue
        out[f"{col}_ma{window}"] = (
            pd.to_numeric(out[col], errors="coerce").rolling(window=window, min_periods=1).mean()
        )
    return out


def append_gtrends_ma_yoy12(
    df: pd.DataFrame,
    ma_columns: Sequence[str],
    *,
    month_end_col: str = "month_end",
) -> pd.DataFrame:
    """For each ``*_maN`` (or other smoothed) column, add ``{col}_yoy12_pct`` = 12-month % change on that series.

    Uses the same calendar ordering as :func:`append_gtrends_trailing_moving_avg` (sort by ``month_end``).
    """
    if df.empty or month_end_col not in df.columns:
        return df
    out = df.sort_values(month_end_col, kind="mergesort").copy()
    for c in ma_columns:
        cc = str(c)
        if cc not in out.columns:
            continue
        ycol = f"{cc}_yoy12_pct"
        s = pd.to_numeric(out[cc], errors="coerce")
        out[ycol] = s.pct_change(periods=12) * 100.0
    return out


def fuzzy_column(df: pd.DataFrame, tokens: tuple[str, ...]) -> str | None:
    for c in df.columns:
        lc = str(c).lower()
        if all(t in lc for t in tokens):
            return str(c)
    return None


def resolve_y_columns(df: pd.DataFrame, preferred: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for name in preferred:
        if name in df.columns and name not in seen:
            out.append(name)
            seen.add(name)
            continue
        f: str | None = None
        if "722513" in name:
            if "employment" in name:
                f = fuzzy_column(df, ("722513", "employment"))
            elif "earning" in name or "hourly" in name:
                f = fuzzy_column(df, ("722513", "earning"))
        if f and f not in seen:
            out.append(f)
            seen.add(f)
    return out


def quarter_label_sort_key(s: object) -> int:
    m = re.match(r"^(\d{4})Q([1-4])$", str(s).strip())
    if not m:
        return 0
    return int(m.group(1)) * 10 + int(m.group(2))


def line_chart_with_peer(
    df: pd.DataFrame,
    title: str,
    y_cols: list[str],
    *,
    x: str = "month_end",
    temporal_x: bool = True,
    height: int = 280,
    left_axis_title: str = "Macro (left)",
) -> None:
    st.subheader(title)
    peer_col = PEER_COL
    if df.empty or x not in df.columns:
        st.caption("No data.")
        return
    work = df.copy()
    if temporal_x:
        work[x] = pd.to_datetime(work[x], errors="coerce")
    else:
        work[x] = work[x].astype(str).str.strip()
    have = resolve_y_columns(work, y_cols)
    if not have:
        st.caption(f"No columns matched: {', '.join(y_cols)}")
        return

    plot_cols = [x, *have]
    if peer_col in work.columns:
        plot_cols.append(peer_col)
    plot = work[[c for c in plot_cols if c in work.columns]].copy()
    for c in have:
        plot[c] = pd.to_numeric(plot[c], errors="coerce")
    long = plot[[x, *have]].melt(id_vars=x, var_name="metric", value_name="value")
    long = long.dropna(subset=["value"])
    if long.empty:
        st.warning(
            f"No numeric points to plot for **{title}** — columns {have} are all NaN in the **current** "
            f"time window. **Widen the slider** or check data load."
        )
        return

    peer_df: pd.DataFrame | None = None
    if peer_col in plot.columns:
        p2 = plot[[x, peer_col]].copy()
        p2[peer_col] = pd.to_numeric(p2[peer_col], errors="coerce")
        p2 = p2.dropna(subset=[peer_col])
        if not p2.empty:
            peer_df = p2

    if alt is None:
        for c in have:
            one = plot[[x, c]].dropna(subset=[c])
            if not one.empty:
                st.caption(c)
                st.line_chart(one, x=x, y=c, height=max(160, height // max(len(have), 1)))
        if peer_df is not None and not peer_df.empty:
            st.caption(f"{peer_col} (ppt) — dual-axis needs Altair")
            st.line_chart(peer_df, x=x, y=peer_col, height=max(140, height // 2))
        return

    if temporal_x:
        x_enc_macro = alt.X(f"{x}:T", title="Month-end")
        x_enc_peer = alt.X(f"{x}:T")
        x_tt = alt.Tooltip(x, title="date", format="%Y-%m-%d")
    else:
        x_order = sorted(plot[x].astype(str).unique(), key=quarter_label_sort_key)
        x_enc_macro = alt.X(f"{x}:N", title="Quarter", sort=x_order)
        x_enc_peer = alt.X(f"{x}:N", sort=x_order)
        x_tt = alt.Tooltip(x, title="quarter")

    left = (
        alt.Chart(long)
        .mark_line()
        .encode(
            x=x_enc_macro,
            y=alt.Y(
                "value:Q",
                axis=alt.Axis(title=left_axis_title),
                scale=alt.Scale(zero=False),
            ),
            color=alt.Color(
                "metric:N",
                title="Series",
                legend=alt.Legend(labelLimit=200, symbolLimit=80),
            ),
            tooltip=[x_tt, "metric", alt.Tooltip("value:Q", format=",.3f")],
        )
    )

    if peer_df is None:
        chart = left.properties(height=height)
        st.altair_chart(chart, use_container_width=True)
        return

    right = (
        alt.Chart(peer_df)
        .mark_line(strokeDash=[5, 3], strokeWidth=2, color="#b83b5e")
        .encode(
            x=x_enc_peer,
            y=alt.Y(
                f"{peer_col}:Q",
                axis=alt.Axis(title="PeerSSSIndex (ppt, right)", orient="right"),
                scale=alt.Scale(zero=False),
            ),
            tooltip=[x_tt, alt.Tooltip(f"{peer_col}:Q", title=peer_col, format=",.2f")],
        )
    )
    chart = (left + right).resolve_scale(y="independent").properties(height=height)
    st.altair_chart(chart, use_container_width=True)


def corr_r2_mape_xy(
    x: np.ndarray,
    y: np.ndarray,
    *,
    min_n: int = 5,
) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    n = int(x.size)
    if n < min_n:
        return (float("nan"), float("nan"), float("nan"))
    if np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return (float("nan"), float("nan"), float("nan"))
    r = float(np.corrcoef(x, y)[0, 1])
    xm, ym = float(x.mean()), float(y.mean())
    var_x = float(((x - xm) ** 2).sum())
    if var_x < 1e-12:
        return (float("nan"), float("nan"), float("nan"))
    beta = float(((x - xm) * (y - ym)).sum() / var_x)
    alpha = float(ym - beta * xm)
    yhat = alpha + beta * x
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - ym) ** 2).sum())
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else float("nan")
    eps = 1e-6
    denom = np.maximum(np.abs(y), eps)
    mape = float(np.mean(np.abs(y - yhat) / denom) * 100.0)
    return (r, r2, mape)


def peer_stats_window_caption(work_stats: pd.DataFrame, x_col: str, slider_years: int) -> str:
    if work_stats.empty:
        return f"slider **{slider_years}** yr — no rows"
    n = len(work_stats)
    if x_col == "month_end":
        dt = pd.to_datetime(work_stats[x_col], errors="coerce").dropna()
        if dt.empty:
            return f"n = {n} · slider **{slider_years}** yr"
        return (
            f"n = **{n}** · **{pd.Timestamp(dt.min()):%Y-%m}** … **{pd.Timestamp(dt.max()):%Y-%m}** "
            f"· slider **{slider_years}** yr"
        )
    qs = sorted(work_stats[x_col].astype(str).unique(), key=quarter_label_sort_key)
    if not qs:
        return f"n = {n} · slider **{slider_years}** yr"
    return f"n = **{n}** · **{qs[0]}** … **{qs[-1]}** · slider **{slider_years}** yr"


def render_peer_vs_macro_stats(
    work_stats: pd.DataFrame,
    macro_base_cols: tuple[str, ...] | Sequence[str],
    *,
    peer_col: str = PEER_COL,
    slider_years: int | None = None,
    x_col: str = "month_end",
    feature_label: str = "macro",
    caption_suffix: str | None = None,
) -> None:
    win = (
        peer_stats_window_caption(work_stats, x_col, int(slider_years))
        if slider_years is not None
        else ""
    )
    suf = f" {caption_suffix}" if caption_suffix else ""
    st.caption(
        f"**{peer_col} vs {feature_label}** — Pearson **r**, OLS **R²** ({peer_col} ~ {feature_label} + intercept), "
        f"**MAPE %** (≥5 overlapping points). Stats use **only the slider window**: {win}.{suf}"
    )
    if work_stats.empty:
        st.caption("No rows in slider window.")
        return
    if peer_col not in work_stats.columns:
        st.caption(f"`{peer_col}` missing from merged macro frame.")
        return
    y_peer = pd.to_numeric(work_stats[peer_col], errors="coerce").to_numpy(dtype=float)
    rows: list[dict[str, float | int | str]] = []
    for base in macro_base_cols:
        b = str(base)
        if b not in work_stats.columns:
            rows.append(
                {
                    "metric": b,
                    "r": float("nan"),
                    "R2": float("nan"),
                    "MAPE_pct": float("nan"),
                    "n": 0,
                    "note": f"{feature_label} column missing",
                }
            )
            continue
        xv = pd.to_numeric(work_stats[b], errors="coerce").to_numpy(dtype=float)
        r, r2, mape = corr_r2_mape_xy(xv, y_peer)
        nn = int(np.sum(np.isfinite(xv) & np.isfinite(y_peer)))
        rows.append(
            {
                "metric": b,
                "r": r,
                "R2": r2,
                "MAPE_pct": mape,
                "n": nn,
                "note": "",
            }
        )
    out = pd.DataFrame(rows)
    show = out.drop(columns=["note"], errors="ignore")
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        column_config={
            "metric": st.column_config.TextColumn(feature_label),
            "r": st.column_config.NumberColumn("r", format="%.3f"),
            "R2": st.column_config.NumberColumn("R²", format="%.3f"),
            "MAPE_pct": st.column_config.NumberColumn("MAPE %", format="%.1f"),
            "n": st.column_config.NumberColumn("n", format="%d"),
        },
    )
    miss = out[out["note"].fillna("").astype(str).str.len() > 0]
    if not miss.empty:
        st.caption(", ".join(f"`{r['metric']}`: {r['note']}" for _, r in miss.iterrows()))


def gtrends_numeric_base_columns(df: pd.DataFrame) -> list[str]:
    """Columns from the Trends merge that may receive a trailing moving average (levels + YoY % + index Δ)."""
    tagged = df.attrs.get("gtrends_cols")
    if isinstance(tagged, (list, tuple)) and tagged:
        return [str(c) for c in tagged if c in df.columns]
    # Fallback if ``attrs`` was lost (e.g. some copies): infer YoY + headline series.
    out: list[str] = []
    for c in df.columns:
        s = str(c)
        if s.endswith("_yoy_pct") or s in ("fast_casual_index", "fast_casual_index_yoy_chg"):
            out.append(s)
    return out
