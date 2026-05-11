"""Load U.S. macro series into pandas (FRED API).

Aligned with ``streamlit_sss_forecast_app_plan.md`` §3.2 macro list. **Series note:** FRED retired
``CUSR0000SEFV02`` (“limited‑service meals and snacks” CPI detail); we use ``CUSR0000SEFV05``
(*Other food away from home*, NSA) as the closest surviving sub‑aggregate. Umbrella food‑away CPI
remains ``CUSR0000SEFV``. **Broad CPI-U (FRED):** ``CPIAUCSL`` headline (all items, SA),
``CPILFESL`` core (less food & energy, SA), ``CUSR0000SAF11`` food at home (SA) — each gets
``*_yoy_pct`` for SSS / traffic vs overall inflation context.

**Never commit API keys.** You may store the same key in both repo ``.env`` and ``.streamlit/secrets.toml``;
only one lookup succeeds — duplicates are harmless. Resolve ``FRED_API_KEY`` (after applying dotenv defaults):

1. ``python-dotenv`` on repo-root then (if different path) cwd ``.env``, with ``override=True`` so files beat a stale shell export
2. Built-in parse of those same ``.env`` paths if needed
3. Local ``.streamlit/secrets.toml`` (repo root then cwd; UTF-8 BOM tolerated)
4. Shell environment variable ``FRED_API_KEY`` (e.g. CI with no local secrets files)
5. ``st.secrets["FRED_API_KEY"]`` under Streamlit / remote *App settings → Secrets*

Get a key: https://fredaccount.stlouisfed.org/apikeys — **Version 2** uses
``Authorization: Bearer <key>`` (this module calls v2 first, then falls back to legacy ``?api_key=``).

BLS CES columns (employment & hourly earnings for leisure vs food services) are merged from
module ``bls_data`` after FRED pulls; optional ``BLS_REGISTRATION_KEY`` at
https://data.bls.gov/registrationEngine/ .

**PPI commercial rent (FRED, BLS PPI, NSA index):** ``PCU531120531120`` lessors of nonresidential
buildings (broad) and ``PCU5311205311201`` leasing of shopping centers and retail stores — both land
in the monthly frame with YoY columns; dashboards chart **retail / shopping leasing only** (see
:data:`PPI_SHOPPING_RETAIL_RENT_YOY_CHART_SPECS`).

Optional **paste CSV** commodity columns (broilers/turkeys, beef cattle benchmarks) merge from
``commodity_paste_csv`` when ``include_commodity_csvs=True`` (default — files live beside this
module: ``broilers_turkeys_monthly_paste.csv``, ``beef_cattle_prices_received_monthly_paste.csv``).
Column names are ``commodity_*_monthly_paste``; they are joined **after** FRED/gas and **before** BLS
so they are easier to spot in exported ``mlp_macro_monthly.csv``.
Use ``load_mlp_master.py --no-commodity-csvs`` to skip if files are absent.

Optional **BART SF financial-district origin trips** (monthly sums from BART’s published OD
``Total Trips`` matrices for entry stations ``EM``, ``MT``, ``PL``, ``CC``): if
``data/bart_sf_ridership_monthly.csv`` exists or ``BART_SF_RIDERSHIP_MONTHLY_CSV`` is set (local or
``gs://``), :mod:`bart_sf_ridership` merges ``bart_sf_financial_district_origin_trips_monthly``.
Like MTA, ``python -m bart_sf_ridership --refresh`` **appends** new complete months after the first
full backfill; ``--full`` re-downloads all. **Not** the api.bart.gov schedule API.

Optional **MTA Manhattan subway entries** (monthly sums of entry swipes / taps; RTO-style proxy):
if ``data/mta_manhattan_subway_monthly.csv`` exists, or env ``MTA_MANHATTAN_SUBWAY_MONTHLY_CSV`` points
to that file or ``gs://bucket/path.csv`` (same Storage credentials as Sheets when using GCS),
:mod:`mta_manhattan_subway` merges ``mta_manhattan_subway_entries_monthly_sum`` into the monthly
frame and **sums** that column within each calendar quarter (other series remain quarter-end **last**
observation). Update the cache incrementally with ``python -m mta_manhattan_subway --refresh``; use
``--full`` for a complete rebuild; ``--upload-gcs gs://...`` to publish after a local write.

Optional **OpenTable State of Industry U.S. seated diners** (monthly YoY % from online reservations):
if ``data/opentable_us_seated_diners_monthly.csv`` exists, or env
``OPENTABLE_US_SEATED_DINERS_MONTHLY_CSV`` points to that file or ``gs://bucket/path.csv``,
:mod:`opentable_state_industry` merges
``opentable_us_seated_diners_online_reservations_yoy_pct`` plus
``opentable_fast_casual_exposed_city_index_yoy_pct``. These are already YoY percent changes,
so no additional YoY transform is computed; quarterly macro uses the last monthly value in quarter.

**Spend anchor (indexed “\$1000 today”):** For broilers ($/lb paste), all-beef cattle ($/cwt
paste), limited-service (722513) CES **avg hourly earnings** (SA), and **PPI retail / shopping-center
lease rent** (NSA index), we take the **calendar-year mean level** for :data:`SPEND_EQUIV_BASE_YEAR`
(default **2019**) as the basket price. Each month
(and each calendar quarter, using quarter-end levels) gets ``equiv_usd_1000_at_<year>avg_*`` =
``1000 × (level / anchor-year mean)``. The same rule applies to **CPI-U all items (SA)** as a
**broad-consumer** reference basket (column :data:`SPEND_EQUIV_HEADLINE_CPI_U_ALL_ITEMS_EQUIV_USD_COL`);
that column is included in exported macro CSVs for narrative context but is **not** part of the
restaurant-ingredient chart series list. A separate **annual** table (see :func:`spend_equiv_annual_dict_key`)
stores the **mean of those monthly equivalents** by ``calendar_year`` for CSV / GCS.

**Broad pay (FRED):** **ECI** wages & salaries for all civilian workers (``CIS1020000000000I``, SA
index, quarterly from BLS) and **CPS** median usual weekly nominal earnings for full-time wage and
salary workers (``LEU0252881500Q``, quarterly) are expanded to **every month in each calendar quarter**
so 12‑month YoY matches quarter-over-year logic on the monthly index. **CES** all private average
hourly earnings (``CES0500000003``, monthly SA) adds the payroll / establishment side.
``workforce_pay_ces_cps_avg_yoy_pct`` is the **simple mean** of CES and CPS YoY % (not an official
BLS statistic — mean private hourly vs median full-time weekly, different coverage).

Usage::

    from macro_data import load_macro_dataframes, spend_equiv_annual_dict_key
    dfs = load_macro_dataframes()
    dfs["monthly"].head()
    dfs["calendar_quarter"].tail()
    dfs.get(spend_equiv_annual_dict_key())
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import bart_sf_ridership
import bls_data
import commodity_paste_csv
import mta_manhattan_subway
import opentable_state_industry
import pandas as pd
import requests

_FRED_OBS_URL_V2 = "https://api.stlouisfed.org/fred/v2/series/observations"
_FRED_OBS_URL_V1 = "https://api.stlouisfed.org/fred/series/observations"
_FRED_HTTP_UA = "MLP_Restaurant_CaseStudy/universal_fred_macro (pandas; github.com economic research)"
_FRED_RETRY_STATUSES = frozenset({500, 502, 503, 504})
_FRED_API_KEY_CHARS = re.compile(r"^[a-z0-9]{32}$")

# Monthly **flow** totals: calendar quarter = sum of months (not last month of quarter).
_QUARTER_AGG_SUM_LEVEL_COLUMNS: frozenset[str] = frozenset(
    {
        mta_manhattan_subway.MTA_MONTHLY_ENTRIES_COLUMN,
        bart_sf_ridership.BART_MONTHLY_ORIGIN_TRIPS_COLUMN,
    }
)

# Calendar year used as price anchor for :func:`spend_equiv_base_means` (pre-pandemic baseline).
SPEND_EQUIV_BASE_YEAR: int = 2019
_SPEND_EQUIV_ANCHOR_USD: float = 1000.0

_y_anchor = int(SPEND_EQUIV_BASE_YEAR)

# (level column, USD column) — ``equiv_* = _SPEND_EQUIV_ANCHOR_USD * level / mean(level in anchor year)``.
SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS: tuple[tuple[str, str], ...] = (
    (
        "commodity_broilers_price_received_usd_per_lb_monthly_paste",
        f"equiv_usd_1000_at_{_y_anchor}avg_broilers_lb_paste",
    ),
    (
        "commodity_all_beef_cattle_price_received_usd_per_cwt_monthly_paste",
        f"equiv_usd_1000_at_{_y_anchor}avg_beef_cattle_cwt_paste",
    ),
    (
        "bls_ces_limited_service_restaurants_naics722513_avg_hourly_earnings_usd_sa",
        f"equiv_usd_1000_at_{_y_anchor}avg_limited_svc_hourly_sa",
    ),
    # PPI lessors — shopping centers & retail stores (NSA index); same series as “Retail & shopping space rent” YoY chart.
    (
        "ppi_lessors_shopping_centers_retail_stores_rent_index_nsa",
        f"equiv_usd_1000_at_{_y_anchor}avg_ppi_retail_shopping_rent_nsa",
    ),
)

# Headline CPI-U (FRED ``CPIAUCSL`` → ``cpi_u_all_items_sa_index``): same \$1000 @ anchor-year-mean
# construction as above, for text / CSV context (not plotted with restaurant spend-equiv inputs).
SPEND_EQUIV_HEADLINE_CPI_U_ALL_ITEMS_EQUIV_USD_COL: str = (
    f"equiv_usd_1000_at_{_y_anchor}avg_cpi_u_all_items_sa"
)
SPEND_EQUIV_AT_ANCHOR_TEXT_ONLY_SPECS: tuple[tuple[str, str], ...] = (
    ("cpi_u_all_items_sa_index", SPEND_EQUIV_HEADLINE_CPI_U_ALL_ITEMS_EQUIV_USD_COL),
)
# All spend-equiv USD columns written to monthly / quarterly / annual macro tables.
SPEND_EQUIV_AT_ANCHOR_ALL_SPECS: tuple[tuple[str, str], ...] = (
    SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS + SPEND_EQUIV_AT_ANCHOR_TEXT_ONLY_SPECS
)


def spend_equiv_annual_dict_key() -> str:
    """Bundle / CSV key for the yearly roll-up of ``equiv_usd_1000_at_<year>avg_*`` columns."""
    return f"annual_{int(SPEND_EQUIV_BASE_YEAR)}_spend_equiv"

# (fred_series_id, output_column_name) — monthly flow unless noted weekly below.
_SERIES_MONTHLY_LEVELS: list[tuple[str, str]] = [
    # Former CUSR0000SEFV02 — discontinued / removed from FRED (was limited-service meals detail).
    ("CUSR0000SEFV05", "cpi_other_food_away_from_home_index"),
    ("CUSR0000SEFV", "cpi_food_away_from_home_index"),
    # CPI-U “headline” vs core vs grocery — YoY columns via append_yoy_pct; join to SSS on fiscal×month.
    ("CPIAUCSL", "cpi_u_all_items_sa_index"),
    ("CPILFESL", "cpi_u_core_less_food_energy_sa_index"),
    ("CUSR0000SAF11", "cpi_u_food_at_home_sa_index"),
    # Census MRTS — food services & drinking (NAICS 722), NSA millions (FRED MRTSSM722USN). Replaces legacy SA id MRTSSM722USS.
    ("MRTSSM722USN", "retail_food_services_drinking_sales_millions_nsa"),
    # Full-service-only (7221) and drinking-places-only (7224) millions splits stopped updating in the
    # legacy MRTSSM722* release; MRTSMPCSM722* without “SM” in the id is **percent change**, not levels.
    # Limited-service eating places (7222): SM72251XUSN is the surviving millions series; stitch
    # MRTSSM7222USN for older months where SM is absent.
    ("SM72251XUSN", "retail_sales_limited_service_eating_places_naics7222_millions_nsa"),
    ("UNRATE", "unemployment_rate_pct"),
    ("DSPI", "disposable_personal_income_billion_sa_monthly"),
    ("UMCSENT", "umich_consumer_sentiment_index"),
    # BLS PPI — nonresidential building landlords (rent received); NSA index, YoY via append_yoy_pct.
    ("PCU531120531120", "ppi_lessors_nonresidential_buildings_rent_index_nsa"),
    (
        "PCU5311205311201",
        "ppi_lessors_shopping_centers_retail_stores_rent_index_nsa",
    ),
    # ECI wages & salaries, all civilian workers (SA index; quarterly FRED obs → month-end last-in-month).
    ("CIS1020000000000I", "eci_wages_salaries_all_civilian_index_sa"),
    # CES all employees, total private — avg hourly earnings (monthly SA), establishment survey.
    ("CES0500000003", "fred_ces_all_private_avg_hourly_earnings_usd_sa"),
    # CPS median usual weekly nominal earnings, full-time wage & salary 16+ (quarterly, NSA).
    ("LEU0252881500Q", "cps_median_usual_weekly_nominal_ft_wage_salary_usd"),
]

# YoY % column + legend label for PPI shopping-center / retail-store leasing only (chart use).
PPI_SHOPPING_RETAIL_RENT_YOY_CHART_SPECS: tuple[tuple[str, str], ...] = (
    (
        "ppi_lessors_shopping_centers_retail_stores_rent_index_nsa_yoy_pct",
        "Retail & shopping space rent (PPI)",
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _sanitize_fred_api_key(raw: str) -> str:
    """Trim BOM/whitespace; keep only lowercase alnums (quotes/spaces accidentally pasted in)."""
    s = str(raw).replace("\ufeff", "").strip().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _validated_fred_key(raw: str) -> str:
    """FRED rejects keys unless they decode to exactly 32 lowercase alnums."""
    key = _sanitize_fred_api_key(raw)
    if not _FRED_API_KEY_CHARS.fullmatch(key):
        raise RuntimeError(
            "FRED_API_KEY must resolve to exactly 32 letters/digits (lowercase after cleanup). "
            f"Got {len(key)} character(s) after removing spaces/quotes/other symbols — "
            "re-copy from https://fredaccount.stlouisfed.org/apikeys "
            "(one line in .env, no wrapping). If you pasted a traceback URL in chat or email, rotate the key."
        )
    return key


def _try_load_dotenv() -> None:
    """Load `.env`; ``override=True`` so an updated repo file replaces a stale shell ``export``."""
    try:
        from dotenv import load_dotenv

        repo_env = _repo_root() / ".env"
        cwd_env = Path.cwd() / ".env"
        load_dotenv(repo_env, override=True)
        if cwd_env.resolve() != repo_env.resolve():
            load_dotenv(cwd_env, override=True)
    except ImportError:
        pass


def _strip_utf8_bom(raw: bytes) -> bytes:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:]
    return raw


def _fred_key_from_dotenv_plain(path: Path) -> str | None:
    """``KEY=value`` lines from ``.env`` without requiring ``python-dotenv``.

    If ``FRED_API_KEY`` appears multiple times (common mistake), **the last non-empty
    assignment wins**.
    """
    if not path.is_file():
        return None
    try:
        raw = _strip_utf8_bom(path.read_bytes())
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
        key, _, val = s.partition("=")
        if key.strip() != "FRED_API_KEY":
            continue
        val = val.strip()
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'") and len(val) >= 2:
            val = val[1:-1]
        val = val.strip()
        if val:
            last = val
    return last


def count_fred_api_key_lines_in_dotenv(path: Path) -> int:
    """How many distinct ``FRED_API_KEY=`` assignments exist (for diagnostics)."""
    if not path.is_file():
        return 0
    try:
        text = _strip_utf8_bom(path.read_bytes()).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        if "=" not in s:
            continue
        env_key, _, val = s.partition("=")
        if env_key.strip() != "FRED_API_KEY":
            continue
        if val.strip():
            n += 1
    return n


def _fred_key_from_local_secrets_toml() -> str | None:
    """Read ``FRED_API_KEY`` from ``.streamlit/secrets.toml`` (not only under ``streamlit run``)."""
    try:
        import tomllib
    except ImportError:
        return None

    for root in (_repo_root(), Path.cwd()):
        path = root / ".streamlit" / "secrets.toml"
        if not path.is_file():
            continue
        try:
            raw = _strip_utf8_bom(path.read_bytes())
            data = tomllib.loads(raw.decode("utf-8"))
            v = data.get("FRED_API_KEY")
            if v is not None and str(v).strip():
                return str(v).strip()
        except Exception:
            continue
    return None


def _require_fred_api_key() -> str:
    _try_load_dotenv()
    name = "FRED_API_KEY"

    # Prefer on-disk secrets over shell env — avoids a revoked `export FRED_API_KEY=...`
    # in ~/.zprofile masking an updated `.env`.
    for env_path in (_repo_root() / ".env", Path.cwd() / ".env"):
        k = _fred_key_from_dotenv_plain(env_path)
        if k:
            return _validated_fred_key(k)

    k = _fred_key_from_local_secrets_toml()
    if k:
        return _validated_fred_key(k)

    k = os.environ.get(name)
    if k and str(k).strip():
        return _validated_fred_key(str(k))

    try:
        import streamlit as st

        if name in st.secrets:
            v = st.secrets[name]
            if v and str(v).strip():
                return _validated_fred_key(str(v))
    except Exception:
        pass

    secrets_path = _repo_root() / ".streamlit" / "secrets.toml"
    env_dot = _repo_root() / ".env"
    env_exists = env_dot.is_file()
    sec_exists = secrets_path.is_file()
    hint = (
        "Missing FRED_API_KEY.\n\n"
        "Lookup order: optional python-dotenv (override=True) → parse repo/cwd .env → "
        f"{secrets_path} → shell env → st.secrets.\n\n"
        f"Repo .env exists: {env_exists} ({env_dot})\n"
        f"Repo secrets.toml exists: {sec_exists} ({secrets_path})\n\n"
        "If a file exists but this still fails: use a single line `FRED_API_KEY=xxxx` (no spaces "
        "around `=`), or in TOML `FRED_API_KEY = \"xxxx\"`. Remove BOM if you edited in Windows.\n\n"
        "Keys on Streamlit Community Cloud do not sync to your Mac — copy them locally if needed.\n\n"
        "https://fred.stlouisfed.org/docs/api/api_key.html"
    )
    raise RuntimeError(hint)


def _fred_http_error_message(r: requests.Response) -> str:
    try:
        j = r.json()
        s = str(j.get("error_message") or j.get("message") or "").strip()
        if s:
            return s
    except Exception:
        pass
    return (r.text or "")[:400].strip()


def _fred_get_with_retries(url: str, *, attempts: int = 5, **kwargs: object) -> requests.Response:
    """GET with backoff on transient 5xx (St. Louis Fed occasionally returns HTML 500)."""
    req_kw = dict(kwargs)
    hdr = dict(req_kw.get("headers") or {})
    hdr.setdefault("User-Agent", _FRED_HTTP_UA)
    req_kw["headers"] = hdr
    last: requests.Response | None = None
    for i in range(attempts):
        last = requests.get(url, timeout=120, **req_kw)
        if last.ok or last.status_code not in _FRED_RETRY_STATUSES:
            return last
        if i + 1 < attempts:
            time.sleep(min(1.5 * (2**i), 20.0))
    assert last is not None
    return last


def _fred_get_observations_payload(
    series_id: str,
    api_key: str,
    observation_start: str,
    extra_params: dict[str, str | int] | None = None,
) -> dict:
    """Fetch observations: legacy v1 ``api_key`` first (broad series coverage), retries on 5xx; then v2 Bearer.

    Some IDs return HTTP 404 on v2 observations but succeed on v1; v1 can also throw transient 500.
    """
    key = _validated_fred_key(api_key)
    params: dict[str, str | int] = {
        "series_id": series_id,
        "file_type": "json",
        "observation_start": observation_start,
    }
    if extra_params:
        params.update(extra_params)

    p1 = dict(params)
    p1["api_key"] = key

    rv1 = _fred_get_with_retries(_FRED_OBS_URL_V1, params=p1)
    if rv1.ok:
        return rv1.json()

    headers_v2 = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": _FRED_HTTP_UA,
    }
    rv2 = _fred_get_with_retries(
        _FRED_OBS_URL_V2,
        params=params,
        headers=headers_v2,
    )
    if rv2.ok:
        return rv2.json()

    m1 = _fred_http_error_message(rv1) or (rv1.text or "")[:400]
    m2 = _fred_http_error_message(rv2) or (rv2.text or "")[:400]
    hint = ""
    low = (m2 + " " + m1).lower()
    if "not registered" in low or "credentials" in low:
        hint = (
            " Confirm the key at https://fredaccount.stlouisfed.org/apikeys ; "
            "`unset FRED_API_KEY` if an old shell export hides an updated `.env`."
        )
    raise RuntimeError(
        f"FRED rejected requests for series_id={series_id}. "
        f"v1 api_key HTTP {rv1.status_code}: {m1 or rv1.reason}; "
        f"v2 Bearer HTTP {rv2.status_code}: {m2 or rv2.reason}.{hint}"
    )


def _fred_observations_payload_to_series(payload: dict) -> pd.Series:
    rows = payload.get("observations", [])
    dt, vals = [], []
    for o in rows:
        dt.append(pd.Timestamp(o["date"]))
        raw = str(o["value"]).strip()
        vals.append(float("nan") if raw in ("", ".") else float(raw))
    ser = pd.Series(vals, index=pd.DatetimeIndex(dt, name="period"), dtype="float64")
    return ser.sort_index()


def _fred_observations(series_id: str, api_key: str, observation_start: str) -> pd.Series:
    """Daily/weekly/monthly observations → ``pd.Series`` indexed by date (Timestamp)."""
    payload = _fred_get_observations_payload(series_id, api_key, observation_start)
    return _fred_observations_payload_to_series(payload)


def _fred_series_to_month_end_last(
    series_id: str,
    column_name: str,
    observation_start: str,
    api_key: str,
) -> tuple[str, pd.Series]:
    """FRED observations → last point in each calendar month (month-end index)."""
    s = pd.to_numeric(_fred_observations(series_id, api_key, observation_start), errors="coerce")
    idx = pd.to_datetime(s.index)
    last_in_month = s.groupby(idx.to_period("M")).last()
    ts_index = last_in_month.index.to_timestamp(how="end").normalize()
    return column_name, pd.Series(last_in_month.values, index=ts_index, name=column_name)


def _legacy_mrtssm7222_monthly_last(observation_start: str, api_key: str) -> pd.Series:
    """Legacy limited-service retail millions (older FRED id) at month-end for ``combine_first``."""
    s_leg = pd.to_numeric(
        _fred_observations("MRTSSM7222USN", api_key, observation_start),
        errors="coerce",
    )
    ix = pd.to_datetime(s_leg.index)
    leg_m = s_leg.groupby(ix.to_period("M")).last()
    leg_ix = leg_m.index.to_timestamp(how="end").normalize()
    return pd.Series(leg_m.values, index=leg_ix, dtype="float64")


def _load_mta_series_for_macro() -> pd.Series:
    mta_path = os.environ.get("MTA_MANHATTAN_SUBWAY_MONTHLY_CSV", "").strip()
    return mta_manhattan_subway.monthly_series_for_macro_join(mta_path if mta_path else None)


def _load_bart_series_for_macro() -> pd.Series:
    bart_path = os.environ.get("BART_SF_RIDERSHIP_MONTHLY_CSV", "").strip()
    return bart_sf_ridership.monthly_series_for_macro_join(bart_path if bart_path else None)


def _load_opentable_frame_for_macro() -> pd.DataFrame:
    opentable_path = os.environ.get("OPENTABLE_US_SEATED_DINERS_MONTHLY_CSV", "").strip()
    return opentable_state_industry.monthly_dataframe_for_macro_join(
        opentable_path if opentable_path else None
    )


# Columns whose FRED release is **quarterly** but should be carried across all months in each
# calendar quarter before YoY (so ``pct_change(12)`` on the monthly index is interpretable).
_QUARTER_LEVEL_EXPAND_TO_MONTHS: tuple[str, ...] = (
    "eci_wages_salaries_all_civilian_index_sa",
    "cps_median_usual_weekly_nominal_ft_wage_salary_usd",
)

# Already-percent monthly metrics that should be copied into the quarterly macro table with a
# quarter-end-last rule, not fed through a second YoY calculation.
_PRECOMPUTED_MONTHLY_PCT_QUARTER_LAST_COLUMNS: tuple[str, ...] = (
    opentable_state_industry.OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN,
    opentable_state_industry.OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN,
)


def expand_quarterly_levels_to_months_in_quarter(
    monthly_levels: pd.DataFrame,
    columns: tuple[str, ...] = _QUARTER_LEVEL_EXPAND_TO_MONTHS,
) -> pd.DataFrame:
    """For each named column, set every month-end in a calendar quarter to that quarter's last known level.

    Quarterly BLS/FRED points (ECI, CPS weekly median) may appear on only one month per quarter on the
    month-end index; copying the quarter's level to Jan–Mar, Apr–Jun, etc. makes 12‑month YoY and
    CES/CPS composites align month-by-month with CES monthly earnings.
    """
    if monthly_levels.empty:
        return monthly_levels
    out = monthly_levels.sort_index().copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        return out
    for c in columns:
        if c not in out.columns:
            continue
        s = pd.to_numeric(out[c], errors="coerce")
        sn = s.dropna()
        if sn.empty:
            continue
        by_q = sn.groupby(sn.index.to_period("Q"), sort=True).last()
        qmap = {q: float(v) for q, v in by_q.items() if pd.notna(v)}
        if not qmap:
            continue
        idx = out.index
        out[c] = [qmap.get(pd.Timestamp(t).to_period("Q"), float("nan")) for t in idx]
    return out


def dedupe_month_end_index(df: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar month-end: normalize the index and drop duplicate labels (``keep='last'``).

    Wide monthly builds can repeat a month when a joined table has duplicate ``month_end`` rows;
    this keeps CSVs and downstream charts from double-counting a month.
    """
    if df.empty:
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        return df.sort_index()
    out = df.sort_index().copy()
    name = out.index.name
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index, errors="coerce"), name=name).normalize()
    return out[~out.index.duplicated(keep="last")]


def load_macro_levels_monthly(
    observation_start: str = "2000-01-01",
    *,
    include_commodity_csvs: bool = True,
) -> pd.DataFrame:
    """Wide monthly panel: index = month-end (last observation in each calendar month per series)."""
    api_key = _require_fred_api_key()

    pieces: dict[str, pd.Series] = {}
    # gas, bls, legacy7222, mta, bart, OpenTable + optional commodity
    n_tasks = len(_SERIES_MONTHLY_LEVELS) + 6
    if include_commodity_csvs:
        n_tasks += 1
    max_workers = min(16, max(6, n_tasks))

    bls_m = pd.DataFrame()
    comm = pd.DataFrame()
    legacy_7222 = pd.Series(dtype="float64")
    mta_series = pd.Series(dtype="float64")
    bart_series = pd.Series(dtype="float64")
    opentable_frame = pd.DataFrame()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        f_meta: dict[object, str] = {}
        for sid, name in _SERIES_MONTHLY_LEVELS:
            fut = ex.submit(_fred_series_to_month_end_last, sid, name, observation_start, api_key)
            f_meta[fut] = "fred_piece"
        f_meta[ex.submit(load_gas_weekly_averaged_to_month, observation_start)] = "gas"
        f_meta[ex.submit(bls_data.load_bls_ces_monthly_dataframe, observation_start)] = "bls"
        f_meta[ex.submit(_legacy_mrtssm7222_monthly_last, observation_start, api_key)] = "legacy7222"
        f_meta[ex.submit(_load_mta_series_for_macro)] = "mta"
        f_meta[ex.submit(_load_bart_series_for_macro)] = "bart"
        f_meta[ex.submit(_load_opentable_frame_for_macro)] = "opentable"
        if include_commodity_csvs:
            f_meta[ex.submit(commodity_paste_csv.load_commodity_paste_monthly_dataframe)] = "commodity"

        for fut in as_completed(f_meta):
            tag = f_meta[fut]
            res = fut.result()
            if tag == "fred_piece":
                col_name, ser = res
                pieces[col_name] = ser
            elif tag == "gas":
                gas = res
                pieces[str(gas.name)] = gas
            elif tag == "bls":
                bls_m = res
            elif tag == "commodity":
                comm = res if isinstance(res, pd.DataFrame) else pd.DataFrame()
            elif tag == "legacy7222":
                legacy_7222 = res
            elif tag == "mta":
                mta_series = res
            elif tag == "bart":
                bart_series = res
            elif tag == "opentable":
                opentable_frame = res if isinstance(res, pd.DataFrame) else pd.DataFrame()

    df = pd.concat(pieces.values(), axis=1).sort_index()

    lm = "retail_sales_limited_service_eating_places_naics7222_millions_nsa"
    if lm in df.columns and not legacy_7222.empty:
        df[lm] = df[lm].combine_first(legacy_7222)

    # Paste commodities before BLS so ``commodity_*`` columns are not buried at the far right of CSVs.
    if include_commodity_csvs and isinstance(comm, pd.DataFrame) and not comm.empty:
        df = df.join(comm, how="left")

    if isinstance(bls_m, pd.DataFrame) and not bls_m.empty:
        df = df.join(bls_m, how="left")

    if not mta_series.empty:
        df = df.join(mta_series.to_frame(), how="left")

    if not bart_series.empty:
        df = df.join(bart_series.to_frame(), how="left")

    if not opentable_frame.empty:
        df = df.join(opentable_frame, how="left")

    df = dedupe_month_end_index(df)
    return expand_quarterly_levels_to_months_in_quarter(df)


def load_gas_weekly_averaged_to_month(observation_start: str = "2000-01-01") -> pd.Series:
    """Prefer ``GASREGCOVW`` then ``GASREGW``; weekly points averaged within calendar month."""
    api_key = _require_fred_api_key()

    for sid in ("GASREGCOVW", "GASREGW"):
        ser = pd.to_numeric(
            _fred_observations(sid, api_key, observation_start),
            errors="coerce",
        )
        ix = pd.to_datetime(ser.index)
        monthly = ser.groupby(ix.to_period("M")).mean()
        ts_index = monthly.index.to_timestamp(how="end").normalize()
        monthly = pd.Series(monthly.values, index=ts_index, name="gas_regular_us_avg_usd_per_gal")
        monthly = monthly.sort_index()
        if monthly.notna().any():
            return monthly.astype("float64")
    raise RuntimeError("Neither GASREGCOVW nor GASREGW returned usable gas price data")


def append_yoy_pct(
    df: pd.DataFrame, periods: int, suffix: str = "_yoy_pct"
) -> pd.DataFrame:
    """Adds YoY pct columns only for numeric level columns."""
    out = df.sort_index().copy()
    lvl = [
        c
        for c in out.columns
        if str(c) != "calendar_quarter"
        and not str(c).endswith(suffix)
        and pd.api.types.is_numeric_dtype(out[c])
    ]
    for c in lvl:
        out[f"{c}{suffix}"] = (
            out[c].pct_change(periods=periods, fill_method=None) * 100.0
        )
    return out


def aggregate_monthly_levels_to_calendar_quarter_last(monthly_levels: pd.DataFrame) -> pd.DataFrame:
    """Quarter-end panel (levels only). Adds ``calendar_quarter``.

    Most columns use the **last** calendar month in the quarter (aligned with FRED month-end
    conventions). Columns listed in ``_QUARTER_AGG_SUM_LEVEL_COLUMNS`` use **sum** across months
    in the quarter (e.g. total subway entry swipes in the quarter).
    """
    lvl = monthly_levels.drop(
        columns=[c for c in monthly_levels.columns if str(c).endswith("_yoy_pct")],
        errors="ignore",
    ).sort_index()
    sum_cols = [c for c in lvl.columns if c in _QUARTER_AGG_SUM_LEVEL_COLUMNS]
    last_cols = [c for c in lvl.columns if c not in set(sum_cols)]

    q_last = lvl[last_cols].resample("QE-DEC").last() if last_cols else pd.DataFrame()
    if sum_cols:
        q_sum = lvl[sum_cols].resample("QE-DEC").sum()
        q = q_last.join(q_sum, how="outer") if not q_last.empty else q_sum
    else:
        q = q_last

    prd = q.index.year.astype(str) + "Q" + q.index.quarter.astype(str)
    out = q.copy()
    out.insert(0, "calendar_quarter", prd.values)
    out.index.name = "quarter_end"
    return out


def add_precomputed_monthly_pct_to_calendar_quarter(
    calendar_quarter: pd.DataFrame,
    monthly: pd.DataFrame,
    columns: tuple[str, ...] = _PRECOMPUTED_MONTHLY_PCT_QUARTER_LAST_COLUMNS,
) -> pd.DataFrame:
    """Append precomputed monthly percent series to quarters using the last month in each quarter."""
    if calendar_quarter.empty or monthly.empty or not isinstance(monthly.index, pd.DatetimeIndex):
        return calendar_quarter
    present = [c for c in columns if c in monthly.columns]
    if not present:
        return calendar_quarter
    q = monthly[present].sort_index().resample("QE-DEC").last()
    q.index = pd.DatetimeIndex(q.index, name=calendar_quarter.index.name or "quarter_end").normalize()
    out = calendar_quarter.copy()
    for c in present:
        out[c] = q[c].reindex(out.index)
    return out


def add_plan_real_restaurant_demand(monthly_wide: pd.DataFrame) -> pd.DataFrame:
    """§12.5 spread: Census retail food services (NAICS 722, NSA) YoY − food-away-from-home CPI YoY (same month).

    Columns must already include ``*_yoy_pct`` for the two inputs; missing → NaNs.
    """

    retail_yoy = monthly_wide["retail_food_services_drinking_sales_millions_nsa_yoy_pct"]
    fa_yoy = monthly_wide["cpi_food_away_from_home_index_yoy_pct"]

    monthly_wide = monthly_wide.copy()
    monthly_wide["real_restaurant_demand_sales_minus_faho_cpi_yoy_spread_pct"] = (
        retail_yoy - fa_yoy
    )
    return monthly_wide


def add_workforce_pay_ces_cps_avg_yoy(wide: pd.DataFrame) -> pd.DataFrame:
    """Mean of CES all-private AHE YoY % and CPS median weekly YoY % (both already ``*_yoy_pct``).

    Requires both inputs non-missing for each month. Not an official BLS statistic.
    """

    ces = "fred_ces_all_private_avg_hourly_earnings_usd_sa_yoy_pct"
    cps = "cps_median_usual_weekly_nominal_ft_wage_salary_usd_yoy_pct"
    out_col = "workforce_pay_ces_cps_avg_yoy_pct"
    if ces not in wide.columns or cps not in wide.columns:
        return wide
    out = wide.copy()
    a = pd.to_numeric(out[ces], errors="coerce")
    b = pd.to_numeric(out[cps], errors="coerce")
    both = a.notna() & b.notna()
    out[out_col] = (a + b) / 2.0
    out.loc[~both, out_col] = float("nan")
    return out


def add_restaurant_sales_minus_headline_cpi_yoy_spread(wide: pd.DataFrame) -> pd.DataFrame:
    """Census NAICS 722 (NSA) retail YoY − CPI-U all-items YoY (headline inflation vs nominal sales).

    Same idea as :func:`add_plan_real_restaurant_demand` but vs **headline** CPI-U instead of
    food-away-from-home only. Skips if YoY inputs are missing (e.g. partial test frames).
    """

    rcol = "retail_food_services_drinking_sales_millions_nsa_yoy_pct"
    ccol = "cpi_u_all_items_sa_index_yoy_pct"
    if rcol not in wide.columns or ccol not in wide.columns:
        return wide
    out = wide.copy()
    out["real_restaurant_demand_sales_minus_headline_cpi_yoy_spread_pct"] = out[rcol] - out[ccol]
    return out


def spend_equiv_base_means(
    monthly_levels: pd.DataFrame,
    *,
    base_year: int = SPEND_EQUIV_BASE_YEAR,
    specs: tuple[tuple[str, str], ...] = SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS,
) -> dict[str, float]:
    """Mean of each **level** series over ``base_year`` calendar months (from ``month_end`` index).

    Used as denominators for ``1000 × level / base_mean`` spend-equivalent columns. Missing or
    zero-mean series are omitted from the returned dict.
    """
    if monthly_levels.empty:
        return {}
    if not isinstance(monthly_levels.index, pd.DatetimeIndex):
        return {}
    years = monthly_levels.index.year
    sub = monthly_levels.loc[years == int(base_year)]
    if sub.empty:
        return {}
    out: dict[str, float] = {}
    for level_col, _out_col in specs:
        if level_col not in sub.columns:
            continue
        v = pd.to_numeric(sub[level_col], errors="coerce")
        mu = float(v.mean(skipna=True))
        if pd.isna(mu) or mu == 0.0:
            continue
        out[level_col] = mu
    return out


def add_spend_equiv_vs_base_year_columns(
    wide: pd.DataFrame,
    bases: dict[str, float],
    *,
    anchor_usd: float = _SPEND_EQUIV_ANCHOR_USD,
    specs: tuple[tuple[str, str], ...] = SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS,
) -> pd.DataFrame:
    """Append ``equiv_usd_1000_at_<anchor_year>avg_*`` columns using ``anchor_usd * level / base_mean``."""
    if not bases:
        return wide
    out = wide.copy()
    for level_col, out_col in specs:
        if level_col not in out.columns or level_col not in bases:
            continue
        lvl = pd.to_numeric(out[level_col], errors="coerce")
        out[out_col] = anchor_usd * lvl / float(bases[level_col])
    return out


def build_annual_spend_equiv_table(
    monthly_wide: pd.DataFrame,
    *,
    specs: tuple[tuple[str, str], ...] = SPEND_EQUIV_AT_ANCHOR_YEAR_AVG_SPECS,
) -> pd.DataFrame:
    """One row per ``calendar_year``: **mean** of monthly spend-equivalent columns within that year."""
    m = monthly_wide.copy()
    if isinstance(m.index, pd.DatetimeIndex):
        m = m.reset_index()
    if "month_end" not in m.columns:
        # Unnamed month-end index becomes column ``0`` after ``reset_index()``.
        if len(m.columns) and pd.api.types.is_datetime64_any_dtype(m.iloc[:, 0]):
            m = m.rename(columns={m.columns[0]: "month_end"})
        else:
            return pd.DataFrame()
    equiv_cols = [oc for _lc, oc in specs if oc in m.columns]
    if not equiv_cols:
        return pd.DataFrame(columns=["calendar_year"])
    m["_cy"] = pd.to_datetime(m["month_end"], errors="coerce").dt.year
    g = m.groupby("_cy", as_index=False)[equiv_cols].mean(numeric_only=True)
    g = g.rename(columns={"_cy": "calendar_year"})
    return g.sort_values("calendar_year").reset_index(drop=True)


def load_macro_dataframes(
    observation_start: str = "2000-01-01",
    *,
    include_commodity_csvs: bool = True,
) -> dict[str, pd.DataFrame]:
    """Return keyed DataFrames::

        monthly                 — calendar month-end rows, levels + 12-m YoY + plan spread + anchor-year USD
        calendar_quarter        — quarter-end rows, levels + 4-quarter YoY + same USD anchors
        annual_<year>_spend_equiv — calendar-year rows; mean of monthly ``equiv_usd_1000_at_<year>avg_*``
            (restaurant inputs plus headline CPI-U all-items spend-equiv; see :data:`SPEND_EQUIV_AT_ANCHOR_ALL_SPECS`)
    """
    levels = load_macro_levels_monthly(
        observation_start,
        include_commodity_csvs=include_commodity_csvs,
    )
    bases = spend_equiv_base_means(
        levels, base_year=SPEND_EQUIV_BASE_YEAR, specs=SPEND_EQUIV_AT_ANCHOR_ALL_SPECS
    )
    monthly = append_yoy_pct(levels, periods=12, suffix="_yoy_pct")
    monthly = add_workforce_pay_ces_cps_avg_yoy(monthly)
    monthly = add_plan_real_restaurant_demand(monthly)
    monthly = add_restaurant_sales_minus_headline_cpi_yoy_spread(monthly)
    monthly = add_spend_equiv_vs_base_year_columns(
        monthly, bases, specs=SPEND_EQUIV_AT_ANCHOR_ALL_SPECS
    )
    monthly.index.name = "month_end"
    monthly = dedupe_month_end_index(monthly)

    q_lvl = aggregate_monthly_levels_to_calendar_quarter_last(levels)
    calendar_quarter = append_yoy_pct(q_lvl, periods=4, suffix="_yoy_pct")
    calendar_quarter = add_precomputed_monthly_pct_to_calendar_quarter(
        calendar_quarter, levels
    )
    calendar_quarter = add_restaurant_sales_minus_headline_cpi_yoy_spread(calendar_quarter)
    calendar_quarter = add_spend_equiv_vs_base_year_columns(
        calendar_quarter, bases, specs=SPEND_EQUIV_AT_ANCHOR_ALL_SPECS
    )

    annual = build_annual_spend_equiv_table(
        monthly, specs=SPEND_EQUIV_AT_ANCHOR_ALL_SPECS
    )
    annual_key = spend_equiv_annual_dict_key()

    return {
        "monthly": monthly,
        "calendar_quarter": calendar_quarter,
        annual_key: annual,
    }


def export_macro_csvs(
    dfs: dict[str, pd.DataFrame],
    directory: str | os.PathLike[str] | None = None,
    *,
    monthly_filename: str = "mlp_macro_monthly.csv",
    quarter_filename: str = "mlp_macro_calendar_quarter.csv",
    annual_filename: str | None = None,
) -> dict[str, Path]:
    """Write :func:`load_macro_dataframes` output to CSV (monthly + quarterly + optional annual table)."""
    root = Path(directory).expanduser().resolve() if directory is not None else _repo_root()
    root.mkdir(parents=True, exist_ok=True)
    p_m = root / monthly_filename
    p_q = root / quarter_filename
    dfs["monthly"].to_csv(p_m, index=True)
    dfs["calendar_quarter"].to_csv(p_q, index=True)
    out: dict[str, Path] = {"monthly": p_m, "calendar_quarter": p_q}
    annual_key = spend_equiv_annual_dict_key()
    ann = dfs.get(annual_key)
    if annual_filename is None:
        annual_filename = f"mlp_macro_annual_{int(SPEND_EQUIV_BASE_YEAR)}_spend_equiv.csv"
    if ann is not None and isinstance(ann, pd.DataFrame) and not ann.empty:
        p_a = root / annual_filename
        ann.to_csv(p_a, index=False)
        out[annual_key] = p_a
    return out


def describe_fred_key_source() -> str:
    """Where :func:`_require_fred_api_key` will read from first (no secret values)."""
    for env_path in (_repo_root() / ".env", Path.cwd() / ".env"):
        if _fred_key_from_dotenv_plain(env_path):
            return f".env ({env_path.resolve()})"
    if _fred_key_from_local_secrets_toml():
        return ".streamlit/secrets.toml (repo or cwd)"
    if os.environ.get("FRED_API_KEY"):
        return "shell environment variable FRED_API_KEY"
    try:
        import streamlit as st

        if "FRED_API_KEY" in st.secrets:
            return "st.secrets (Streamlit)"
    except Exception:
        pass
    return "(not found — would error on load)"


def probe_fred_api_key() -> int:
    """One minimal FRED request; prints source + HTTP outcome. Does not print the key. Returns 0 if OK."""
    try:
        key = _require_fred_api_key()
    except RuntimeError as e:
        print(f"FRED_API_KEY resolution failed:\n{e}")
        return 1

    print("Resolved FRED key (32 chars, validated).")
    print("First source with a FRED_API_KEY line:", describe_fred_key_source())
    repo_env = _repo_root() / ".env"
    if repo_env.is_file():
        nk = count_fred_api_key_lines_in_dotenv(repo_env)
        if nk > 1:
            print(
                f"Note: {repo_env} has {nk} non-empty `FRED_API_KEY=` lines; "
                "the **last** one is used — remove stale lines."
            )
    print("If that path is wrong, edit or remove it; `unset FRED_API_KEY` clears the shell.\n")

    try:
        _fred_get_observations_payload(
            "GNPCA",
            key,
            "2000-01-01",
            extra_params={"limit": 1, "sort_order": "desc"},
        )
    except RuntimeError as e:
        print(str(e))
        print("Key help: https://fredaccount.stlouisfed.org/apikeys (v2 Bearer + v1 fallback in code).")
        return 1

    print("FRED probe: OK (v2 or legacy API accepted the key for series GNPCA).")
    return 0


if __name__ == "__main__":
    dfs = load_macro_dataframes()
    print("Monthly:", dfs["monthly"].shape)
    print(dfs["monthly"].tail(2))
    print("Quarter:", dfs["calendar_quarter"].shape)
    print(dfs["calendar_quarter"][["calendar_quarter", "unemployment_rate_pct"]].tail(2))
    ann = dfs.get(spend_equiv_annual_dict_key())
    print(f"Annual {SPEND_EQUIV_BASE_YEAR}-anchor table:", getattr(ann, "shape", None))
    if isinstance(ann, pd.DataFrame) and not ann.empty:
        print(ann.tail(3))
