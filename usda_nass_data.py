"""USDA NASS Quick Stats — monthly commodity benchmarks (broilers / steers).

**Free API key (required):** https://quickstats.nass.usda.gov/api  

Set ``USDA_NASS_API_KEY`` in ``.env`` or ``.streamlit/secrets.toml`` (same convention as ``bls_data``).
If the key is absent, returns an empty DataFrame and emits a warning. Slow or failing endpoints
(per-column timeouts/errors) emit warnings and omit those columns so the rest of the macro panel can load.

**Optional cache (reuse after a successful pull):**

* ``USDA_NASS_CACHE_TTL_HOURS`` — default ``72``. Set ``0`` to disable disk cache reads/writes.
* ``USDA_NASS_CACHE_REFRESH=1`` — ignore cached files and refresh from NASS once.

**One-time / flaky server:** By default we request **small year windows** (``USDA_NASS_YEAR_CHUNK``,
default ``6`` years per HTTP call) instead of one huge ``year__GE`` query—this usually completes
where a single national monthly pull times out. Set ``USDA_NASS_YEAR_CHUNK=0`` to use one call.
Optionally bump ``USDA_NASS_READ_TIMEOUT`` (seconds, default ``120``, max ``600``).

Caches live under repo ``.cache/usda_nass/`` (see ``.gitignore``).
"""

from __future__ import annotations

import os
import time
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

NASS_HTTP_UA = "MLP_Restaurant_CaseStudy/usda_nass"

NASS_API_GET = "https://quickstats.nass.usda.gov/api/api_GET/"

# National survey, monthly totals. ``CENTS / LB`` priced series → divide by 100 → USD/lb column name.
_TARGETS: list[dict[str, object]] = [
    {
        "column": "usda_nass_broilers_price_received_usd_per_lb_sa_monthly_survey_mean",
        "cents_divide_for_usd_lb": True,
        "fixed": {
            "source_desc": "SURVEY",
            "sector_desc": "ANIMALS & PRODUCTS",
            "commodity_desc": "BROILERS",
            "statisticcat_desc": "PRICE RECEIVED",
            "unit_desc": "CENTS / LB",
            "freq_desc": "MONTHLY",
            "agg_level_desc": "NATIONAL",
            "country_name": "UNITED STATES",
            "domain_desc": "TOTAL",
        },
    },
    {
        "column": "usda_nass_steers_500lbs_plus_price_received_usd_per_cwt_na_monthly",
        "cents_divide_for_usd_lb": False,
        "fixed": {
            "source_desc": "SURVEY",
            "sector_desc": "ANIMALS & PRODUCTS",
            "commodity_desc": "CATTLE",
            "class_desc": "STEERS, GE 500 LBS",
            "statisticcat_desc": "PRICE RECEIVED",
            "unit_desc": "DOLLARS / CWT",
            "freq_desc": "MONTHLY",
            "agg_level_desc": "NATIONAL",
            "country_name": "UNITED STATES",
            "domain_desc": "TOTAL",
        },
    },
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _nass_disk_cache_dir() -> Path:
    d = _repo_root() / ".cache" / "usda_nass"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _nass_ttl_seconds() -> float:
    raw = os.environ.get("USDA_NASS_CACHE_TTL_HOURS", "").strip()
    if not raw:
        return 72.0 * 3600.0
    try:
        h = float(raw)
    except ValueError:
        return 72.0 * 3600.0
    return max(0.0, h) * 3600.0


def _nass_cache_refresh_requested() -> bool:
    return str(os.environ.get("USDA_NASS_CACHE_REFRESH", "")).strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _series_cache_path(column: str, year_ge: int) -> Path:
    slug = "".join(ch if str(ch).isalnum() or ch in "-._" else "_" for ch in column)[:140]
    return _nass_disk_cache_dir() / f"{slug}_y{year_ge}.pkl"


def _try_load_cached_series(path: Path, *, ttl_seconds: float) -> pd.Series | None:
    if ttl_seconds <= 0 or not path.is_file():
        return None
    age = time.time() - path.stat().st_mtime
    if age > ttl_seconds:
        return None
    try:
        ser = pd.read_pickle(path)  # noqa: S301
    except Exception:
        return None
    if isinstance(ser, pd.Series) and len(ser.index):
        out = ser.copy()
        out.index = pd.DatetimeIndex(pd.to_datetime(out.index)).normalize()
        return out.astype("float64")
    return None


def _save_cached_series(path: Path, series: pd.Series) -> None:
    if len(series.index) == 0:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        series.astype("float64").to_pickle(path)
    except Exception:
        pass


def _nass_requests_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": NASS_HTTP_UA})
    adapter = HTTPAdapter(pool_connections=2, pool_maxsize=2)
    s.mount("https://", adapter)
    return s


def _nass_connect_read_timeout() -> tuple[float, float]:
    raw = os.environ.get("USDA_NASS_READ_TIMEOUT", "").strip()
    try:
        read_sec = float(raw) if raw else 120.0
    except ValueError:
        read_sec = 120.0
    read_sec = max(30.0, min(read_sec, 600.0))
    return (20.0, read_sec)


def _nass_year_chunk_years() -> int:
    """Years per NASS request; ``0`` = single unbounded ``year__GE`` call (often slow / times out)."""
    raw = os.environ.get("USDA_NASS_YEAR_CHUNK", "6").strip()
    try:
        v = int(raw)
    except ValueError:
        return 6
    return max(0, min(v, 30))


def _nass_http_fetch_data(
    params: dict[str, str],
    *,
    session: requests.Session | None,
    timeout: tuple[float, float],
) -> list[dict[str, object]]:
    """One GET with retries; returns ``data`` list (possibly empty)."""
    last_err: str | None = None
    param_keys = sorted(k for k in params if k != "key")
    for attempt in range(4):
        try:
            get = session.get if session is not None else requests.get
            r = get(
                NASS_API_GET,
                params=params,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as e:
            last_err = f"timeout ({e})"
            if attempt + 1 < 4:
                time.sleep(min(20.0, 2**attempt))
            continue
        except requests.exceptions.RequestException as e:
            last_err = f"network ({e})"
            if attempt + 1 < 4:
                time.sleep(min(15.0, 1.5 * (2**attempt)))
            continue

        snippet = (r.text or "")[:480]
        try:
            j = r.json()
        except Exception:
            j = {}

        raw_err = j.get("error")
        if raw_err is False or raw_err is None:
            err_msgs: list[str] = []
        elif isinstance(raw_err, list):
            err_msgs = [str(x).strip() for x in raw_err if str(x).strip()]
        elif isinstance(raw_err, str):
            err_msgs = [raw_err.strip()] if raw_err.strip() else []
        else:
            err_msgs = [str(raw_err)]

        blob = "; ".join(err_msgs)
        low_blob = blob.lower()

        unauthorized = (
            r.status_code in {401, 403}
            or "unauthorized" in low_blob
            or ("invalid" in low_blob and "api" in low_blob)
        )
        if unauthorized:
            raise RuntimeError(
                "NASS unauthorized — check USDA_NASS_API_KEY at https://quickstats.nass.usda.gov/api"
            )

        data_raw = j.get("data")
        rows_ok = isinstance(data_raw, list)
        rows = list(data_raw) if rows_ok else None

        if r.status_code == 200 and rows_ok:
            if rows:
                return rows
            if blob:
                raise RuntimeError(f"USDA NASS returned no rows: {blob}")
            return []

        last_err = f"HTTP {r.status_code}: {blob or snippet}"

        if r.status_code >= 500 and attempt + 1 < 4:
            time.sleep(min(20.0, 2**attempt))
            continue
        break

    raise RuntimeError(
        f"USDA NASS request failed ({last_err}) params={param_keys}"
    )


def _try_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        r = _repo_root() / ".env"
        c = Path.cwd() / ".env"
        load_dotenv(r, override=True)
        if c.resolve() != r.resolve():
            load_dotenv(c, override=True)
    except ImportError:
        pass


def _env_last(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    last: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        if "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() != key:
            continue
        v = v.strip().strip('"').strip("'").strip()
        if v:
            last = v
    return last


def _toml_secret(key: str) -> str | None:
    try:
        import tomllib
    except ImportError:
        return None
    for root in (_repo_root(), Path.cwd()):
        p = root / ".streamlit" / "secrets.toml"
        if not p.is_file():
            continue
        try:
            raw = p.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            data = tomllib.loads(raw.decode("utf-8"))
            v = data.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
        except Exception:
            continue
    return None


def resolve_usda_nass_api_key() -> str | None:
    _try_load_dotenv()
    name = "USDA_NASS_API_KEY"
    for p in (_repo_root() / ".env", Path.cwd() / ".env"):
        k = _env_last(p, name)
        if k:
            return k
    k = _toml_secret(name)
    if k:
        return k
    k = os.environ.get(name)
    if k and str(k).strip():
        return str(k).strip()
    try:
        import streamlit as st

        if name in st.secrets:
            v = st.secrets[name]
            if v and str(v).strip():
                return str(v).strip()
    except Exception:
        pass
    return None


def describe_usda_key() -> str:
    return (
        "USDA_NASS_API_KEY is set"
        if resolve_usda_nass_api_key()
        else "USDA_NASS_API_KEY not set — see https://quickstats.nass.usda.gov/api"
    )


_MONTH = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def _parse_money_string(x: object) -> float | None:
    if x is None:
        return None
    s = str(x).strip().replace(",", "")
    if not s or s in {"(D)", "(NA)", "(X)", "(S)"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _row_month_end(row: dict[str, object]) -> pd.Timestamp | None:
    try:
        y = int(str(row.get("year", "")).strip())
    except ValueError:
        return None

    rp = row.get("reference_period_desc") or row.get("period_desc") or ""
    tok = str(rp).strip().upper().split()
    if not tok:
        return None
    ab = tok[0][:3]
    m = _MONTH.get(ab)
    if m is None:
        return None
    return pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0)


def _fetch_nass_json(
    api_key: str,
    base: dict[str, str],
    *,
    year_ge: int,
    session: requests.Session | None = None,
) -> list[dict[str, object]]:
    """Fetch all rows from ``year_ge`` through the current calendar year."""
    timeout = _nass_connect_read_timeout()
    chunk = _nass_year_chunk_years()
    y_max = int(datetime.now().year)

    if chunk <= 0:
        params = {
            **base,
            "key": api_key,
            "format": "JSON",
            "year__GE": str(year_ge),
        }
        return _nass_http_fetch_data(params, session=session, timeout=timeout)

    out: list[dict[str, object]] = []
    y = year_ge
    while y <= y_max:
        y_hi = min(y + chunk - 1, y_max)
        params = {
            **base,
            "key": api_key,
            "format": "JSON",
            "year__GE": str(y),
            "year__LE": str(y_hi),
        }
        out.extend(_nass_http_fetch_data(params, session=session, timeout=timeout))
        y = y_hi + 1
        if y <= y_max:
            time.sleep(0.2)
    return out


def _rows_to_sorted_series(
    rows: list[dict[str, object]],
    *,
    cents_to_usd_per_lb: bool,
) -> pd.Series:
    buckets: dict[pd.Timestamp, float] = {}
    for row in rows:
        if str(row.get("freq_desc") or "").upper().find("MONTH") == -1:
            continue
        dom = str(row.get("domain_desc") or "").upper()
        if dom and dom != "TOTAL":
            continue
        ts = _row_month_end(row)
        if ts is None:
            continue
        v = _parse_money_string(row.get("Value"))
        if v is None:
            continue
        if cents_to_usd_per_lb:
            u = str(row.get("unit_desc") or "").upper()
            if "CENT" in u and "LB" in u.replace(" ", ""):
                v = v / 100.0
        buckets[ts] = v

    if not buckets:
        return pd.Series(dtype="float64")
    ix = sorted(buckets.keys())
    return pd.Series([buckets[k] for k in ix], index=pd.DatetimeIndex(ix))


def load_usda_nass_monthly_optional(
    observation_start: str = "2000-01-01",
    *,
    targets: list[dict[str, object]] | None = None,
) -> pd.DataFrame:
    """Wide monthly USDA columns; empty if ``USDA_NASS_API_KEY`` missing."""
    key = resolve_usda_nass_api_key()
    if not key:
        warnings.warn(
            "USDA_NASS skipped: add USDA_NASS_API_KEY → https://quickstats.nass.usda.gov/api",
            stacklevel=2,
        )
        return pd.DataFrame()

    y0 = max(1950, int(str(observation_start)[:4]))
    specs = targets or _TARGETS
    cols = {}
    ttl_s = _nass_ttl_seconds()
    bypass_cache_read = _nass_cache_refresh_requested()

    with _nass_requests_session() as session:
        for spec in specs:
            col = str(spec["column"])
            fixed_d = dict(spec["fixed"])  # type: ignore[arg-type]
            fixed_str = {k: str(v) for k, v in fixed_d.items()}
            cache_path = _series_cache_path(col, y0)
            if not bypass_cache_read and ttl_s > 0:
                hit = _try_load_cached_series(cache_path, ttl_seconds=ttl_s)
                if hit is not None:
                    cols[col] = hit
                    continue
            try:
                rows = _fetch_nass_json(key, fixed_str, year_ge=y0, session=session)
                cents_bool = bool(spec.get("cents_divide_for_usd_lb", False))
                ser = _rows_to_sorted_series(rows, cents_to_usd_per_lb=cents_bool)
                cols[col] = ser
                if ttl_s > 0 and len(ser.index):
                    _save_cached_series(cache_path, ser)
            except Exception as e:
                warnings.warn(
                    f"USDA NASS skipped column {col!r}: {type(e).__name__}: {e}. "
                    "Quick Stats often times out—retry later. Macro uses commodity CSVs by default "
                    "(commodity_paste_csv), not this API. "
                    "After any successful fetch, .cache/usda_nass/ avoids repeat calls until "
                    "USDA_NASS_CACHE_TTL_HOURS expires (or set USDA_NASS_CACHE_REFRESH=1 to force).",
                    stacklevel=2,
                )
            time.sleep(0.45)

    out = pd.DataFrame(cols).sort_index()
    if out.empty:
        return out
    out.index = out.index.normalize()
    out.index.name = "month_end"
    return out


def probe_usda_nass() -> int:
    print(describe_usda_key())
    key = resolve_usda_nass_api_key()
    if not key:
        print("Skipping probe (no key).")
        return 1
    df = load_usda_nass_monthly_optional("2019-01-01")
    if df.empty:
        print("Probe: empty frame — widen filters / check series availability.")
        return 1
    print("Probe OK:", df.shape, list(df.columns))
    print(df.tail(2))
    return 0
