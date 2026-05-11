"""BART — SF financial district origin trips from published monthly OD workbooks.

BART posts **Excel** ridership matrices (not the schedule API at api.bart.gov). We download
those files from ``bart.gov``, open the **Total Trips** sheet, and sum all OD cells whose
**entry (origin) station** is one of the four downtown SF stations (Embarcadero, Montgomery,
Powell, Civic Center — two-letter codes ``EM``, ``MT``, ``PL``, ``CC``). That is the closest
public analog to “activity starting in the SF CBD” on BART.

**History:** workbooks before **2018-02** only have weekday/sat/sun averages (no monthly total
matrix); those months are skipped. **2017** zip files use the old layout only — omitted.

Cache: ``data/bart_sf_ridership_monthly.csv`` (or env ``BART_SF_RIDERSHIP_MONTHLY_CSV`` as local
path or ``gs://...``).

**Update workflow (same idea as MTA cache):**

1. **First time** — if the CSV does not exist yet, ``python -m bart_sf_ridership --refresh`` downloads
   the **full** history from ``--first`` (default 2018-02) through the last **complete** calendar month
   (one backfill run; can take a few minutes).
2. **After that** — each ``python -m bart_sf_ridership --refresh`` only downloads months **after** the
   latest ``month_end`` already in the file, merges them in, and rewrites the CSV (fast).
3. **Force rebuild** — ``python -m bart_sf_ridership --refresh --full`` replaces the whole series.

Optional upload after a local write::

    python -m bart_sf_ridership --refresh --upload-gcs gs://bucket/bart_sf_ridership_monthly.csv

**Attribution:** data from `BART ridership reports <https://www.bart.gov/about/reports/ridership>`_
(CC-BY where noted on their site).
"""

from __future__ import annotations

import argparse
import io
import os
import time
import zipfile
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd

_HTTP_UA = "MLP_Restaurant_CaseStudy/bart_sf_ridership (pandas; research)"
_DEFAULT_FILENAME = "bart_sf_ridership_monthly.csv"

# BART two-letter entry-station codes (SF downtown corridor).
BART_SF_FINANCIAL_ORIGIN_CODES: tuple[str, ...] = ("EM", "MT", "PL", "CC")
BART_MONTHLY_ORIGIN_TRIPS_COLUMN = "bart_sf_financial_district_origin_trips_monthly"

# First month known to ship ``Total Trips OD`` in the yearly zip.
_EARLIEST_YM: tuple[int, int] = (2018, 2)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def default_monthly_csv_path() -> Path:
    return _repo_root() / "data" / _DEFAULT_FILENAME


def bart_monthly_csv_uri_from_env() -> str | None:
    v = os.environ.get("BART_SF_RIDERSHIP_MONTHLY_CSV", "").strip()
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

    pr = urlparse(str(gs_uri).strip())
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


def _http_get_bytes(url: str, *, timeout: float = 120.0) -> bytes:
    req = Request(url, headers={"User-Agent": _HTTP_UA}, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _month_end(y: int, m: int) -> pd.Timestamp:
    return (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)).normalize()


def _next_month_first(y: int, m: int) -> date:
    if m == 12:
        return date(y + 1, 1, 1)
    return date(y, m + 1, 1)


def _ridership_monthly_direct_url(y: int, m: int) -> str:
    pub = _next_month_first(y, m)
    return f"https://www.bart.gov/sites/default/files/{pub.year}-{pub.month:02d}/Ridership_{y}{m:02d}.xlsx"


def _year_zip_url(year: int) -> str | None:
    if year in (2018, 2019, 2020, 2021):
        return f"https://www.bart.gov/sites/default/files/docs/ridership_{year}.zip"
    if year == 2022:
        return "https://www.bart.gov/sites/default/files/docs/Ridership_2022.zip"
    if year == 2023:
        return "https://www.bart.gov/sites/default/files/2024-02/ridership_2023.zip"
    if year == 2024:
        return "https://www.bart.gov/sites/default/files/2025-02/ridership_2024.zip"
    if year == 2025:
        return "https://www.bart.gov/sites/default/files/2026-02/ridership_OD_2025.zip"
    return None


def _zip_member_name(year: int, month: int) -> str:
    yyyymm = f"{year}{month:02d}"
    if year == 2018:
        return f"ridership_2018/Ridership_{yyyymm}.xlsx"
    if year in (2019, 2020, 2021):
        return f"ridership_{year}/Ridership_{yyyymm}.xlsx"
    if year == 2022:
        return f"Ridership_2022/Ridership_{yyyymm}.xlsx"
    return f"Ridership_{yyyymm}.xlsx"


_zip_bytes_cache: dict[int, bytes] = {}


def _fetch_workbook_bytes(year: int, month: int) -> bytes | None:
    """Return .xlsx bytes or None if not found."""
    global _zip_bytes_cache
    # Rolling single-file URLs (work for current months once published).
    direct = _ridership_monthly_direct_url(year, month)
    try:
        return _http_get_bytes(direct, timeout=90.0)
    except HTTPError as e:
        if e.code != 404:
            raise
    except URLError:
        pass

    zurl = _year_zip_url(year)
    if not zurl:
        return None
    if year not in _zip_bytes_cache:
        _zip_bytes_cache[year] = _http_get_bytes(zurl, timeout=180.0)
    zraw = _zip_bytes_cache[year]
    member = _zip_member_name(year, month)
    with zipfile.ZipFile(io.BytesIO(zraw)) as zf:
        try:
            return zf.read(member)
        except KeyError:
            # Some archives use different casing / prefix — try case-insensitive match
            lower = {n.lower(): n for n in zf.namelist()}
            hit = lower.get(member.lower())
            if hit:
                return zf.read(hit)
    return None


def _normalize_station_code(h: object) -> str:
    """Excel sometimes stores ``19`` as float ``19.0``."""
    if pd.isna(h):
        return ""
    if isinstance(h, (int, float)):
        f = float(h)
        if pd.isna(f):
            return ""
        if f == int(f):
            return str(int(f))
    s = str(h).strip()
    if len(s) > 2 and s.endswith(".0") and s[:-2].replace("-", "").isdigit():
        return s[:-2]
    return s


def _find_total_trips_sheet(xl: pd.ExcelFile) -> str | None:
    for name in xl.sheet_names:
        ln = name.lower()
        if "total" in ln and "trip" in ln:
            return name
    return None


def _parse_month_end_from_sheet(df: pd.DataFrame, year: int, month: int) -> pd.Timestamp:
    """Prefer embedded date / ``YYYY / MM``; fall back to workbook ``year`` / ``month``."""
    for r in range(min(12, len(df))):
        for c in range(min(24, df.shape[1])):
            v = df.iloc[r, c]
            if isinstance(v, pd.Timestamp):
                t = v.normalize()
                return (t + pd.offsets.MonthEnd(0)).normalize()
            if hasattr(v, "year") and not isinstance(v, str):
                try:
                    t = pd.Timestamp(v).normalize()
                    return (t + pd.offsets.MonthEnd(0)).normalize()
                except Exception:
                    pass
    s0 = str(df.iloc[2, 0]) if df.shape[0] > 2 else ""
    if "/" in s0 and any(ch.isdigit() for ch in s0):
        tok = s0.replace(" ", "")
        parts = [p for p in tok.split("/") if p]
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            y, m = int(parts[0]), int(parts[1])
            return _month_end(y, m)
    return _month_end(year, month)


def _sum_sf_origins_from_od(df: pd.DataFrame) -> float:
    """Sum matrix entries for columns whose header is in ``BART_SF_FINANCIAL_ORIGIN_CODES``."""
    if df.shape[0] < 5 or df.shape[1] < 3:
        return float("nan")

    header_row: int | None = None
    for r in range(min(14, len(df))):
        cell = df.iloc[r, 0]
        if pd.isna(cell):
            continue
        s = str(cell).lower()
        if "two-letter" in s or ("exit" in s and "station" in s and "code" in s):
            header_row = r
            break
    if header_row is not None:
        data_start = header_row + 1
    else:
        s00 = str(df.iloc[0, 0]) if pd.notna(df.iloc[0, 0]) else ""
        if "exit" in s00.lower():
            header_row, data_start = 1, 2
        else:
            return float("nan")

    codes: list[str] = []
    col_map: dict[str, int] = {}
    for j in range(1, min(df.shape[1], 64)):
        h = df.iloc[header_row, j]
        code = _normalize_station_code(h)
        if not code:
            continue
        if code.lower().startswith("unnamed"):
            break
        if code.lower() == "exits":
            break
        codes.append(code)
        col_map[code] = j

    total = 0.0
    for code in BART_SF_FINANCIAL_ORIGIN_CODES:
        j = col_map.get(code)
        if j is None:
            continue
        for r in range(data_start, min(df.shape[0], data_start + 55)):
            lab = df.iloc[r, 0]
            if pd.isna(lab) or (isinstance(lab, str) and not str(lab).strip()):
                break
            cell = df.iloc[r, j]
            if pd.notna(cell):
                try:
                    total += float(cell)
                except (TypeError, ValueError):
                    pass
    return total


def parse_workbook_bytes(
    raw: bytes,
    *,
    year: int,
    month: int,
) -> tuple[pd.Timestamp, float]:
    """Return ``(month_end, bart_sf_financial_district_origin_trips_monthly)``."""
    xl = pd.ExcelFile(io.BytesIO(raw))
    sheet = _find_total_trips_sheet(xl)
    if sheet is None:
        return _month_end(year, month), float("nan")
    df = pd.read_excel(io.BytesIO(raw), sheet_name=sheet, header=None, engine="openpyxl")
    me = _parse_month_end_from_sheet(df, year=year, month=month)
    val = _sum_sf_origins_from_od(df)
    return me, val


def fetch_one_month(year: int, month: int) -> tuple[pd.Timestamp, float]:
    raw = _fetch_workbook_bytes(year, month)
    if raw is None:
        return _month_end(year, month), float("nan")
    return parse_workbook_bytes(raw, year=year, month=month)


def _month_starts(first: pd.Timestamp, last: pd.Timestamp) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    cur = pd.Timestamp(first).normalize().replace(day=1)
    end = pd.Timestamp(last).normalize().replace(day=1)
    while cur <= end:
        out.append((int(cur.year), int(cur.month)))
        cur = cur + pd.offsets.MonthBegin(1)
    return out


def fetch_monthly_dataframe(
    *,
    first_month: str = "2018-02-01",
    last_month: str | None = None,
    progress: bool = False,
) -> pd.DataFrame:
    global _zip_bytes_cache
    _zip_bytes_cache = {}
    if last_month is None:
        last_month = (
            pd.Timestamp.today().normalize().replace(day=1) - pd.Timedelta(days=1)
        ).strftime("%Y-%m-%d")
    lo = max(pd.Timestamp(first_month), pd.Timestamp(_EARLIEST_YM[0], _EARLIEST_YM[1], 1))
    hi = pd.Timestamp(last_month)
    rows: list[dict[str, object]] = []
    for y, m in _month_starts(lo, hi):
        me, val = fetch_one_month(y, m)
        rows.append({"month_end": me, BART_MONTHLY_ORIGIN_TRIPS_COLUMN: val})
        if progress:
            print(f"{me.date()} -> {val:,.0f}" if pd.notna(val) else f"{me.date()} -> NaN")
        time.sleep(0.12)
    if not rows:
        return pd.DataFrame(columns=["month_end", BART_MONTHLY_ORIGIN_TRIPS_COLUMN])
    out = pd.DataFrame(rows)
    out["month_end"] = pd.to_datetime(out["month_end"]).dt.normalize()
    return out.sort_values("month_end").reset_index(drop=True)


def _normalize_monthly_df(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or "month_end" not in raw.columns or BART_MONTHLY_ORIGIN_TRIPS_COLUMN not in raw.columns:
        return pd.DataFrame(columns=["month_end", BART_MONTHLY_ORIGIN_TRIPS_COLUMN])
    df = raw.copy()
    df["month_end"] = pd.to_datetime(df["month_end"], errors="coerce").dt.normalize()
    df[BART_MONTHLY_ORIGIN_TRIPS_COLUMN] = pd.to_numeric(df[BART_MONTHLY_ORIGIN_TRIPS_COLUMN], errors="coerce")
    return df.dropna(subset=["month_end"]).sort_values("month_end").reset_index(drop=True)


def load_monthly_dataframe(path: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    if path is not None and str(path).strip():
        return _normalize_monthly_df(_read_csv_any(str(path).strip()))
    env_uri = bart_monthly_csv_uri_from_env()
    if env_uri:
        return _normalize_monthly_df(_read_csv_any(env_uri))
    p = default_monthly_csv_path()
    if not p.is_file():
        return pd.DataFrame(columns=["month_end", BART_MONTHLY_ORIGIN_TRIPS_COLUMN])
    return _normalize_monthly_df(pd.read_csv(p))


def merge_monthly_history(existing: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
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
    if last_month is None or not str(last_month).strip():
        return default_cap
    t = pd.Timestamp(str(last_month).strip()).normalize()
    user_end = (t + pd.offsets.MonthEnd(0)).normalize()
    return min(default_cap, user_end)


def refresh_monthly_cache_merged(
    *,
    existing: pd.DataFrame,
    full: bool = False,
    first_month_if_empty: str = "2018-02-01",
    last_month: str | None = None,
    progress: bool = False,
) -> pd.DataFrame:
    last_me = _cap_last_month_end(last_month, default_cap=_last_complete_calendar_month_end())
    global _zip_bytes_cache
    _zip_bytes_cache = {}

    if full:
        return fetch_monthly_dataframe(
            first_month=first_month_if_empty,
            last_month=last_me.strftime("%Y-%m-%d"),
            progress=progress,
        )

    base = _normalize_monthly_df(existing)
    if base.empty:
        return fetch_monthly_dataframe(
            first_month=first_month_if_empty,
            last_month=last_me.strftime("%Y-%m-%d"),
            progress=progress,
        )

    have_max = base["month_end"].max()
    if pd.isna(have_max):
        return fetch_monthly_dataframe(
            first_month=first_month_if_empty,
            last_month=last_me.strftime("%Y-%m-%d"),
            progress=progress,
        )

    start_next = (pd.Timestamp(have_max).normalize() + pd.offsets.MonthBegin(1)).normalize()
    if start_next > last_me:
        if progress:
            print(f"No new complete months (cache ends {have_max.date()}, last complete {last_me.date()}).")
        return base

    new_rows: list[dict[str, object]] = []
    for y, m in _month_starts(start_next, last_me):
        me, val = fetch_one_month(y, m)
        new_rows.append({"month_end": me, BART_MONTHLY_ORIGIN_TRIPS_COLUMN: val})
        if progress:
            print(f"{me.date()} -> {val:,.0f}" if pd.notna(val) else f"{me.date()} -> NaN")
        time.sleep(0.12)
    new_df = pd.DataFrame(new_rows) if new_rows else pd.DataFrame()
    return merge_monthly_history(base, new_df)


def monthly_series_for_macro_join(path: str | os.PathLike[str] | None = None) -> pd.Series:
    df = load_monthly_dataframe(path)
    if df.empty:
        return pd.Series(dtype="float64", name=BART_MONTHLY_ORIGIN_TRIPS_COLUMN)
    s = pd.Series(
        df[BART_MONTHLY_ORIGIN_TRIPS_COLUMN].values,
        index=pd.DatetimeIndex(df["month_end"]),
        name=BART_MONTHLY_ORIGIN_TRIPS_COLUMN,
    )
    return s.sort_index().astype("float64")


def write_monthly_cache(df: pd.DataFrame, path: str | os.PathLike[str] | None = None) -> Path:
    p = Path(path).expanduser().resolve() if path is not None else default_monthly_csv_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    return p


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Build BART SF downtown-origin monthly trip cache.")
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="Merge new months into the CSV (append after latest month). If CSV is missing, "
        "backfills full history from --first once; use --full to re-pull everything.",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="With --refresh: discard merged logic and re-download all months from --first to last complete.",
    )
    ap.add_argument(
        "--input",
        type=str,
        default=None,
        help="Existing CSV (local or gs://) to merge from if --output missing",
    )
    ap.add_argument("--output", type=str, default=None, help=f"Local CSV (default: {default_monthly_csv_path()})")
    ap.add_argument("--upload-gcs", type=str, default=None, help="After write, upload to gs://...")
    ap.add_argument("--first", type=str, default="2018-02-01", help="First month if cache empty / --full")
    ap.add_argument("--last", type=str, default=None, help="Last month cap (default: last complete)")
    args = ap.parse_args()
    out_path = Path(args.output).expanduser().resolve() if args.output else default_monthly_csv_path()

    if args.refresh:
        existing = pd.DataFrame()
        if args.input:
            existing = _normalize_monthly_df(_read_csv_any(args.input.strip()))
        elif out_path.is_file():
            existing = _normalize_monthly_df(pd.read_csv(out_path))
        else:
            env_uri = bart_monthly_csv_uri_from_env()
            if env_uri and env_uri.startswith("gs://"):
                existing = _normalize_monthly_df(_read_csv_from_gcs(env_uri))
            elif env_uri and Path(env_uri).expanduser().is_file():
                existing = _normalize_monthly_df(pd.read_csv(Path(env_uri).expanduser()))

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

    df = load_monthly_dataframe(str(out_path) if out_path.is_file() else None)
    print(f"Cache {out_path}: {len(df)} rows (use --refresh to update)")
    if not df.empty:
        print(df.tail(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
