#!/usr/bin/env python3
"""Publish the 8 runtime CSVs the dashboard reads to a single GCS prefix.

Uploads each repo-bundled CSV to ``gs://<bucket>/<prefix>/<basename>``. After
running, set the matching ``MLP_*_CSV`` / ``*_MONTHLY_CSV`` env vars (locally in
``.env`` or in Streamlit Cloud secrets) to the printed ``gs://...`` URIs so the
dashboard reads from GCS as the canonical source. The repo copies remain as the
offline-dev fallback.

By default skips files whose MD5 already matches the remote object so re-runs
are idempotent.

Usage:
    python scripts/upload_runtime_csvs_to_gcs.py                # upload changed/new
    python scripts/upload_runtime_csvs_to_gcs.py --dry-run      # report only
    python scripts/upload_runtime_csvs_to_gcs.py --force        # upload everything
    python scripts/upload_runtime_csvs_to_gcs.py --bucket X     # override bucket
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

DEFAULT_BUCKET = "data-exhaust_cloudbuild"
DEFAULT_PREFIX = "source/csvs"


@dataclass(frozen=True)
class RuntimeCsv:
    """One runtime CSV the dashboard reads — local repo path + GCS basename + env var hint."""

    local_path: str  # relative to repo root
    env_var: str  # which env var consumers read to override the source


RUNTIME_CSVS: tuple[RuntimeCsv, ...] = (
    RuntimeCsv("gdelt_fast_casual_monthly.csv", "MLP_GDELT_CSV"),
    RuntimeCsv("gtrends_fast_casual_monthly.csv", "MLP_GTRENDS_CSV"),
    RuntimeCsv("data/gdelt_fast_casual_monthly_long.csv", "MLP_GDELT_LONG_CSV"),
    RuntimeCsv("data/bart_sf_ridership_monthly.csv", "BART_SF_RIDERSHIP_MONTHLY_CSV"),
    RuntimeCsv("data/mta_manhattan_subway_monthly.csv", "MTA_MANHATTAN_SUBWAY_MONTHLY_CSV"),
    RuntimeCsv("data/opentable_us_seated_diners_monthly.csv", "OPENTABLE_US_SEATED_DINERS_MONTHLY_CSV"),
    RuntimeCsv("broilers_turkeys_monthly_paste.csv", "MLP_BROILERS_CSV"),
    RuntimeCsv("beef_cattle_prices_received_monthly_paste.csv", "MLP_BEEF_CSV"),
)


def _load_dotenv_quiet() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_REPO / ".env", override=True)
    except ImportError:
        pass


def _resolve_credentials() -> str | None:
    for var in ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_SHEETS_CREDENTIALS"):
        v = os.environ.get(var)
        if v and Path(v).is_file():
            return v
    fallback = _REPO / "data-exhaust-key.json"
    if fallback.is_file():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(fallback)
        return str(fallback)
    return None


def _local_md5_base64(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode("ascii")


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f}GB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help=f"GCS bucket (default: {DEFAULT_BUCKET})")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help=f"prefix within bucket (default: {DEFAULT_PREFIX})")
    parser.add_argument("--dry-run", action="store_true", help="show plan, do not upload")
    parser.add_argument("--force", action="store_true", help="upload even when md5 matches")
    args = parser.parse_args()

    _load_dotenv_quiet()
    cred_path = _resolve_credentials()
    if cred_path is None:
        print("ERROR: no service-account key (GOOGLE_APPLICATION_CREDENTIALS or data-exhaust-key.json).",
              file=sys.stderr)
        return 2
    print(f"Credentials: {cred_path}")

    try:
        from google.cloud import storage
    except ImportError:
        print("ERROR: google-cloud-storage is not installed.", file=sys.stderr)
        return 2

    client = storage.Client()
    bucket = client.bucket(args.bucket)
    prefix = args.prefix.rstrip("/")

    print(f"Target: gs://{args.bucket}/{prefix}/")
    if args.dry_run:
        print("(dry-run — no uploads will be performed)")
    print("-" * 80)
    print(f"{'STATUS':<10} {'SIZE':>8}  {'FILE':<55} {'ENV VAR'}")
    print("-" * 80)

    n_uploaded = 0
    n_skipped = 0
    n_missing = 0

    for spec in RUNTIME_CSVS:
        local = _REPO / spec.local_path
        blob_name = f"{prefix}/{Path(spec.local_path).name}"
        if not local.is_file():
            print(f"{'MISSING':<10} {'—':>8}  {spec.local_path:<55} {spec.env_var}")
            n_missing += 1
            continue
        size = local.stat().st_size
        blob = bucket.blob(blob_name)

        action = "UPLOAD"
        if not args.force:
            try:
                if blob.exists():
                    blob.reload()
                    if blob.md5_hash and blob.md5_hash == _local_md5_base64(local):
                        action = "SKIP"
            except Exception:
                pass

        print(f"{action:<10} {_human(size):>8}  {spec.local_path:<55} {spec.env_var}")

        if action == "SKIP":
            n_skipped += 1
            continue

        if args.dry_run:
            continue

        try:
            blob.upload_from_filename(str(local), content_type="text/csv")
            n_uploaded += 1
        except Exception as e:
            print(f"  ERROR uploading {blob_name}: {type(e).__name__}: {e}", file=sys.stderr)
            return 1

    print("-" * 80)
    print(f"Summary: uploaded={n_uploaded}  skipped={n_skipped}  missing={n_missing}  total={len(RUNTIME_CSVS)}")

    if args.dry_run:
        return 0

    print("")
    print("Add these to .streamlit/secrets.toml (and/or .env) to make GCS the canonical source:")
    for spec in RUNTIME_CSVS:
        uri = f"gs://{args.bucket}/{prefix}/{Path(spec.local_path).name}"
        print(f'  {spec.env_var} = "{uri}"')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
