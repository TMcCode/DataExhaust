"""Upload / download a gzip+pickle **dashboard bundle** on Google Cloud Storage.

Use for fast Streamlit cold starts when hosted: build once (Sheets + FRED), upload to ``gs://…``,
then set ``MLP_GCS_SNAPSHOT_URI`` so the app loads the snapshot instead of live APIs.

Requires ``google-cloud-storage``. Credentials: same service-account JSON as Sheets
(``GOOGLE_SHEETS_CREDENTIALS`` / ``GOOGLE_APPLICATION_CREDENTIALS``) must include **Storage**
scopes on the bucket (often a separate key or extra IAM role vs Sheets-only keys).
"""

from __future__ import annotations

import gzip
import io
import os
import pickle
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_GCS_SCOPES_RO = ("https://www.googleapis.com/auth/devstorage.read_only",)
_GCS_SCOPES_RW = ("https://www.googleapis.com/auth/devstorage.read_write",)


def parse_gs_uri(uri: str) -> tuple[str, str]:
    u = str(uri).strip()
    p = urlparse(u)
    if p.scheme != "gs":
        raise ValueError(f"Expected gs:// URI, got: {uri!r}")
    bucket = (p.netloc or "").strip()
    path = (p.path or "").lstrip("/")
    if not bucket:
        raise ValueError(f"Invalid GCS URI (empty bucket): {uri!r}")
    return bucket, path


def _storage_client(*, write: bool = False):
    from google.cloud import storage
    from google.oauth2.service_account import Credentials

    scopes = _GCS_SCOPES_RW if write else _GCS_SCOPES_RO
    p = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if p and Path(p).is_file():
        creds = Credentials.from_service_account_file(str(p), scopes=scopes)
        return storage.Client(credentials=creds, project=creds.project_id)
    return storage.Client()


def upload_bundle_gzip_pickle(bundle: dict[str, Any], gs_uri: str, *, compresslevel: int = 6) -> None:
    """Pickle ``bundle`` (gzip) to ``gs_uri`` (``gs://bucket/path/file.pkl.gz``)."""
    bucket_name, blob_path = parse_gs_uri(gs_uri)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=compresslevel) as gz:
        pickle.dump(bundle, gz, protocol=pickle.HIGHEST_PROTOCOL)
    data = buf.getvalue()
    client = _storage_client(write=True)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(data, content_type="application/gzip")


def download_bundle_gzip_pickle(gs_uri: str) -> dict[str, Any] | None:
    """Return unpickled bundle, or ``None`` if missing / unreadable / wrong shape."""
    try:
        bucket_name, blob_path = parse_gs_uri(gs_uri)
    except ValueError:
        return None
    try:
        client = _storage_client(write=False)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        if not blob.exists():
            return None
        raw = blob.download_as_bytes()
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gz:
            obj = pickle.load(gz)
        if not isinstance(obj, dict):
            return None
        return obj
    except ImportError:
        return None
    except Exception:
        return None


def load_bundle_from_local_path(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Read a gzip+pickle bundle from a local file. Returns ``None`` on any failure.

    Used as the offline-dev / zero-credential fallback by
    :func:`streamlit_dashboard.data_loader.load_dashboard_data`; bundle shape must match
    what :func:`upload_bundle_gzip_pickle` produced.
    """
    p = Path(path).expanduser()
    if not p.is_file():
        return None
    try:
        with gzip.open(p, "rb") as gz:
            obj = pickle.load(gz)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj
