"""Reproducible **fiscal-wide × national macro / brand signal** joins for modeling.

Grain of every table here: **one row per** ``(Ticker, Prd_Nm)`` from
:func:`sheets_client.build_mlp_brand_period_wide_df`. Macro is **calendar**-based
(FRED / BLS monthly; resampled calendar quarters). Join keys are derived from workbook
``FiscalDates`` **``Prd_End``**:

- **Monthly macro** — ``macro_month_end_join`` = calendar month-end of the month containing
  ``Prd_End`` (:func:`analytic_panel.join_wide_with_calendar_macro_monthly`).
- **Calendar-quarter macro** — ``macro_calendar_quarter_join`` = ``YYYYQk`` of ``Prd_End``
  (:func:`analytic_panel.join_wide_with_calendar_macro_quarterly`).

Notebook::

    from load_mlp_master import load_all_mlp_data
    from feature_panel import build_macro_joined_panels

    bundle = load_all_mlp_data()
    tables = build_macro_joined_panels(
        bundle["brand_period_wide"],
        bundle["mlp_sheets"]["fiscal_dates"],
        bundle["macro"],
    )
    month_df = tables["fiscal_wide_x_macro_calendar_month"]
    q_df = tables["fiscal_wide_x_macro_calendar_quarter"]
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd

import analytic_panel

_GDELT_DEFAULT_LONG_CSV = "data/gdelt_fast_casual_monthly_long.csv"
_GDELT_LONG_ENV_VAR = "MLP_GDELT_LONG_CSV"
_GDELT_MONTHLY_PREFIX = "gdelt_m_"
_GDELT_QUARTER_PREFIX = "gdelt_cq_"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _read_csv_from_gcs(gs_uri: str) -> pd.DataFrame:
    try:
        from google.cloud import storage
        from google.oauth2.service_account import Credentials
    except ImportError:
        return pd.DataFrame()

    p = urlparse(str(gs_uri).strip())
    if p.scheme != "gs":
        return pd.DataFrame()
    bucket_name = (p.netloc or "").strip()
    blob_path = (p.path or "").lstrip("/")
    if not bucket_name:
        return pd.DataFrame()
    try:
        key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
            "GOOGLE_SHEETS_CREDENTIALS"
        )
        if key and Path(key).is_file():
            creds = Credentials.from_service_account_file(
                str(key),
                scopes=("https://www.googleapis.com/auth/devstorage.read_only",),
            )
            client = storage.Client(credentials=creds, project=creds.project_id)
        else:
            client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        if not blob.exists():
            return pd.DataFrame()
        return pd.read_csv(io.BytesIO(blob.download_as_bytes()))
    except Exception:
        return pd.DataFrame()


def _read_csv_any(uri_or_path: str) -> pd.DataFrame:
    s = str(uri_or_path).strip()
    if not s:
        return pd.DataFrame()
    if s.startswith("gs://"):
        return _read_csv_from_gcs(s)
    p = Path(s).expanduser()
    if not p.is_file():
        return pd.DataFrame()
    return pd.read_csv(p)


def load_gdelt_monthly_long(path: str | Path | None = None) -> pd.DataFrame:
    """Load brand-month GDELT metrics keyed by ``Ticker`` and calendar month-end.

    Source resolution order: explicit ``path`` arg > ``MLP_GDELT_LONG_CSV`` env var
    (local path or ``gs://...`` URI) > ``data/gdelt_fast_casual_monthly_long.csv`` next
    to this module. Returns an empty frame when none are reachable.
    """
    if path is not None and str(path).strip():
        raw = _read_csv_any(str(path).strip())
    else:
        env_uri = os.environ.get(_GDELT_LONG_ENV_VAR, "").strip()
        if env_uri:
            raw = _read_csv_any(env_uri)
        else:
            raw = _read_csv_any(str(_repo_root() / _GDELT_DEFAULT_LONG_CSV))
    if raw.empty:
        return pd.DataFrame()
    required = {"month", "ticker"}
    if not required.issubset(raw.columns):
        return pd.DataFrame()
    df = raw.copy()
    df["Ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["gdelt_month_end"] = (
        pd.to_datetime(df["month"], format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)
    ).dt.normalize()
    metric_cols = [
        c
        for c in (
            "gdelt_article_count",
            "gdelt_total_article_count",
            "gdelt_article_share_per_100k",
            "gdelt_avg_tone",
        )
        if c in df.columns
    ]
    for c in metric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    keep = ["Ticker", "gdelt_month_end", *metric_cols]
    return (
        df[keep]
        .dropna(subset=["Ticker", "gdelt_month_end"])
        .sort_values(["Ticker", "gdelt_month_end"])
        .drop_duplicates(subset=["Ticker", "gdelt_month_end"], keep="last")
        .reset_index(drop=True)
    )


def _prefix_feature_columns(df: pd.DataFrame, *, prefix: str, keys: set[str]) -> pd.DataFrame:
    ren = {c: f"{prefix}{c}" for c in df.columns if c not in keys}
    return df.rename(columns=ren)


def add_gdelt_to_monthly_feature_panel(
    monthly_panel: pd.DataFrame,
    gdelt_monthly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join brand-month GDELT metrics to fiscal rows using ``Ticker`` + ``macro_month_end_join``."""
    if monthly_panel.empty:
        return monthly_panel
    if "Ticker" not in monthly_panel.columns or "macro_month_end_join" not in monthly_panel.columns:
        return monthly_panel
    g = gdelt_monthly if gdelt_monthly is not None else load_gdelt_monthly_long()
    if g is None or g.empty:
        return monthly_panel
    right = _prefix_feature_columns(g, prefix=_GDELT_MONTHLY_PREFIX, keys={"Ticker", "gdelt_month_end"})
    out = monthly_panel.copy()
    out["macro_month_end_join"] = pd.to_datetime(
        out["macro_month_end_join"], errors="coerce"
    ).dt.normalize()
    return out.merge(
        right,
        left_on=["Ticker", "macro_month_end_join"],
        right_on=["Ticker", "gdelt_month_end"],
        how="left",
    ).drop(columns=["gdelt_month_end"], errors="ignore")


def gdelt_calendar_quarter_features(gdelt_monthly: pd.DataFrame | None = None) -> pd.DataFrame:
    """Aggregate brand-month GDELT metrics to ticker × calendar quarter.

    Article counts and total GDELT article denominators are summed. Article share is recomputed from
    those quarterly sums. Tone, when present, is article-count weighted.
    """
    g = gdelt_monthly if gdelt_monthly is not None else load_gdelt_monthly_long()
    if g is None or g.empty:
        return pd.DataFrame()
    df = g.copy()
    if "gdelt_month_end" not in df.columns or "Ticker" not in df.columns:
        return pd.DataFrame()
    df["calendar_quarter"] = pd.to_datetime(df["gdelt_month_end"], errors="coerce").map(
        analytic_panel.calendar_quarter_label_from_datetime
    )
    rows: list[dict[str, object]] = []
    for (ticker, cq), part in df.dropna(subset=["calendar_quarter"]).groupby(
        ["Ticker", "calendar_quarter"], sort=True
    ):
        article = pd.to_numeric(part.get("gdelt_article_count"), errors="coerce").fillna(0.0)
        total = pd.to_numeric(part.get("gdelt_total_article_count"), errors="coerce")
        article_sum = float(article.sum())
        total_sum = float(total.sum(skipna=True))
        row: dict[str, object] = {
            "Ticker": ticker,
            "calendar_quarter": cq,
            "gdelt_article_count": article_sum,
            "gdelt_total_article_count": total_sum if np.isfinite(total_sum) else np.nan,
            "gdelt_article_share_per_100k": (
                article_sum / total_sum * 100000.0 if total_sum > 0 else np.nan
            ),
        }
        if "gdelt_avg_tone" in part.columns:
            tone = pd.to_numeric(part["gdelt_avg_tone"], errors="coerce")
            weights = article.where(tone.notna(), 0.0)
            denom = float(weights.sum())
            row["gdelt_avg_tone"] = (
                float((tone.fillna(0.0) * weights).sum() / denom)
                if denom > 0
                else float(tone.mean(skipna=True))
            )
        rows.append(row)
    out = pd.DataFrame(rows).sort_values(["Ticker", "calendar_quarter"]).reset_index(drop=True)
    if out.empty:
        return out
    for c in ("gdelt_article_count", "gdelt_article_share_per_100k"):
        out[f"{c}_yoy_pct"] = out.groupby("Ticker", sort=False)[c].pct_change(
            periods=4, fill_method=None
        ) * 100.0
    return out


def add_gdelt_to_quarterly_feature_panel(
    quarterly_panel: pd.DataFrame,
    gdelt_monthly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join ticker-quarter GDELT metrics using ``Ticker`` + ``macro_calendar_quarter_join``."""
    if quarterly_panel.empty:
        return quarterly_panel
    if "Ticker" not in quarterly_panel.columns or "macro_calendar_quarter_join" not in quarterly_panel.columns:
        return quarterly_panel
    gq = gdelt_calendar_quarter_features(gdelt_monthly)
    if gq.empty:
        return quarterly_panel
    right = _prefix_feature_columns(
        gq, prefix=_GDELT_QUARTER_PREFIX, keys={"Ticker", "calendar_quarter"}
    )
    return quarterly_panel.merge(
        right,
        left_on=["Ticker", "macro_calendar_quarter_join"],
        right_on=["Ticker", "calendar_quarter"],
        how="left",
    ).drop(columns=["calendar_quarter"], errors="ignore")


def build_macro_joined_panels(
    brand_period_wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
    macro: dict[str, Any],
    *,
    include_gdelt: bool = True,
    gdelt_monthly: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Return two left-joined panels (month macro + quarter macro), same fiscal row grain."""
    if "monthly" not in macro or "calendar_quarter" not in macro:
        raise KeyError('macro must contain "monthly" and "calendar_quarter" DataFrames')

    monthly = analytic_panel.join_wide_with_calendar_macro_monthly(
        brand_period_wide,
        fiscal_dates,
        macro["monthly"],
    )
    quarterly = analytic_panel.join_wide_with_calendar_macro_quarterly(
        brand_period_wide,
        fiscal_dates,
        macro["calendar_quarter"],
    )

    if include_gdelt:
        gdelt = gdelt_monthly if gdelt_monthly is not None else load_gdelt_monthly_long()
        monthly = add_gdelt_to_monthly_feature_panel(monthly, gdelt)
        quarterly = add_gdelt_to_quarterly_feature_panel(quarterly, gdelt)

    return {
        "fiscal_wide_x_macro_calendar_month": monthly,
        "fiscal_wide_x_macro_calendar_quarter": quarterly,
    }


def export_macro_joined_panel_csvs(
    tables: dict[str, pd.DataFrame],
    directory: str | Path | None = None,
    *,
    monthly_filename: str = "mlp_feature_fiscal_x_macro_monthly.csv",
    quarter_filename: str = "mlp_feature_fiscal_x_macro_calendar_quarter.csv",
) -> dict[str, Path]:
    """Write :func:`build_macro_joined_panels` outputs next to this repo (or ``directory``)."""
    root = Path(directory).expanduser().resolve() if directory else Path(__file__).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "fiscal_wide_x_macro_calendar_month": root / monthly_filename,
        "fiscal_wide_x_macro_calendar_quarter": root / quarter_filename,
    }
    for key, path in paths.items():
        if key not in tables:
            raise KeyError(f"tables missing {key!r}")
        tables[key].to_csv(path, index=False)
    return paths
