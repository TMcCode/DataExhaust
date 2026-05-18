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
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

import feature_panel
import macro_data
import mlp_gcs_snapshot
import sheets_client

# Dashboard default: enough history for ~15y charts without pulling full FRED history from 2000.
_STREAMLIT_DEFAULT_MACRO_START = "2010-01-01"

# Local snapshot bundle shipped with the repo (offline-dev / zero-credential fallback).
# Same gzip+pickle shape as the GCS snapshot; refreshed by
# `python load_mlp_master.py --gcs-snapshot-uri ... && python scripts/download_snapshot.py`
# (or simply copying from GCS). Loaded after GCS but before live API fall-through.
_LOCAL_SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "snapshots" / "mlp_dashboard_bundle.pkl.gz"
)


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


def _try_local_snapshot() -> dict[str, Any] | None:
    """Return the repo-bundled snapshot if present, else ``None``.

    Lets ``streamlit run app.py`` work with zero credentials by serving the frozen
    bundle in ``data/snapshots/`` when neither GCS nor live APIs are reachable.
    """
    return mlp_gcs_snapshot.load_bundle_from_local_path(_LOCAL_SNAPSHOT_PATH)


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


def _strip_feature_tables_if_unwanted(
    snap: dict[str, Any], include_feature_tables: bool
) -> dict[str, Any]:
    if include_feature_tables:
        return snap
    out = dict(snap)
    out["feature_tables"] = {}
    return out


def _local_snapshot_mtime() -> float:
    """File mtime for cache invalidation when the repo snapshot is refreshed."""
    try:
        return _LOCAL_SNAPSHOT_PATH.stat().st_mtime
    except OSError:
        return -1.0


def dataframe_revision(df: pd.DataFrame | None) -> str:
    """Lightweight fingerprint for ``st.cache_data`` keys built from panel frames."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return "empty"
    return f"{df.shape}_{pd.util.hash_pandas_object(df, index=True).sum()}"


@st.cache_data(ttl=3600, show_spinner="Loading dashboard snapshot (GCS)…")
def _cached_gcs_snapshot_bundle(gcs_snapshot_uri: str) -> dict[str, Any]:
    snap = mlp_gcs_snapshot.download_bundle_gzip_pickle(gcs_snapshot_uri)
    if snap is None:
        raise ValueError(f"GCS snapshot missing or unreadable: {gcs_snapshot_uri}")
    return snap


@st.cache_data(ttl=3600, show_spinner="Loading dashboard snapshot (local)…")
def _cached_local_snapshot_bundle(local_snapshot_mtime: float) -> dict[str, Any]:
    del local_snapshot_mtime  # cache key only — file reread when mtime changes
    snap = _try_local_snapshot()
    if snap is None:
        raise ValueError(f"Local snapshot missing: {_LOCAL_SNAPSHOT_PATH}")
    return snap


def _load_dashboard_data_uncached(
    spreadsheet_id_blank_means_default: str | None,
    macro_observation_start: str,
    include_commodity_csvs: bool,
    gcs_snapshot_uri: str | None = None,
    *,
    include_feature_tables: bool = True,
) -> dict[str, Any]:
    """Return workbook + macro + wide panel; optionally the fiscal×macro joined tables.

    Resolution order:

    1. **GCS snapshot** — if ``gcs_snapshot_uri`` is set, try downloading the
       gzip+pickle bundle (fast cold start when credentials are available).
    2. **Local snapshot** — fall back to ``data/snapshots/mlp_dashboard_bundle.pkl.gz``
       shipped with the repo so a zero-credential clone still renders the dashboard.
    3. **Live APIs** — last-resort path that rebuilds the bundle from Sheets + FRED +
       alt-data CSVs (requires the relevant API keys / service-account JSON).

    Sub-loads in step 3 are cached separately so a page that sets
    ``include_feature_tables=False`` still warms the workbook/macro caches for other pages.
    """
    if gcs_snapshot_uri and str(gcs_snapshot_uri).strip():
        snap = mlp_gcs_snapshot.download_bundle_gzip_pickle(str(gcs_snapshot_uri).strip())
        if snap is not None:
            return _strip_feature_tables_if_unwanted(snap, include_feature_tables)

    local_snap = _try_local_snapshot()
    if local_snap is not None:
        return _strip_feature_tables_if_unwanted(local_snap, include_feature_tables)

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


@st.cache_data(ttl=3600, show_spinner="Loading dashboard data…")
def _cached_load_dashboard_data(
    spreadsheet_id_blank_means_default: str,
    macro_observation_start: str,
    include_commodity_csvs: bool,
    gcs_snapshot_uri: str,
    local_snapshot_mtime: float,
    include_feature_tables: bool,
) -> dict[str, Any]:
    """Cached wrapper: snapshot paths avoid repeated GCS download + unpickle on every rerun."""
    uri = (gcs_snapshot_uri or "").strip()
    if uri:
        try:
            snap = _cached_gcs_snapshot_bundle(uri)
            return _strip_feature_tables_if_unwanted(snap, include_feature_tables)
        except ValueError:
            pass

    if _LOCAL_SNAPSHOT_PATH.is_file():
        try:
            snap = _cached_local_snapshot_bundle(_local_snapshot_mtime())
            return _strip_feature_tables_if_unwanted(snap, include_feature_tables)
        except ValueError:
            pass

    return _load_dashboard_data_uncached(
        spreadsheet_id_blank_means_default or None,
        macro_observation_start,
        include_commodity_csvs,
        gcs_snapshot_uri=uri or None,
        include_feature_tables=include_feature_tables,
    )


def load_dashboard_data(
    spreadsheet_id_blank_means_default: str | None,
    macro_observation_start: str,
    include_commodity_csvs: bool,
    gcs_snapshot_uri: str | None = None,
    *,
    include_feature_tables: bool = True,
) -> dict[str, Any]:
    return _cached_load_dashboard_data(
        spreadsheet_id_blank_means_default or "",
        macro_observation_start,
        include_commodity_csvs,
        gcs_snapshot_uri or "",
        _local_snapshot_mtime(),
        include_feature_tables,
    )


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
