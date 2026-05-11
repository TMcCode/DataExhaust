"""Monthly commodity benchmarks from analyst-pasted USDA-style tables (CSV), no Quick Stats API.

Each source can be supplied via an env var pointing at a local path or ``gs://...`` URI:

- ``MLP_BROILERS_CSV`` — broiler/turkey $/lb monthly
- ``MLP_BEEF_CSV`` — beef cattle categories $/cwt monthly

When unset, falls back to CSVs colocated with this module:

- ``broilers_turkeys_monthly_paste.csv``
- ``beef_cattle_prices_received_monthly_paste.csv``

Missing sources emit a warning and omit those columns; macro still loads without them.
"""

from __future__ import annotations

import io
import os
import warnings
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

_POULTRY_FILENAME = "broilers_turkeys_monthly_paste.csv"
_BEEF_FILENAME = "beef_cattle_prices_received_monthly_paste.csv"

_POULTRY_ENV_VAR = "MLP_BROILERS_CSV"
_BEEF_ENV_VAR = "MLP_BEEF_CSV"

_POULTRY_RENAME = {
    "broilers_usd_per_lb": "commodity_broilers_price_received_usd_per_lb_monthly_paste",
    "turkeys_usd_per_lb": "commodity_turkeys_price_received_usd_per_lb_monthly_paste",
}

_BEEF_RENAME = {
    "all_beef_cattle_price_received_usd_per_cwt": (
        "commodity_all_beef_cattle_price_received_usd_per_cwt_monthly_paste"
    ),
    "calves_price_received_usd_per_cwt": "commodity_calves_price_received_usd_per_cwt_monthly_paste",
    "cows_price_received_usd_per_cwt": "commodity_cows_price_received_usd_per_cwt_monthly_paste",
    "steers_and_heifers_price_received_usd_per_cwt": (
        "commodity_steers_and_heifers_price_received_usd_per_cwt_monthly_paste"
    ),
}


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


def _resolve_source(env_var: str, default_filename: str) -> tuple[str, bool]:
    """Return ``(uri_or_path, is_env_override)``."""
    env_uri = os.environ.get(env_var, "").strip()
    if env_uri:
        return env_uri, True
    return str(_repo_root() / default_filename), False


def _load_commodity_frame(
    uri: str, rename: dict[str, str], source_label: str
) -> pd.DataFrame | None:
    df = _read_csv_any(uri)
    if df.empty:
        warnings.warn(
            f"Commodity paste source unavailable ({source_label} -> {uri}) — "
            "skipping those columns. Set MLP_BROILERS_CSV / MLP_BEEF_CSV to override.",
            stacklevel=3,
        )
        return None
    if "calendar_month_end" not in df.columns:
        warnings.warn(
            f"{source_label}: no calendar_month_end column — skipped.", stacklevel=3
        )
        return None
    drop_cols = {"year", "month", "calendar_month_end"}
    cols = [c for c in df.columns if c not in drop_cols]
    raw_ix = pd.to_datetime(df["calendar_month_end"]).dt.normalize()
    # Use ndarray values so pandas does not re-align Series onto the DatetimeIndex.
    out = pd.DataFrame(
        {c: pd.to_numeric(df[c], errors="coerce").to_numpy() for c in cols},
        index=pd.DatetimeIndex(raw_ix, name="month_end"),
        dtype="float64",
    )
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    return out.sort_index()


def load_commodity_paste_monthly_dataframe() -> pd.DataFrame:
    """Wide monthly panel keyed by normalized month-end. Empty when no usable CSVs."""
    chunks: list[pd.DataFrame] = []

    poultry_uri, _ = _resolve_source(_POULTRY_ENV_VAR, _POULTRY_FILENAME)
    p = _load_commodity_frame(poultry_uri, _POULTRY_RENAME, _POULTRY_FILENAME)
    if p is not None and not p.empty:
        chunks.append(p)

    beef_uri, _ = _resolve_source(_BEEF_ENV_VAR, _BEEF_FILENAME)
    b = _load_commodity_frame(beef_uri, _BEEF_RENAME, _BEEF_FILENAME)
    if b is not None and not b.empty:
        chunks.append(b)

    if not chunks:
        return pd.DataFrame()

    out = chunks[0]
    for c in chunks[1:]:
        out = out.join(c, how="outer")
    out = out.sort_index()
    return out.astype("float64")


def probe_commodity_csvs() -> int:
    """Print whether paste sources are reachable and row counts."""
    sources = (
        (_POULTRY_ENV_VAR, _POULTRY_FILENAME),
        (_BEEF_ENV_VAR, _BEEF_FILENAME),
    )
    for env_var, fn in sources:
        uri, from_env = _resolve_source(env_var, fn)
        tag = f"{env_var}={uri}" if from_env else uri
        df = _read_csv_any(uri)
        if df.empty:
            print(f"MISSING {tag}")
        else:
            print(f"OK {tag} (~{len(df)} rows)")
    df = load_commodity_paste_monthly_dataframe()
    if df.empty:
        print("Merged commodity frame is empty.")
        return 1
    print("Merged columns:", list(df.columns))
    print(df.tail(2))
    return 0
