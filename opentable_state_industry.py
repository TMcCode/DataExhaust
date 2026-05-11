"""OpenTable State of Industry monthly seated-diners cache.

Builds a small U.S.-only monthly CSV from OpenTable's State of the Restaurant
Industry dashboard payload. The value is already a YoY percent change, so
``macro_data`` joins it as a precomputed percent metric rather than deriving a
second YoY transform.
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

SOURCE_PAGE = "https://www.opentable.com/c/state-of-industry/#seated-diners-chart"
ENDPOINT = "https://www.opentable.com/c/wapi/r9-ot-soti/v1/data"
_DEFAULT_FILENAME = "opentable_us_seated_diners_monthly.csv"
_DEFAULT_CITY_CONSTITUENTS_FILENAME = "opentable_fast_casual_city_constituents_monthly.csv"
_HTTP_UA = (
    "MLP_Restaurant_CaseStudy/opentable_state_industry "
    "(authorized OpenTable data extraction)"
)

OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN = (
    "opentable_us_seated_diners_online_reservations_yoy_pct"
)
OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN = (
    "opentable_fast_casual_exposed_city_index_yoy_pct"
)
FAST_CASUAL_EXPOSED_CITY_BASKET: tuple[str, ...] = (
    # Urban/professional lunch, coastal, and Sunbelt growth markets where fast-casual chains
    # such as CMG, CAVA, SG, SHAK, WING, and BROS are most strategically relevant.
    "Atlanta",
    "Austin",
    "Boston",
    "Charlotte",
    "Chicago",
    "Dallas",
    "Denver",
    "Los Angeles",
    "Miami",
    "Nashville",
    "New York",
    "Philadelphia",
    "Phoenix",
    "Raleigh",
    "San Diego",
    "San Francisco",
    "Seattle",
    "Tampa",
    "Washington",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def default_monthly_csv_path() -> Path:
    return _repo_root() / "data" / _DEFAULT_FILENAME


def default_city_constituents_csv_path() -> Path:
    return _repo_root() / "data" / _DEFAULT_CITY_CONSTITUENTS_FILENAME


def opentable_monthly_csv_uri_from_env() -> str | None:
    v = os.environ.get("OPENTABLE_US_SEATED_DINERS_MONTHLY_CSV", "").strip()
    return v or None


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    p = urlparse(str(uri).strip())
    if p.scheme != "gs":
        raise ValueError(f"Expected gs:// URI, got {uri!r}")
    bucket = (p.netloc or "").strip()
    path = (p.path or "").lstrip("/")
    if not bucket:
        raise ValueError(f"Invalid GCS URI: {uri!r}")
    return bucket, path


def _storage_client(*, write: bool = False):
    from google.cloud import storage
    from google.oauth2.service_account import Credentials

    scopes = (
        ("https://www.googleapis.com/auth/devstorage.read_write",)
        if write
        else ("https://www.googleapis.com/auth/devstorage.read_only",)
    )
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
        "GOOGLE_SHEETS_CREDENTIALS"
    )
    if not cred_path:
        local_key = _repo_root() / "data-exhaust-key.json"
        if local_key.is_file():
            cred_path = str(local_key)
    if cred_path and Path(cred_path).is_file():
        creds = Credentials.from_service_account_file(str(cred_path), scopes=scopes)
        return storage.Client(credentials=creds, project=creds.project_id)
    return storage.Client()


def _read_csv_from_gcs(gs_uri: str) -> pd.DataFrame:
    try:
        bucket_name, blob_path = _parse_gs_uri(gs_uri)
        client = _storage_client(write=False)
        blob = client.bucket(bucket_name).blob(blob_path)
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


def upload_csv_to_gcs(local_csv: Path, gs_uri: str) -> None:
    bucket_name, blob_path = _parse_gs_uri(gs_uri)
    client = _storage_client(write=True)
    blob = client.bucket(bucket_name).blob(blob_path)
    blob.upload_from_filename(str(local_csv), content_type="text/csv")


def fetch_dashboard_payload() -> dict:
    resp = requests.get(
        ENDPOINT,
        timeout=30,
        headers={"User-Agent": _HTTP_UA, "Accept": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()


def us_monthly_dataframe_from_payload(payload: dict) -> pd.DataFrame:
    seated = payload.get("seatedDiners") or {}
    month_ends = seated.get("monthlyHeaders") or []
    countries = seated.get("countries") or []
    us = next(
        (
            x
            for x in countries
            if str(x.get("name", "")).strip().lower() == "united states"
            or str(x.get("countryId", "")).strip() == "840"
        ),
        None,
    )
    if not us:
        raise ValueError("OpenTable payload does not contain United States monthly data")
    values = us.get("monthlyYoY") or []
    if len(month_ends) != len(values):
        raise ValueError(
            f"OpenTable monthly length mismatch: {len(month_ends)} dates vs {len(values)} values"
        )
    period_end = pd.to_datetime(month_ends, errors="coerce").normalize()
    us_df = pd.DataFrame(
        {
            "month_end": (period_end + pd.offsets.MonthEnd(0)).normalize(),
            "opentable_period_end": period_end,
            OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN: pd.to_numeric(
                pd.Series(values), errors="coerce"
            ),
            "source": "OpenTable State of the Restaurant Industry",
            "source_page": SOURCE_PAGE,
        }
    )
    index_df = fast_casual_city_index_dataframe_from_payload(payload)
    out = us_df.merge(
        index_df[
            [
                "month_end",
                OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN,
                "fast_casual_exposed_city_count",
            ]
        ],
        on="month_end",
        how="left",
    )
    return normalize_monthly_dataframe(out)


def city_constituents_dataframe_from_payload(
    payload: dict,
    cities: tuple[str, ...] = FAST_CASUAL_EXPOSED_CITY_BASKET,
) -> pd.DataFrame:
    seated = payload.get("seatedDiners") or {}
    month_ends = seated.get("monthlyHeaders") or []
    period_end = pd.to_datetime(month_ends, errors="coerce").normalize()
    city_set = {str(c).strip() for c in cities}
    rows: list[dict[str, object]] = []
    for city in seated.get("cities") or []:
        name = str(city.get("name", "")).strip()
        country = str(city.get("country", "")).strip()
        if country != "United States" or name not in city_set:
            continue
        values = city.get("monthlyYoY") or []
        if len(values) != len(period_end):
            raise ValueError(
                f"OpenTable monthly length mismatch for {name}: "
                f"{len(period_end)} dates vs {len(values)} values"
            )
        for dt, value in zip(period_end, values):
            rows.append(
                {
                    "month_end": (dt + pd.offsets.MonthEnd(0)).normalize(),
                    "opentable_period_end": dt,
                    "city": name,
                    "country": country,
                    "monthly_yoy_pct": value,
                    "source": "OpenTable State of the Restaurant Industry",
                    "source_page": SOURCE_PAGE,
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "month_end",
                "opentable_period_end",
                "city",
                "country",
                "monthly_yoy_pct",
                "source",
                "source_page",
            ]
        )
    out = pd.DataFrame(rows)
    out["month_end"] = pd.to_datetime(out["month_end"], errors="coerce").dt.normalize()
    out["opentable_period_end"] = pd.to_datetime(
        out["opentable_period_end"], errors="coerce"
    ).dt.normalize()
    out["monthly_yoy_pct"] = pd.to_numeric(out["monthly_yoy_pct"], errors="coerce")
    return out.sort_values(["month_end", "city"]).reset_index(drop=True)


def fast_casual_city_index_dataframe_from_payload(payload: dict) -> pd.DataFrame:
    city_df = city_constituents_dataframe_from_payload(payload)
    if city_df.empty:
        return pd.DataFrame(
            columns=[
                "month_end",
                OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN,
                "fast_casual_exposed_city_count",
            ]
        )
    grouped = city_df.groupby("month_end", as_index=False).agg(
        **{
            OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN: (
                "monthly_yoy_pct",
                "mean",
            ),
            "fast_casual_exposed_city_count": ("city", "nunique"),
        }
    )
    grouped[OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN] = grouped[
        OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN
    ].round(2)
    return grouped.sort_values("month_end").reset_index(drop=True)


def us_monthly_dataframe_from_raw_json(path: str | os.PathLike[str]) -> pd.DataFrame:
    raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload = raw.get("payload", raw) if isinstance(raw, dict) else raw
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return us_monthly_dataframe_from_payload(payload)


def normalize_monthly_dataframe(raw: pd.DataFrame) -> pd.DataFrame:
    cols = ["month_end", OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN]
    if raw.empty or any(c not in raw.columns for c in cols):
        return pd.DataFrame(columns=cols)
    df = raw.copy()
    df["month_end"] = pd.to_datetime(df["month_end"], errors="coerce").dt.normalize()
    df[OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN] = pd.to_numeric(
        df[OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN],
        errors="coerce",
    )
    if OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN in df.columns:
        df[OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN] = pd.to_numeric(
            df[OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN],
            errors="coerce",
        )
    out_cols = cols + [
        c
        for c in (
            OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN,
            "fast_casual_exposed_city_count",
            "opentable_period_end",
            "source",
            "source_page",
        )
        if c in df.columns
    ]
    return (
        df[out_cols]
        .dropna(subset=["month_end"])
        .sort_values("month_end")
        .drop_duplicates(subset=["month_end"], keep="last")
        .reset_index(drop=True)
    )


def load_monthly_dataframe(path: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    if path is not None and str(path).strip():
        return normalize_monthly_dataframe(_read_csv_any(str(path).strip()))
    env_uri = opentable_monthly_csv_uri_from_env()
    if env_uri:
        return normalize_monthly_dataframe(_read_csv_any(env_uri))
    p = default_monthly_csv_path()
    if not p.is_file():
        return pd.DataFrame(
            columns=["month_end", OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN]
        )
    return normalize_monthly_dataframe(pd.read_csv(p))


def monthly_series_for_macro_join(path: str | os.PathLike[str] | None = None) -> pd.Series:
    df = load_monthly_dataframe(path)
    name = OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN
    if df.empty:
        return pd.Series(dtype="float64", name=name)
    return pd.Series(
        df[name].values,
        index=pd.DatetimeIndex(df["month_end"]),
        name=name,
    ).sort_index()


def monthly_dataframe_for_macro_join(path: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    df = load_monthly_dataframe(path)
    cols = [
        OPENTABLE_US_SEATED_DINERS_MONTHLY_YOY_COLUMN,
        OPENTABLE_FAST_CASUAL_EXPOSED_CITY_INDEX_MONTHLY_YOY_COLUMN,
    ]
    present = [c for c in cols if c in df.columns]
    if df.empty or not present:
        return pd.DataFrame(columns=cols)
    out = df[["month_end", *present]].copy()
    out = out.set_index(pd.DatetimeIndex(out["month_end"])).drop(columns=["month_end"])
    return out.sort_index().astype("float64")


def write_us_monthly_csv(
    output: str | os.PathLike[str] | None = None,
    *,
    raw_json: str | os.PathLike[str] | None = None,
    fetch: bool = False,
    upload_gcs: str | None = None,
) -> Path:
    if fetch:
        df = us_monthly_dataframe_from_payload(fetch_dashboard_payload())
    else:
        raw_path = (
            Path(raw_json).expanduser()
            if raw_json
            else _repo_root() / "data" / "opentable_state_of_industry_raw.json"
        )
        df = us_monthly_dataframe_from_raw_json(raw_path)
    out = Path(output).expanduser().resolve() if output else default_monthly_csv_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    if upload_gcs:
        upload_csv_to_gcs(out, upload_gcs)
    return out


def write_city_constituents_csv(
    output: str | os.PathLike[str] | None = None,
    *,
    raw_json: str | os.PathLike[str] | None = None,
    fetch: bool = False,
    upload_gcs: str | None = None,
) -> Path:
    payload = (
        fetch_dashboard_payload()
        if fetch
        else json.loads(
            Path(
                raw_json
                if raw_json
                else _repo_root() / "data" / "opentable_state_of_industry_raw.json"
            )
            .expanduser()
            .read_text(encoding="utf-8")
        )
    )
    if isinstance(payload, dict) and "payload" in payload:
        payload = payload["payload"]
    df = city_constituents_dataframe_from_payload(payload)
    out = (
        Path(output).expanduser().resolve()
        if output
        else default_city_constituents_csv_path()
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    if upload_gcs:
        upload_csv_to_gcs(out, upload_gcs)
    return out


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Build OpenTable U.S. seated diners monthly YoY CSV.")
    ap.add_argument(
        "--output",
        default=None,
        help=f"Output CSV (default: {default_monthly_csv_path()})",
    )
    ap.add_argument(
        "--raw-json",
        default=None,
        help="Raw OpenTable JSON wrapper/payload to transform",
    )
    ap.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch the dashboard JSON endpoint instead of using raw JSON",
    )
    ap.add_argument(
        "--upload-gcs",
        default=None,
        metavar="gs://BUCKET/path.csv",
        help="Upload written CSV to GCS",
    )
    ap.add_argument(
        "--city-constituents-output",
        default=None,
        help=f"Write city constituent CSV (default: {default_city_constituents_csv_path()})",
    )
    ap.add_argument(
        "--city-constituents-upload-gcs",
        default=None,
        metavar="gs://BUCKET/path.csv",
        help="Upload city constituent CSV to GCS",
    )
    args = ap.parse_args()
    path = write_us_monthly_csv(
        args.output,
        raw_json=args.raw_json,
        fetch=bool(args.fetch),
        upload_gcs=args.upload_gcs,
    )
    df = load_monthly_dataframe(path)
    print(f"Wrote {len(df)} rows -> {path}")
    if args.upload_gcs:
        print(f"Uploaded -> {args.upload_gcs}")
    city_path = write_city_constituents_csv(
        args.city_constituents_output,
        raw_json=args.raw_json,
        fetch=bool(args.fetch),
        upload_gcs=args.city_constituents_upload_gcs,
    )
    city_df = pd.read_csv(city_path)
    print(f"Wrote {len(city_df)} city constituent rows -> {city_path}")
    if args.city_constituents_upload_gcs:
        print(f"Uploaded city constituents -> {args.city_constituents_upload_gcs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
