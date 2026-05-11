"""Load pre-built Google Trends monthly CSV from the repo (see ``gtrends_monthly_brands.py``)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

DEFAULT_GTRENDS_CSV = "gtrends_fast_casual_monthly.csv"


def gtrends_csv_path() -> Path:
    """``MLP_GTRENDS_CSV`` env / ``st.secrets``, else ``<repo root>/gtrends_fast_casual_monthly.csv``."""
    env = os.environ.get("MLP_GTRENDS_CSV")
    if isinstance(env, str) and env.strip():
        return Path(env.strip()).expanduser()
    try:
        import streamlit as st  # local import — module also used outside Streamlit

        if hasattr(st, "secrets") and "MLP_GTRENDS_CSV" in st.secrets:
            v = st.secrets["MLP_GTRENDS_CSV"]
            if v is not None and str(v).strip():
                return Path(str(v).strip()).expanduser()
    except Exception:
        pass
    root = Path(__file__).resolve().parent.parent
    return root / DEFAULT_GTRENDS_CSV


def _append_gtrends_uri_from_env() -> str | None:
    v = os.environ.get("MLP_GTRENDS_APPEND_CSV")
    if isinstance(v, str) and v.strip():
        return v.strip()
    try:
        import streamlit as st

        if hasattr(st, "secrets") and "MLP_GTRENDS_APPEND_CSV" in st.secrets:
            s = st.secrets["MLP_GTRENDS_APPEND_CSV"]
            if s is not None and str(s).strip():
                return str(s).strip()
    except Exception:
        pass
    return None


def _read_csv_from_gcs(gs_uri: str) -> pd.DataFrame:
    try:
        from google.cloud import storage
        from google.oauth2.service_account import Credentials
    except ImportError:
        return pd.DataFrame()

    u = str(gs_uri).strip()
    p = urlparse(u)
    if p.scheme != "gs":
        return pd.DataFrame()
    bucket_name = (p.netloc or "").strip()
    blob_path = (p.path or "").lstrip("/")
    if not bucket_name:
        return pd.DataFrame()
    try:
        key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
        if key and Path(key).is_file():
            creds = Credentials.from_service_account_file(
                str(key), scopes=("https://www.googleapis.com/auth/devstorage.read_only",)
            )
            client = storage.Client(credentials=creds, project=creds.project_id)
        else:
            client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        if not blob.exists():
            return pd.DataFrame()
        raw = blob.download_as_bytes()
        return pd.read_csv(io.BytesIO(raw))
    except Exception:
        return pd.DataFrame()


def _read_gtrends_csv_any(uri_or_path: str) -> pd.DataFrame:
    s = str(uri_or_path).strip()
    if not s:
        return pd.DataFrame()
    if s.startswith("gs://"):
        return _read_csv_from_gcs(s)
    p = Path(s).expanduser()
    if not p.is_file():
        return pd.DataFrame()
    return pd.read_csv(p)


def _merge_gtrends_monthly_frames(primary: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """Concatenate on ``month``; overlapping months keep the **primary** (newer) row."""
    if extra.empty:
        return primary
    if primary.empty:
        return extra
    if "month" not in primary.columns or "month" not in extra.columns:
        return primary
    out = pd.concat([extra, primary], ignore_index=True)
    return out.sort_values("month").drop_duplicates(subset=["month"], keep="last")


def load_gtrends_monthly_csv(path: Path | None = None) -> pd.DataFrame:
    """Return CSV rows or an empty frame if the file is missing / invalid.

    If ``MLP_GTRENDS_APPEND_CSV`` is set (env or ``st.secrets``) to a **local path** or ``gs://…/file.csv``,
    that table is concatenated with the primary CSV on ``month`` (duplicates keep the primary file’s row).
    Use this to stitch **archived** Trends history (e.g. from GCS) in front of a recent pull.
    """
    path = path or gtrends_csv_path()
    if not path.is_file():
        primary = pd.DataFrame()
    else:
        primary = pd.read_csv(path)
        if "month" not in primary.columns:
            return pd.DataFrame()

    append_uri = _append_gtrends_uri_from_env()
    if not append_uri:
        return primary

    extra = _read_gtrends_csv_any(append_uri)
    if extra.empty or "month" not in extra.columns:
        return primary

    return _merge_gtrends_monthly_frames(primary, extra)
