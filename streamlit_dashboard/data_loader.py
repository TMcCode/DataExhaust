"""Cached loads for the dashboard.

Defaults when no sidebar widgets exist: macro from **2010-01-01** (smaller FRED payloads than 2000;
set ``st.session_state["macro_start"] = "2000-01-01"`` if you need full history), default workbook ID,
commodity CSVs on. Optional session keys ``macro_start``, ``spreadsheet_id``, ``include_commodity_csvs``
override loads.

Heavy joins are split into ``st.cache_data`` layers so pages can reuse workbook + macro pulls without
re-running the fiscal×macro wide merge when they do not need ``feature_tables``.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st

import feature_panel
import macro_data
import mlp_gcs_snapshot
import sheets_client

# Dashboard default: enough history for ~15y charts without pulling full FRED history from 2000.
_STREAMLIT_DEFAULT_MACRO_START = "2010-01-01"


def _gcs_snapshot_uri() -> str | None:
    v = os.environ.get("MLP_GCS_SNAPSHOT_URI")
    if isinstance(v, str) and v.strip():
        return v.strip()
    try:
        if hasattr(st, "secrets") and "MLP_GCS_SNAPSHOT_URI" in st.secrets:
            u = st.secrets["MLP_GCS_SNAPSHOT_URI"]
            if u is not None and str(u).strip():
                return str(u).strip()
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner="Loading Google Sheets workbook…")
def _cached_mlp_sheets(spreadsheet_id_blank_means_default: str) -> dict[str, Any]:
    sid = (spreadsheet_id_blank_means_default or "").strip() or None
    return sheets_client.load_mlp_fast_casual_dataframes(sid)


@st.cache_data(ttl=3600, show_spinner="Loading macro (FRED, BLS, commodities)…")
def _cached_macro_frames(macro_observation_start: str, include_commodity_csvs: bool) -> dict[str, Any]:
    return macro_data.load_macro_dataframes(
        macro_observation_start,
        include_commodity_csvs=include_commodity_csvs,
    )


@st.cache_data(ttl=3600, show_spinner="Building brand × quarter wide panel…")
def _cached_brand_period_wide(spreadsheet_id_blank_means_default: str) -> pd.DataFrame:
    sid = (spreadsheet_id_blank_means_default or "").strip() or None
    dfs = _cached_mlp_sheets(spreadsheet_id_blank_means_default)
    return sheets_client.build_mlp_brand_period_wide_df(sid, dfs=dfs)


@st.cache_data(ttl=3600, show_spinner="Joining macro to workbook (fiscal × calendar month)…")
def _cached_feature_tables(
    spreadsheet_id_blank_means_default: str,
    macro_observation_start: str,
    include_commodity_csvs: bool,
) -> dict[str, pd.DataFrame]:
    wide = _cached_brand_period_wide(spreadsheet_id_blank_means_default)
    dfs = _cached_mlp_sheets(spreadsheet_id_blank_means_default)
    macro = _cached_macro_frames(macro_observation_start, include_commodity_csvs)
    return feature_panel.build_macro_joined_panels(wide, dfs["fiscal_dates"], macro)


def load_dashboard_data(
    spreadsheet_id_blank_means_default: str | None,
    macro_observation_start: str,
    include_commodity_csvs: bool,
    gcs_snapshot_uri: str | None = None,
    *,
    include_feature_tables: bool = True,
) -> dict[str, Any]:
    """Return workbook + macro + wide panel; optionally the fiscal×macro joined tables.

    If ``gcs_snapshot_uri`` is set (``gs://bucket/path.pkl.gz``), try loading that gzip+pickle bundle
    first (fast on hosted runs); on failure falls back to live Sheets + FRED.

    Sub-loads are cached separately so a page that sets ``include_feature_tables=False`` still warms
    the workbook/macro caches for other pages.
    """
    if gcs_snapshot_uri and str(gcs_snapshot_uri).strip():
        snap = mlp_gcs_snapshot.download_bundle_gzip_pickle(str(gcs_snapshot_uri).strip())
        if snap is not None:
            if not include_feature_tables:
                out = dict(snap)
                out["feature_tables"] = {}
                return out
            return snap

    sid_key = spreadsheet_id_blank_means_default or ""
    dfs = _cached_mlp_sheets(sid_key)
    macro = _cached_macro_frames(macro_observation_start, include_commodity_csvs)
    brand_wide = _cached_brand_period_wide(sid_key)
    feature_tables: dict[str, pd.DataFrame] = {}
    if include_feature_tables:
        feature_tables = _cached_feature_tables(sid_key, macro_observation_start, include_commodity_csvs)
    return {
        "mlp_sheets": dfs,
        "macro": macro,
        "brand_period_wide": brand_wide,
        "feature_tables": feature_tables,
    }


def get_dashboard_bundle_or_stop(*, include_feature_tables: bool = True) -> dict[str, Any]:
    """Load using session overrides if present, otherwise repo defaults."""
    start = str(st.session_state.get("macro_start") or _STREAMLIT_DEFAULT_MACRO_START)
    sid = st.session_state.get("spreadsheet_id")
    if isinstance(sid, str):
        sid = sid.strip() or None
    elif sid is not None:
        sid = str(sid).strip() or None
    include_comm = bool(st.session_state.get("include_commodity_csvs", True))
    snap_uri = _gcs_snapshot_uri()
    try:
        return load_dashboard_data(
            sid or "",
            start,
            include_comm,
            gcs_snapshot_uri=snap_uri,
            include_feature_tables=include_feature_tables,
        )
    except FileNotFoundError as e:
        st.error(
            f"**Google credentials:** {e}\n\n"
            "Configure Google Sheets credentials for this deployment (service account JSON or "
            "`GOOGLE_SHEETS_CREDENTIALS` path)."
        )
        st.stop()
    except Exception as e:
        st.error(f"**Data load failed:** `{type(e).__name__}` — {e}")
        st.stop()
