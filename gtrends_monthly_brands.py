#!/usr/bin/env python3
"""
Google Trends → monthly CSV: one API pull per search term.

Each column is 0–100 **relative to that term’s own peak** over the requested
window (separate pulls). YoY % is computed on those raw monthly levels.

**Long history (e.g. back to 2018):** use ``--start-date 2018-01-01`` (and optional ``--end-date``;
defaults to today). Google may rate-limit long pulls; sleep between terms. To **archive** older
months in GCS, keep a CSV there and pass ``--merge-csv`` when re-pulling so overlapping months stay
fresh while earlier months back-fill. Streamlit can read a stitched file via ``MLP_GTRENDS_APPEND_CSV``.

Builds **fast_casual_index**: equal-weight mean of **z-scores** (within each
series across time) of the directed components — brand terms as-is,
**Recipe** (and **meal prep**, home-cooking substitute) inverted where noted.
Terms with **`include_in_composite=False`** are still pulled into the CSV but
omitted from the index (e.g. **McDonald's** as a raw benchmark). Adjust flags in
`DEFAULT_COMPONENTS` as you like.

**Composite YoY:** the index is centered near zero, so percent YoY is unstable.
We export **fast_casual_index_yoy_chg** = index minus its value 12 months ago
(same units as the index).

Requires: pip install pytrends
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import sleep
from typing import Sequence
from urllib.parse import urlparse

import numpy as np
import pandas as pd

try:
    from pytrends.exceptions import TooManyRequestsError
    from pytrends.request import TrendReq
except ImportError:
    print("Install pytrends: pip install pytrends", file=sys.stderr)
    sys.exit(1)


@dataclass(frozen=True)
class Component:
    """CSV column name for raw monthly interest + Google Trends query string."""

    col: str
    query: str
    invert: bool = False
    """If True, use (-interest) before z-scoring for the composite index."""
    include_in_composite: bool = True
    """If False, series is fetched and in CSV/YoY but excluded from fast_casual_index."""


# Edit this list to add/remove terms. Composite uses only rows with include_in_composite=True.
DEFAULT_COMPONENTS: tuple[Component, ...] = (
    Component("chipotle", "Chipotle"),
    Component("sweetgreen", "Sweetgreen"),
    Component("cava", "CAVA"),
    Component("jersey_mikes_subs", "Jersey Mike's Subs"),
    Component("shake_shack", "Shake Shack"),
    Component("panera_bread", "Panera Bread"),
    Component("recipe", "Recipe", invert=True),
    Component("food_near_me", "Food near me"),
    # Category / out-of-home demand
    Component("fast_casual", "fast casual"),
    Component("restaurants_near_me", "restaurants near me"),
    Component("healthy_fast_food", "healthy fast food"),
    # Health / at-home / weight (pulled for testing; not in composite)
    Component("microwavable_meals", "microwavable meals", include_in_composite=False),
    Component("weight_loss", "weight loss", include_in_composite=False),
    Component("glp1", "glp1", include_in_composite=False),
    Component("how_to_lose_weight", "how to lose weight", include_in_composite=False),
    Component("healthy_food", "healthy food", include_in_composite=False),
    Component("salad_near_me", "salad near me"),
    Component("takeout", "takeout"),
    Component("delivery", "delivery"),
    # Substitution (invert: more at-home meal kits = drag on index)
    Component("meal_prep", "meal prep", invert=True),
    # Value / trade-down (raw + YoY only; flip invert if you want them as headwinds)
    Component("cheap_eats", "cheap eats"),
    Component("dollar_menu", "dollar menu"),
    # Benchmark: not mixed into composite by default
    Component("mcdonalds", "McDonald's", include_in_composite=False),
)


def _interest_single(pytrends: TrendReq, query: str, timeframe: str, geo: str) -> pd.DataFrame:
    pytrends.build_payload([query], timeframe=timeframe, geo=geo)
    df = pytrends.interest_over_time()
    if df is None or df.empty:
        raise RuntimeError(f"No data returned for query {query!r}")
    df = df.drop(columns=["isPartial"], errors="ignore").astype(float)
    if query not in df.columns and len(df.columns) == 1:
        df = df.rename(columns={df.columns[0]: query})
    if query not in df.columns:
        raise RuntimeError(f"Expected column {query!r}, got {df.columns.tolist()}")
    return df[[query]]


def fetch_single_with_retries(
    pytrends: TrendReq,
    query: str,
    *,
    timeframe: str,
    geo: str,
    sleep_after: float,
    max_retries: int = 8,
) -> pd.DataFrame:
    delay = 10.0
    last_err: Exception | None = None
    for _ in range(max_retries):
        try:
            df = _interest_single(pytrends, query, timeframe, geo)
            sleep(sleep_after)
            return df
        except TooManyRequestsError as e:
            last_err = e
            sleep(delay)
            delay = min(delay * 1.6, 120.0)
    raise RuntimeError(f"Google Trends rate-limited for {query!r}") from last_err


def weekly_panel(
    pytrends: TrendReq,
    components: Sequence[Component],
    *,
    timeframe: str,
    geo: str,
    sleep_after: float,
) -> pd.DataFrame:
    frames: list[pd.Series] = []
    for c in components:
        df = fetch_single_with_retries(
            pytrends, c.query, timeframe=timeframe, geo=geo, sleep_after=sleep_after
        )
        frames.append(df.iloc[:, 0].rename(c.col))
    return pd.concat(frames, axis=1).sort_index()


def monthly_from_weekly(weekly: pd.DataFrame) -> pd.DataFrame:
    return weekly.resample("MS").mean().round(1)


def zscore(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    std = float(s.std(ddof=0))
    if not np.isfinite(std) or std == 0.0:
        return pd.Series(0.0, index=s.index)
    return (s - float(s.mean())) / std


def composite_subset(components: Sequence[Component]) -> tuple[Component, ...]:
    return tuple(c for c in components if c.include_in_composite)


def directed_for_index(monthly: pd.DataFrame, components: Sequence[Component]) -> pd.DataFrame:
    out = pd.DataFrame(index=monthly.index)
    for c in components:
        if c.col not in monthly.columns:
            raise KeyError(f"Missing column {c.col!r} for composite")
        x = monthly[c.col].astype(float)
        out[c.col] = -x if c.invert else x
    return out


def fast_casual_index(monthly: pd.DataFrame, components: Sequence[Component]) -> pd.Series:
    directed = directed_for_index(monthly, composite_subset(components))
    z = pd.DataFrame({col: zscore(directed[col]) for col in directed.columns}, index=directed.index)
    return z.mean(axis=1).rename("fast_casual_index")


def add_yoy(monthly: pd.DataFrame) -> pd.DataFrame:
    yoy = (monthly - monthly.shift(12)) / monthly.shift(12) * 100.0
    yoy.columns = [f"{c}_yoy_pct" for c in monthly.columns]
    return yoy


def merge_monthly_with_history_csv(
    monthly_new: pd.DataFrame,
    history_path: Path,
    components: Sequence[Component],
) -> pd.DataFrame:
    """Overlay a fresh monthly panel onto an older CSV (e.g. GCS download); recompute index/YoY on the union."""
    raw_cols = [c.col for c in components]
    old = pd.read_csv(history_path)
    if "month" not in old.columns:
        raise ValueError(f"History CSV missing month column: {history_path}")
    use_cols = ["month"] + [c for c in raw_cols if c in old.columns]
    old = old[use_cols].copy()
    old["_p"] = pd.to_datetime(old["month"], format="%Y-%m", errors="coerce").dt.to_period("M")
    old = old.dropna(subset=["_p"]).drop(columns=["month"]).set_index("_p")

    m = monthly_new.copy()
    m.index = pd.DatetimeIndex(m.index).to_period("M")

    full_idx = m.index.union(old.index).sort_values()
    combined = pd.DataFrame(index=full_idx)
    for c in raw_cols:
        a = old[c] if c in old.columns else pd.Series(np.nan, index=full_idx)
        b = m[c] if c in m.columns else pd.Series(np.nan, index=full_idx)
        combined[c] = b.reindex(full_idx).combine_first(a.reindex(full_idx))

    combined.index = combined.index.to_timestamp(how="start")
    return combined.sort_index()


def _parse_gs_uri(uri: str) -> tuple[str, str]:
    u = str(uri).strip()
    p = urlparse(u)
    if p.scheme != "gs":
        raise ValueError(f"Expected gs:// URI, got {uri!r}")
    bucket = (p.netloc or "").strip()
    path = (p.path or "").lstrip("/")
    if not bucket:
        raise ValueError(f"Invalid GCS URI: {uri!r}")
    return bucket, path


def upload_csv_to_gcs(local_csv: Path, gs_uri: str) -> None:
    """Upload ``local_csv`` to ``gs://bucket/path.csv`` (needs ``google-cloud-storage`` + write IAM)."""
    import os

    from google.cloud import storage
    from google.oauth2.service_account import Credentials

    bucket_name, blob_path = _parse_gs_uri(gs_uri)
    p = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if p and Path(p).is_file():
        creds = Credentials.from_service_account_file(
            str(p), scopes=("https://www.googleapis.com/auth/devstorage.read_write",)
        )
        client = storage.Client(credentials=creds, project=creds.project_id)
    else:
        client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(str(local_csv), content_type="text/csv")


def write_gtrends_monthly_csv(
    output: Path | str,
    *,
    geo: str = "US",
    timeframe: str = "today 5-y",
    start_date: str | None = None,
    end_date: str | None = None,
    merge_csv: Path | str | None = None,
    upload_gcs: str | None = None,
    sleep_after: float = 5.0,
    components: Sequence[Component] | None = None,
    verbose: bool = True,
) -> Path:
    """Pull Google Trends for each :data:`DEFAULT_COMPONENTS` term, write monthly + YoY + composite CSV.

    Also used by :mod:`load_mlp_master` (``--gtrends``). Requires ``pytrends`` and network access.
    """
    if bool(start_date) ^ bool(end_date):
        if start_date and not end_date:
            end_date = str(date.today())
        elif end_date and not start_date:
            raise ValueError("start_date is required when end_date is set")

    if start_date and end_date:
        tf = f"{start_date} {end_date}"
    else:
        tf = str(timeframe)

    comp = tuple(components) if components is not None else DEFAULT_COMPONENTS
    pytrends = TrendReq(hl="en-US", tz=360)

    weekly = weekly_panel(
        pytrends,
        comp,
        timeframe=tf,
        geo=geo,
        sleep_after=sleep_after,
    )
    monthly = monthly_from_weekly(weekly)
    if merge_csv:
        hist = Path(merge_csv).expanduser().resolve()
        if not hist.is_file():
            raise FileNotFoundError(f"merge_csv not found: {hist}")
        monthly = merge_monthly_with_history_csv(monthly, hist, comp)

    composite = fast_casual_index(monthly, comp).round(3)
    monthly_out = pd.concat([monthly, composite], axis=1)

    yoy_components = add_yoy(monthly)
    index_yoy_chg = (composite - composite.shift(12)).round(3).rename("fast_casual_index_yoy_chg")
    out = pd.concat([monthly_out, yoy_components, index_yoy_chg], axis=1)
    out.index.name = "month"
    out = out.reset_index()
    out["month"] = out["month"].dt.strftime("%Y-%m")

    yoy_cols = [c for c in out.columns if c.endswith("_yoy_pct")]
    out[yoy_cols] = out[yoy_cols].replace([np.inf, -np.inf], np.nan).round(2)

    out_path = Path(output).expanduser().resolve()
    out.to_csv(out_path, index=False)
    n_comp = len(composite_subset(comp))
    if verbose:
        print(
            f"Wrote {out_path} ({len(out)} rows, {len(comp)} pulls, "
            f"{n_comp} series in fast_casual_index); timeframe={tf!r}"
        )
    if upload_gcs:
        uri = str(upload_gcs).strip()
        upload_csv_to_gcs(out_path, uri)
        if verbose:
            print(f"Uploaded CSV to {uri}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Separate Google Trends pulls per term, monthly + YoY + composite index CSV"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="gtrends_fast_casual_monthly.csv",
        help="Output CSV path",
    )
    parser.add_argument("--geo", default="US", help="Trends geo code (default US)")
    parser.add_argument(
        "--timeframe",
        default="today 5-y",
        help="pytrends timeframe when --start-date is not set (default: today 5-y)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Custom window start (use with --end-date). Example for back to 2018: --start-date 2018-01-01",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Custom window end (defaults to today if --start-date is set)",
    )
    parser.add_argument(
        "--merge-csv",
        default=None,
        metavar="PATH",
        help=(
            "Older monthly CSV to merge (e.g. downloaded from GCS). Overlapping months keep the **new** pull; "
            "missing months back-fill from this file. Index and YoY are recomputed on the combined span."
        ),
    )
    parser.add_argument(
        "--upload-gcs",
        default=None,
        metavar="gs://BUCKET/path.csv",
        help="After writing -o, upload the same file to this GCS URI (needs Storage write on the bucket).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=5.0,
        help="Seconds to sleep after each successful API call",
    )
    args = parser.parse_args()

    if bool(args.start_date) ^ bool(args.end_date):
        if args.start_date and not args.end_date:
            pass  # write_gtrends_monthly_csv fills end_date
        else:
            parser.error("--start-date is required when --end-date is set")

    try:
        write_gtrends_monthly_csv(
            args.output,
            geo=args.geo,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            merge_csv=args.merge_csv,
            upload_gcs=args.upload_gcs,
            sleep_after=args.sleep,
            verbose=True,
        )
    except ValueError as e:
        raise SystemExit(str(e)) from e
    except FileNotFoundError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
