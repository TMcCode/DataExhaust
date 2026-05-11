"""MTA NYC subway — Manhattan entry swipes aggregated to calendar month (open data).

Source: data.ny.gov Socrata resources (hourly rows; we query ``sum(ridership)`` per month).
``ridership`` counts **entries** (MetroCard / OMNY) at each station complex; we filter
``borough = Manhattan`` and ``transit_mode = subway``.

Datasets (non-overlapping periods)::

    2017-01-13 — 2019-12-31  ``t69i-h2me``
    2020-01-01 — 2024-12-31  ``wujg-7c2s``
    2025-01-01 — present      ``5wq4-mkjj``

Optional env ``DATA_NY_GOV_APP_TOKEN`` (or ``SOCRATA_APP_TOKEN``): Socrata app token for
higher rate limits — not required.

**Macro / app load:** set ``MTA_MANHATTAN_SUBWAY_MONTHLY_CSV`` to a local path or ``gs://bucket/path.csv``
(same credentials pattern as Sheets: ``GOOGLE_APPLICATION_CREDENTIALS`` or ``GOOGLE_SHEETS_CREDENTIALS``).
If unset, ``<repo>/data/mta_manhattan_subway_monthly.csv`` is used when present.

Cache file (CSV): columns ``month_end`` and ``mta_manhattan_subway_entries_monthly_sum``.

**Update workflow:** (1) If the CSV is **missing**, ``--refresh`` does a **one-time** full backfill
from ``--first`` through the last complete calendar month. (2) On later runs, ``--refresh`` **only**
fetches months after the latest ``month_end`` already stored (append + merge). (3) ``--full`` forces
a complete re-download. Optional: ``--refresh --upload-gcs gs://bucket/path.csv`` writes local
``--output`` then uploads.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

_DEFAULT_FILENAME = "mta_manhattan_subway_monthly.csv"
_SOCRATA_BASE = "https://data.ny.gov/resource"
# (resource_id, first_timestamp_inclusive, last_timestamp_inclusive)
_RESOURCES: tuple[tuple[str, str, str], ...] = (
    ("t69i-h2me", "2017-01-13T00:00:00.000", "2019-12-31T23:59:59.999"),
    ("wujg-7c2s", "2020-01-01T00:00:00.000", "2024-12-31T23:59:59.999"),
    ("5wq4-mkjj", "2025-01-01T00:00:00.000", "2099-12-31T23:59:59.999"),
)

MTA_MONTHLY_ENTRIES_COLUMN = "mta_manhattan_subway_entries_monthly_sum"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def default_monthly_csv_path() -> Path:
    return _repo_root() / "data" / _DEFAULT_FILENAME


def mta_monthly_csv_uri_from_env() -> str | None:
    """``MTA_MANHATTAN_SUBWAY_MONTHLY_CSV`` if set (local path or ``gs://...``)."""
    v = os.environ.get("MTA_MANHATTAN_SUBWAY_MONTHLY_CSV", "").strip()
    return v or None


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
        raw = blob.download_as_bytes()
        return pd.read_csv(io.BytesIO(raw))
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


def _upload_csv_to_gcs(local_csv: Path, gs_uri: str) -> None:
    from google.cloud import storage
    from google.oauth2.service_account import Credentials

    u = str(gs_uri).strip()
    pr = urlparse(u)
    if pr.scheme != "gs":
        raise ValueError(f"Expected gs:// URI, got {gs_uri!r}")
    bucket_name = (pr.netloc or "").strip()
    blob_path = (pr.path or "").lstrip("/")
    if not bucket_name:
        raise ValueError(f"Invalid GCS URI: {gs_uri!r}")
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
        "GOOGLE_SHEETS_CREDENTIALS"
    )
    if cred_path and Path(cred_path).is_file():
        creds = Credentials.from_service_account_file(
            str(cred_path),
            scopes=("https://www.googleapis.com/auth/devstorage.read_write",),
        )
        client = storage.Client(credentials=creds, project=creds.project_id)
    else:
        client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(str(local_csv), content_type="text/csv")


def _socrata_app_token() -> str | None:
    for k in ("DATA_NY_GOV_APP_TOKEN", "SOCRATA_APP_TOKEN"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    return None


def _resource_for_month(month_start: pd.Timestamp) -> str | None:
    """Return Socrata resource id whose published range overlaps this calendar month."""
    ms = month_start.normalize().replace(day=1)
    me = ms + pd.offsets.MonthEnd(0)
    for rid, lo, hi in _RESOURCES:
        lo_ts = pd.Timestamp(lo).normalize()
        hi_ts = pd.Timestamp(hi).normalize()
        if me >= lo_ts and ms <= hi_ts:
            return rid
    return None


def _month_starts(first: pd.Timestamp, last: pd.Timestamp) -> list[pd.Timestamp]:
    out: list[pd.Timestamp] = []
    cur = pd.Timestamp(first).normalize().replace(day=1)
    end = pd.Timestamp(last).normalize().replace(day=1)
    while cur <= end:
        out.append(cur)
        cur = cur + pd.offsets.MonthBegin(1)
    return out


def _fetch_month_sum(
    resource_id: str,
    month_start: pd.Timestamp,
    *,
    app_token: str | None,
    timeout_s: float = 120.0,
) -> float:
    month_start = month_start.normalize().replace(day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)
    nxt = month_start + pd.offsets.MonthBegin(1)
    lo = month_start.strftime("%Y-%m-%dT00:00:00.000")
    hi = nxt.strftime("%Y-%m-%dT00:00:00.000")
    where = (
        f"transit_timestamp >= '{lo}' AND transit_timestamp < '{hi}' "
        "AND borough = 'Manhattan' AND transit_mode = 'subway'"
    )
    params = {"$select": "sum(ridership) as total", "$where": where}
    q = urllib.parse.urlencode(params)
    url = f"{_SOCRATA_BASE}/{resource_id}.json?{q}"
    headers = {"User-Agent": "MLP_Restaurant_CaseStudy/mta_manhattan_subway (pandas)"}
    if app_token:
        headers["X-App-Token"] = app_token
    req = urllib.request.Request(url, headers=headers, method="GET")
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8")
            rows = json.loads(raw)
            if not rows or rows[0].get("total") in (None, ""):
                return float("nan")
            return float(rows[0]["total"])
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Socrata request failed after retries: {url!r}: {last_err!r}") from last_err


def fetch_monthly_totals_dataframe(
    *,
    first_month: str = "2017-01-01",
    last_month: str | None = None,
    app_token: str | None = None,
    progress: bool = False,
) -> pd.DataFrame:
    """Return one row per calendar month with ``month_end`` and ``MTA_MONTHLY_ENTRIES_COLUMN``."""
    if last_month is None:
        # Exclude the in-progress calendar month (partial MTA publish / incomplete swipes).
        last_month = (
            pd.Timestamp.today().normalize().replace(day=1) - pd.Timedelta(days=1)
        ).strftime("%Y-%m-%d")
    starts = _month_starts(pd.Timestamp(first_month), pd.Timestamp(last_month))
    rows: list[dict[str, object]] = []
    token = app_token if app_token is not None else _socrata_app_token()
    for ms in starts:
        rid = _resource_for_month(ms)
        if rid is None:
            continue
        total = _fetch_month_sum(rid, ms, app_token=token)
        me = ms + pd.offsets.MonthEnd(0)
        rows.append({"month_end": me.normalize(), MTA_MONTHLY_ENTRIES_COLUMN: total})
        if progress:
            print(f"{me.date()} {rid} -> {total:,.0f}")
    if not rows:
        return pd.DataFrame(columns=["month_end", MTA_MONTHLY_ENTRIES_COLUMN])
    out = pd.DataFrame(rows)
    out["month_end"] = pd.to_datetime(out["month_end"]).dt.normalize()
    return out.sort_values("month_end").reset_index(drop=True)


def _normalize_monthly_df(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or "month_end" not in raw.columns or MTA_MONTHLY_ENTRIES_COLUMN not in raw.columns:
        return pd.DataFrame(columns=["month_end", MTA_MONTHLY_ENTRIES_COLUMN])
    df = raw.copy()
    df["month_end"] = pd.to_datetime(df["month_end"], errors="coerce").dt.normalize()
    df[MTA_MONTHLY_ENTRIES_COLUMN] = pd.to_numeric(df[MTA_MONTHLY_ENTRIES_COLUMN], errors="coerce")
    return df.dropna(subset=["month_end"]).sort_values("month_end").reset_index(drop=True)


def load_monthly_dataframe(path: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    """Read cached CSV from a local path, ``gs://...``, or env :func:`mta_monthly_csv_uri_from_env`."""
    if path is not None and str(path).strip():
        return _normalize_monthly_df(_read_csv_any(str(path).strip()))
    env_uri = mta_monthly_csv_uri_from_env()
    if env_uri:
        return _normalize_monthly_df(_read_csv_any(env_uri))
    p = default_monthly_csv_path()
    if not p.is_file():
        return pd.DataFrame(columns=["month_end", MTA_MONTHLY_ENTRIES_COLUMN])
    return _normalize_monthly_df(pd.read_csv(p))


def merge_monthly_history(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    """Stack frames; same ``month_end`` keeps the **new** row (revisions / re-pull)."""
    a = _normalize_monthly_df(existing)
    b = _normalize_monthly_df(new_rows)
    if a.empty:
        return b
    if b.empty:
        return a
    out = pd.concat([a, b], ignore_index=True)
    out = out.sort_values("month_end").drop_duplicates(subset=["month_end"], keep="last")
    return out.reset_index(drop=True)


def _last_complete_calendar_month_end() -> pd.Timestamp:
    return pd.Timestamp(
        pd.Timestamp.today().normalize().replace(day=1) - pd.Timedelta(days=1)
    ).normalize()


def _cap_last_month_end(last_month: str | None, *, default_cap: pd.Timestamp) -> pd.Timestamp:
    """Upper bound for fetches: min(default_cap, month-end of ``last_month`` if given)."""
    if last_month is None or not str(last_month).strip():
        return default_cap
    t = pd.Timestamp(str(last_month).strip()).normalize()
    user_end = (t + pd.offsets.MonthEnd(0)).normalize()
    return min(default_cap, user_end)


def refresh_monthly_cache_merged(
    *,
    existing: pd.DataFrame,
    full: bool = False,
    first_month_if_empty: str = "2017-01-01",
    last_month: str | None = None,
    app_token: str | None = None,
    progress: bool = False,
) -> pd.DataFrame:
    """Return merged monthly frame after fetching new rows from Socrata (incremental unless ``full``)."""
    last_me = _cap_last_month_end(last_month, default_cap=_last_complete_calendar_month_end())

    if full:
        return fetch_monthly_totals_dataframe(
            first_month=first_month_if_empty,
            last_month=last_me.strftime("%Y-%m-%d"),
            app_token=app_token,
            progress=progress,
        )

    base = _normalize_monthly_df(existing)
    if base.empty:
        return fetch_monthly_totals_dataframe(
            first_month=first_month_if_empty,
            last_month=last_me.strftime("%Y-%m-%d"),
            app_token=app_token,
            progress=progress,
        )

    have_max = base["month_end"].max()
    if pd.isna(have_max):
        return fetch_monthly_totals_dataframe(
            first_month=first_month_if_empty,
            last_month=last_me.strftime("%Y-%m-%d"),
            app_token=app_token,
            progress=progress,
        )

    start_next = (pd.Timestamp(have_max).normalize() + pd.offsets.MonthBegin(1)).normalize()
    if start_next > last_me:
        if progress:
            print(f"No new complete months (cache ends {have_max.date()}, last complete {last_me.date()}).")
        return base

    new_part = fetch_monthly_totals_dataframe(
        first_month=start_next.strftime("%Y-%m-%d"),
        last_month=last_me.strftime("%Y-%m-%d"),
        app_token=app_token,
        progress=progress,
    )
    return merge_monthly_history(base, new_part)


def monthly_series_for_macro_join(
    path: str | os.PathLike[str] | None = None,
) -> pd.Series:
    """``Series`` indexed by month-end ``Timestamp`` (name = ``MTA_MONTHLY_ENTRIES_COLUMN``).

    ``path`` overrides env + default; pass ``path`` explicitly from :mod:`macro_data` when set.
    """
    df = load_monthly_dataframe(path)
    if df.empty:
        return pd.Series(dtype="float64", name=MTA_MONTHLY_ENTRIES_COLUMN)
    s = pd.Series(
        df[MTA_MONTHLY_ENTRIES_COLUMN].values,
        index=pd.DatetimeIndex(df["month_end"]),
        name=MTA_MONTHLY_ENTRIES_COLUMN,
    )
    return s.sort_index().astype("float64")


def write_monthly_cache(
    df: pd.DataFrame,
    path: str | os.PathLike[str] | None = None,
) -> Path:
    p = Path(path).expanduser().resolve() if path is not None else default_monthly_csv_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return p


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Build MTA Manhattan subway monthly entry cache.")
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch from data.ny.gov, merge into cache (incremental unless --full)",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="With --refresh: rebuild entire range (--first through last complete month)",
    )
    ap.add_argument(
        "--input",
        type=str,
        default=None,
        help="Existing CSV to merge from (local or gs://). Default: --output if it exists, else MTA_MANHATTAN_SUBWAY_MONTHLY_CSV",
    )
    ap.add_argument(
        "--output",
        type=str,
        default=None,
        help=f"Local CSV path to write (default: {default_monthly_csv_path()})",
    )
    ap.add_argument(
        "--upload-gcs",
        type=str,
        default=None,
        help="After writing --output, upload the file to this gs:// URI (needs Storage write IAM)",
    )
    ap.add_argument("--first", type=str, default="2017-01-01", help="With --full: first month (YYYY-MM-01)")
    ap.add_argument("--last", type=str, default=None, help="Override last month fetched (default: last complete)")
    args = ap.parse_args()
    out_path = Path(args.output).expanduser().resolve() if args.output else default_monthly_csv_path()

    if args.refresh:
        existing = pd.DataFrame()
        if args.input:
            existing = _normalize_monthly_df(_read_csv_any(args.input.strip()))
        elif out_path.is_file():
            existing = _normalize_monthly_df(pd.read_csv(out_path))
        else:
            env_uri = mta_monthly_csv_uri_from_env()
            if env_uri and not str(env_uri).startswith("gs://") and Path(env_uri).is_file():
                existing = _normalize_monthly_df(pd.read_csv(Path(env_uri).expanduser()))
            elif env_uri and str(env_uri).startswith("gs://"):
                existing = _normalize_monthly_df(_read_csv_from_gcs(env_uri))

        df = refresh_monthly_cache_merged(
            existing=existing,
            full=bool(args.full),
            first_month_if_empty=args.first,
            last_month=args.last,
            progress=True,
        )
        written = write_monthly_cache(df, out_path)
        print(f"Wrote {len(df)} rows -> {written}")
        if args.upload_gcs:
            uri = str(args.upload_gcs).strip()
            _upload_csv_to_gcs(written, uri)
            print(f"Uploaded -> {uri}")
        return 0

    inspect_path = out_path
    if args.input:
        df = _normalize_monthly_df(_read_csv_any(args.input.strip()))
        print(f"Cache (from --input): {len(df)} rows")
    else:
        df = load_monthly_dataframe(str(inspect_path) if inspect_path.is_file() else None)
        print(f"Cache {inspect_path}: {len(df)} rows (use --refresh to update)")
    if not df.empty:
        print(df.tail(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
