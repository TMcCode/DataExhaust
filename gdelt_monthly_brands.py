#!/usr/bin/env python3
"""GDELT DOC 2.0 brand buzz -> monthly CSV.

Free chain-specific proxy for media attention:

* ``*_article_count``: count of matching U.S.-source news articles.
* ``*_article_share_per_100k``: article count divided by GDELT's daily monitored-article
  denominator, scaled by 100,000. This helps adjust for total news-volume drift.
* ``*_avg_tone``: optional GDELT average tone, aggregated monthly using article-count weights.

The script uses GDELT timeline modes and sleeps between requests to respect the public API's
rate limit. It is intentionally conservative: one volume request and one tone request per brand.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests

_GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_HTTP_UA = "MLP_Restaurant_CaseStudy/gdelt_monthly_brands (research; contact local user)"
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class BrandQuery:
    ticker: str
    slug: str
    label: str
    query: str


DEFAULT_BRANDS: tuple[BrandQuery, ...] = (
    BrandQuery("CMG", "chipotle", "Chipotle", '"Chipotle" sourceCountry:US'),
    BrandQuery("CAVA", "cava", "CAVA", '"CAVA Group" sourceCountry:US'),
    BrandQuery("BROS", "dutch_bros", "Dutch Bros", '"Dutch Bros" sourceCountry:US'),
    BrandQuery("SHAK", "shake_shack", "Shake Shack", '"Shake Shack" sourceCountry:US'),
    BrandQuery("WING", "wingstop", "Wingstop", '"Wingstop" sourceCountry:US'),
    BrandQuery("SG", "sweetgreen", "Sweetgreen", '"Sweetgreen" sourceCountry:US'),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    p = urlparse(str(uri).strip())
    if p.scheme != "gs":
        raise ValueError(f"Expected gs:// URI, got {uri!r}")
    bucket = (p.netloc or "").strip()
    path = (p.path or "").lstrip("/")
    if not bucket:
        raise ValueError(f"Invalid GCS URI: {uri!r}")
    return bucket, path


def upload_csv_to_gcs(local_csv: Path, gs_uri: str) -> None:
    from google.cloud import storage
    from google.oauth2.service_account import Credentials

    bucket_name, blob_path = _parse_gs_uri(gs_uri)
    cred_path = None
    for candidate in ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_SHEETS_CREDENTIALS"):
        import os

        value = os.environ.get(candidate)
        if value and Path(value).is_file():
            cred_path = value
            break
    if cred_path is None:
        local_key = _repo_root() / "data-exhaust-key.json"
        if local_key.is_file():
            cred_path = str(local_key)
    if cred_path:
        creds = Credentials.from_service_account_file(
            str(cred_path), scopes=("https://www.googleapis.com/auth/devstorage.read_write",)
        )
        client = storage.Client(credentials=creds, project=creds.project_id)
    else:
        client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_path)
    blob.upload_from_filename(str(local_csv), content_type="text/csv")


def _gdelt_datetime(day: str | date | pd.Timestamp) -> str:
    ts = pd.Timestamp(day).normalize()
    return ts.strftime("%Y%m%d000000")


def _request_timeline(
    query: str,
    *,
    mode: str,
    start_date: str,
    end_date: str,
    sleep_s: float,
    max_retries: int = 6,
) -> dict:
    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "STARTDATETIME": _gdelt_datetime(start_date),
        "ENDDATETIME": _gdelt_datetime(end_date),
    }
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                _GDELT_DOC_URL,
                params=params,
                timeout=180,
                headers={"User-Agent": _HTTP_UA},
            )
            if resp.status_code in _RETRY_STATUSES:
                last_error = RuntimeError(
                    f"HTTP {resp.status_code}: {resp.text[:240].strip()}"
                )
                time.sleep(max(sleep_s, 5.0) * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            time.sleep(max(0.0, sleep_s))
            return data
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(max(sleep_s, 5.0) * (attempt + 1))
    raise RuntimeError(f"GDELT request failed for mode={mode!r}, query={query!r}") from last_error


def _timeline_series(payload: dict, series_name: str) -> pd.DataFrame:
    timeline = payload.get("timeline") or []
    hit = next((x for x in timeline if x.get("series") == series_name), None)
    if not hit:
        return pd.DataFrame(columns=["date", "value", "norm"])
    rows = hit.get("data") or []
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["date", "value", "norm"])
    out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True).dt.tz_convert(None)
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    if "norm" in out.columns:
        out["norm"] = pd.to_numeric(out["norm"], errors="coerce")
    else:
        out["norm"] = np.nan
    return out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_brand_daily(
    brand: BrandQuery,
    *,
    start_date: str,
    end_date: str,
    sleep_s: float,
    include_tone: bool = False,
) -> pd.DataFrame:
    vol = _request_timeline(
        brand.query,
        mode="timelinevolraw",
        start_date=start_date,
        end_date=end_date,
        sleep_s=sleep_s,
    )
    v = _timeline_series(vol, "Article Count").rename(
        columns={"value": "article_count", "norm": "gdelt_total_article_count"}
    )
    if include_tone:
        tone = _request_timeline(
            brand.query,
            mode="timelinetone",
            start_date=start_date,
            end_date=end_date,
            sleep_s=sleep_s,
        )
        t = _timeline_series(tone, "Average Tone").rename(columns={"value": "avg_tone"})
        daily = v.merge(t[["date", "avg_tone"]], on="date", how="outer").sort_values("date")
    else:
        daily = v.sort_values("date")
        daily["avg_tone"] = np.nan
    daily["ticker"] = brand.ticker
    daily["brand"] = brand.label
    daily["slug"] = brand.slug
    daily["query"] = brand.query
    daily["article_count"] = pd.to_numeric(daily["article_count"], errors="coerce").fillna(0.0)
    daily["gdelt_total_article_count"] = pd.to_numeric(
        daily["gdelt_total_article_count"], errors="coerce"
    )
    daily["avg_tone"] = pd.to_numeric(daily["avg_tone"], errors="coerce")
    return daily.reset_index(drop=True)


def monthly_from_daily(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for (ticker, brand, slug), g in daily.groupby(["ticker", "brand", "slug"], sort=False):
        work = g.copy()
        work["_month"] = pd.to_datetime(work["date"], errors="coerce").dt.to_period("M")
        for month, m in work.groupby("_month", sort=True):
            counts = pd.to_numeric(m["article_count"], errors="coerce").fillna(0.0)
            norm = pd.to_numeric(m["gdelt_total_article_count"], errors="coerce")
            tone = pd.to_numeric(m["avg_tone"], errors="coerce")
            tone_weight = counts.where(tone.notna(), 0.0)
            tone_denom = float(tone_weight.sum())
            avg_tone = (
                float((tone.fillna(0.0) * tone_weight).sum() / tone_denom)
                if tone_denom > 0
                else float(tone.mean(skipna=True))
            )
            article_count = float(counts.sum())
            norm_sum = float(norm.sum(skipna=True))
            rows.append(
                {
                    "month": month.to_timestamp(how="start").strftime("%Y-%m"),
                    "ticker": ticker,
                    "brand": brand,
                    "slug": slug,
                    "gdelt_article_count": int(article_count),
                    "gdelt_total_article_count": int(norm_sum) if np.isfinite(norm_sum) else np.nan,
                    "gdelt_article_share_per_100k": (
                        article_count / norm_sum * 100000.0 if norm_sum > 0 else np.nan
                    ),
                    "gdelt_avg_tone": avg_tone,
                }
            )
    out = pd.DataFrame(rows).sort_values(["ticker", "month"]).reset_index(drop=True)
    out["gdelt_article_share_per_100k"] = out["gdelt_article_share_per_100k"].round(4)
    out["gdelt_avg_tone"] = out["gdelt_avg_tone"].round(4)
    return out


def wide_monthly(monthly_long: pd.DataFrame) -> pd.DataFrame:
    if monthly_long.empty:
        return pd.DataFrame(columns=["month"])
    pieces: list[pd.DataFrame] = []
    metrics = (
        "gdelt_article_count",
        "gdelt_article_share_per_100k",
        "gdelt_avg_tone",
    )
    for metric in metrics:
        p = monthly_long.pivot(index="month", columns="ticker", values=metric)
        p.columns = [f"{str(c).lower()}_{metric}" for c in p.columns]
        pieces.append(p)
    out = pd.concat(pieces, axis=1).sort_index()
    count_cols = [c for c in out.columns if c.endswith("_gdelt_article_count")]
    share_cols = [c for c in out.columns if c.endswith("_gdelt_article_share_per_100k")]
    for c in count_cols + share_cols:
        out[f"{c}_yoy_pct"] = (
            (pd.to_numeric(out[c], errors="coerce") - pd.to_numeric(out[c], errors="coerce").shift(12))
            / pd.to_numeric(out[c], errors="coerce").shift(12)
            * 100.0
        ).replace([np.inf, -np.inf], np.nan).round(2)
    out = out.reset_index()
    return out


def fetch_monthly_brand_panel(
    *,
    start_date: str,
    end_date: str,
    brands: Sequence[BrandQuery] = DEFAULT_BRANDS,
    sleep_s: float = 5.5,
    cache_dir: Path | str | None = "data/gdelt_cache",
    include_tone: bool = False,
    verbose: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily_frames: list[pd.DataFrame] = []
    cache_root = Path(cache_dir).expanduser().resolve() if cache_dir else None
    if cache_root:
        cache_root.mkdir(parents=True, exist_ok=True)
    for brand in brands:
        cache_path = (
            cache_root
            / (
                f"{brand.slug}_{pd.Timestamp(start_date).strftime('%Y%m%d')}_"
                f"{pd.Timestamp(end_date).strftime('%Y%m%d')}_"
                f"{'tone' if include_tone else 'volume'}_daily.csv"
            )
            if cache_root
            else None
        )
        if cache_path is not None and cache_path.is_file():
            if verbose:
                print(f"GDELT: using cached {brand.ticker} / {brand.label}", flush=True)
            daily_frames.append(pd.read_csv(cache_path, parse_dates=["date"]))
            continue
        if verbose:
            print(f"GDELT: fetching {brand.ticker} / {brand.label}", flush=True)
        daily = fetch_brand_daily(
            brand,
            start_date=start_date,
            end_date=end_date,
            sleep_s=sleep_s,
                include_tone=include_tone,
        )
        if cache_path is not None:
            daily.to_csv(cache_path, index=False)
        daily_frames.append(daily)
    daily = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    monthly_long = monthly_from_daily(daily)
    monthly_wide = wide_monthly(monthly_long)
    return daily, monthly_long, monthly_wide


def write_gdelt_monthly_csvs(
    output: Path | str = "gdelt_fast_casual_monthly.csv",
    *,
    long_output: Path | str | None = "data/gdelt_fast_casual_monthly_long.csv",
    daily_output: Path | str | None = None,
    start_date: str = "2022-01-01",
    end_date: str | None = None,
    sleep_s: float = 5.5,
    cache_dir: Path | str | None = "data/gdelt_cache",
    include_tone: bool = False,
    upload_gcs: str | None = None,
    verbose: bool = True,
) -> dict[str, Path]:
    end = end_date or date.today().isoformat()
    daily, monthly_long, monthly_wide = fetch_monthly_brand_panel(
        start_date=start_date,
        end_date=end,
        sleep_s=sleep_s,
        cache_dir=cache_dir,
        include_tone=include_tone,
        verbose=verbose,
    )
    out_paths: dict[str, Path] = {}
    out = Path(output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    monthly_wide.to_csv(out, index=False)
    out_paths["wide"] = out
    if long_output:
        p = Path(long_output).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        monthly_long.to_csv(p, index=False)
        out_paths["long"] = p
    if daily_output:
        p = Path(daily_output).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        daily.to_csv(p, index=False)
        out_paths["daily"] = p
    if verbose:
        print(f"Wrote GDELT wide CSV: {out} ({len(monthly_wide)} rows)")
        if "long" in out_paths:
            print(f"Wrote GDELT long CSV: {out_paths['long']} ({len(monthly_long)} rows)")
        if "daily" in out_paths:
            print(f"Wrote GDELT daily CSV: {out_paths['daily']} ({len(daily)} rows)")
    if upload_gcs:
        upload_csv_to_gcs(out, upload_gcs)
        if verbose:
            print(f"Uploaded GDELT wide CSV to {upload_gcs}")
    return out_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GDELT monthly brand-buzz CSVs.")
    parser.add_argument("-o", "--output", default="gdelt_fast_casual_monthly.csv")
    parser.add_argument("--long-output", default="data/gdelt_fast_casual_monthly_long.csv")
    parser.add_argument("--daily-output", default=None)
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--sleep", type=float, default=5.5)
    parser.add_argument(
        "--include-tone",
        action="store_true",
        help="Also request GDELT tone timelines. Slower and more likely to hit public API throttles.",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/gdelt_cache",
        help="Per-brand daily cache directory; reruns reuse successful brand pulls.",
    )
    parser.add_argument("--upload-gcs", default=None, metavar="gs://BUCKET/path.csv")
    args = parser.parse_args()
    write_gdelt_monthly_csvs(
        args.output,
        long_output=args.long_output,
        daily_output=args.daily_output,
        start_date=args.start_date,
        end_date=args.end_date,
        sleep_s=args.sleep,
        cache_dir=args.cache_dir,
        include_tone=bool(args.include_tone),
        upload_gcs=args.upload_gcs,
        verbose=True,
    )


if __name__ == "__main__":
    main()
