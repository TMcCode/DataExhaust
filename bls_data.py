"""BLS Public Data API — CES employment & earnings for restaurant macro context.

Register (optional, higher daily limits): https://data.bls.gov/registrationEngine/

Set ``BLS_REGISTRATION_KEY`` in ``.env`` or ``.streamlit/secrets.toml`` (same resolution order as
``macro_data`` for FRED). Calls succeed without a key for light usage.

Default series (seasonally adjusted, monthly, U.S.):

- ``CES7000000001`` / ``CES7000000008`` — leisure & hospitality totals (employees, avg hourly wage)
- ``CES7072200001`` / ``CES7072200008`` — **NAICS 722** food services & drinking places (aggregate)
- **Finer CES NAICS splits (same datatype pattern as 722 totals):**

  ``CES7072230001`` / ``CES7072230008`` — **7223** special food services
  ``CES7072240001`` / ``CES7072240008`` — **7224** drinking places
  ``CES7072251101`` / ``CES7072251108`` — **722511** full-service restaurants
  ``CES7072251301`` / ``CES7072251308`` — **722513** limited-service restaurants

Restaurant-related retail sales (FRED MRTS: NAICS 722 headline NSA, limited-service 7222) are pulled via ``macro_data``.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from pathlib import Path

import pandas as pd
import requests

BLS_TIMESERIES_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# (bls_series_id, output_column_name)
_BLS_CES_RESTAURANT_CONTEXT: list[tuple[str, str]] = [
    ("CES7000000001", "bls_ces_leisure_hospitality_employment_thousands_sa"),
    ("CES7072200001", "bls_ces_food_services_drinking_places_employment_thousands_sa"),
    ("CES7072230001", "bls_ces_special_food_services_naics7223_employment_thousands_sa"),
    ("CES7072240001", "bls_ces_drinking_places_naics7224_employment_thousands_sa"),
    ("CES7072251101", "bls_ces_full_service_restaurants_naics722511_employment_thousands_sa"),
    ("CES7072251301", "bls_ces_limited_service_restaurants_naics722513_employment_thousands_sa"),
    ("CES7000000008", "bls_ces_leisure_hospitality_avg_hourly_earnings_usd_sa"),
    ("CES7072200008", "bls_ces_food_services_drinking_places_avg_hourly_earnings_usd_sa"),
    ("CES7072230008", "bls_ces_special_food_services_naics7223_avg_hourly_earnings_usd_sa"),
    ("CES7072240008", "bls_ces_drinking_places_naics7224_avg_hourly_earnings_usd_sa"),
    ("CES7072251108", "bls_ces_full_service_restaurants_naics722511_avg_hourly_earnings_usd_sa"),
    ("CES7072251308", "bls_ces_limited_service_restaurants_naics722513_avg_hourly_earnings_usd_sa"),
]

_MAX_YEARS_PER_REQUEST = 10


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _try_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        repo = _repo_root() / ".env"
        cwd = Path.cwd() / ".env"
        load_dotenv(repo, override=True)
        if cwd.resolve() != repo.resolve():
            load_dotenv(cwd, override=True)
    except ImportError:
        pass


def _env_file_value(path: Path, key: str) -> str | None:
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
        v = v.strip()
        if v.startswith('"') and v.endswith('"') and len(v) >= 2:
            v = v[1:-1]
        elif v.startswith("'") and v.endswith("'") and len(v) >= 2:
            v = v[1:-1]
        v = v.strip()
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


def resolve_bls_registration_key() -> str | None:
    """BLS registration key, or ``None`` (API still works with stricter rate limits)."""
    _try_load_dotenv()
    name = "BLS_REGISTRATION_KEY"
    for p in (_repo_root() / ".env", Path.cwd() / ".env"):
        k = _env_file_value(p, name)
        if k:
            return k.strip()
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


def describe_bls_key_source() -> str:
    return "BLS_REGISTRATION_KEY is set" if resolve_bls_registration_key() else "BLS_REGISTRATION_KEY not set (optional)"


def _period_to_month_end(year: int, period: str) -> pd.Timestamp:
    if not period.startswith("M"):
        raise ValueError(period)
    m = int(period[1:])
    if m < 1 or m > 12:
        raise ValueError(period)
    return pd.Timestamp(year=year, month=m, day=1) + pd.offsets.MonthEnd(0)


def _fetch_bls_window(
    series_ids: list[str],
    start_year: int,
    end_year: int,
    *,
    registration_key: str | None,
) -> list[dict]:
    body: dict[str, object] = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if registration_key:
        body["registrationKey"] = registration_key
    r = requests.post(
        BLS_TIMESERIES_URL,
        json=body,
        timeout=120,
        headers={"User-Agent": "MLP_Restaurant_CaseStudy/bls_data (pandas)"},
    )
    r.raise_for_status()
    payload = r.json()
    status = payload.get("status")
    if status != "REQUEST_SUCCEEDED":
        msgs = payload.get("message") or []
        raise RuntimeError(
            f"BLS API status={status!r}: {'; '.join(str(m) for m in msgs)}"
        )
    return list(payload.get("Results", {}).get("series", []))


def load_bls_ces_monthly_dataframe(
    observation_start: str = "2000-01-01",
    *,
    series_map: list[tuple[str, str]] | None = None,
    end_year: int | None = None,
    registration_key: str | None = None,
) -> pd.DataFrame:
    """Wide monthly panel (index ``month_end``) for default CES restaurant-context series."""
    smap = series_map or _BLS_CES_RESTAURANT_CONTEXT
    series_ids = [s for s, _ in smap]
    col_names = [c for _, c in smap]

    y0 = int(str(observation_start)[:4])
    y1 = end_year if end_year is not None else _dt.datetime.now().year
    if y1 < y0:
        raise ValueError("end_year before observation_start year")

    reg = registration_key if registration_key is not None else resolve_bls_registration_key()
    by_series: dict[str, dict[pd.Timestamp, float]] = {sid: {} for sid in series_ids}

    y = y0
    while y <= y1:
        win_end = min(y + _MAX_YEARS_PER_REQUEST - 1, y1)
        block = _fetch_bls_window(series_ids, y, win_end, registration_key=reg)
        sid_rows = {b["seriesID"]: b.get("data") or [] for b in block}
        for sid in series_ids:
            for row in sid_rows.get(sid, []):
                if row.get("period") == "M13":
                    continue
                try:
                    ts = _period_to_month_end(int(row["year"]), str(row["period"]))
                except (ValueError, KeyError):
                    continue
                raw = str(row.get("value", "")).strip()
                if raw in ("", "-"):
                    continue
                try:
                    val = float(raw)
                except ValueError:
                    continue
                by_series[sid][ts] = val
        time.sleep(0.35)
        y = win_end + 1

    pieces: dict[str, pd.Series] = {}
    for sid, col in zip(series_ids, col_names):
        d = by_series[sid]
        if not d:
            pieces[col] = pd.Series(dtype="float64", name=col)
            continue
        idx = sorted(d.keys())
        pieces[col] = pd.Series([d[t] for t in idx], index=pd.DatetimeIndex(idx), name=col)

    out = pd.DataFrame(pieces).sort_index()
    out.index = out.index.normalize()
    out.index.name = "month_end"
    return out


def probe_bls_ces() -> int:
    """Fetch one year of default series; prints key status. Returns 0 if OK."""
    print(describe_bls_key_source())
    df = load_bls_ces_monthly_dataframe(
        "2024-01-01",
        end_year=2024,
    )
    print("BLS CES probe:", df.shape, "columns:", list(df.columns))
    if df.empty or df.isna().all().all():
        print("BLS probe: no data returned — check series IDs or API status.")
        return 1
    print("BLS probe: OK (sample last row):")
    print(df.tail(1).T.to_string(header=False))
    return 0
