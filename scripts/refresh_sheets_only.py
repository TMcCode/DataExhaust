"""Surgical bundle refresh — pull fresh Google Sheets data only, preserve macro.

Use this when BLS / FRED / another macro source is temporarily broken (API outage,
rate-limit, expired key) and a full ETL run would overwrite good macro columns
in ``data/snapshots/mlp_dashboard_bundle.pkl.gz`` with empty data.

What this script does:
  1. Loads the existing local snapshot bundle.
  2. Re-pulls Sheets (HistoricalValues, FiscalDates, MetricNames, SSSForecasts).
  3. Rebuilds the sheets-derived panels (``brand_period_wide`` and
     ``feature_tables``) from the new sheets + the **existing** macro that's
     already in the bundle.
  4. Writes the merged bundle back to disk and (optionally) uploads it to GCS.

What this script does NOT do:
  - Re-fetch FRED / BLS / commodity / USDA data. Those stay exactly as they
    were in the previous snapshot.

If macro is fully working, prefer the normal full ETL:
    python3 load_mlp_master.py --gcs-snapshot-uri "$MLP_GCS_SNAPSHOT_URI"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import feature_panel
import mlp_gcs_snapshot
import sheets_client


_LOCAL_SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "snapshots"
    / "mlp_dashboard_bundle.pkl.gz"
)


def _macro_has_rows(macro: dict) -> bool:
    """Sanity check: existing snapshot's macro must be non-empty to preserve."""
    m = macro.get("monthly")
    return m is not None and not m.empty


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh only the Sheets-derived parts of the dashboard snapshot. "
            "Preserves the existing macro (FRED / BLS / commodities)."
        )
    )
    parser.add_argument(
        "--gcs-snapshot-uri",
        default=os.environ.get("MLP_GCS_SNAPSHOT_URI"),
        help=(
            "Optional gs:// URI to also upload the refreshed bundle to. "
            "Defaults to $MLP_GCS_SNAPSHOT_URI."
        ),
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=None,
        help="Override workbook ID (default: sheets_client.MLP_FAST_CASUAL_SPREADSHEET_ID).",
    )
    args = parser.parse_args()

    if not _LOCAL_SNAPSHOT_PATH.is_file():
        print(f"ERROR: no existing snapshot at {_LOCAL_SNAPSHOT_PATH}", file=sys.stderr)
        print("       Run the full ETL first (load_mlp_master.py).", file=sys.stderr)
        return 1

    print(f"Loading existing snapshot: {_LOCAL_SNAPSHOT_PATH}")
    bundle = mlp_gcs_snapshot.load_bundle_from_local_path(_LOCAL_SNAPSHOT_PATH)
    if bundle is None:
        print("ERROR: failed to load existing snapshot bundle.", file=sys.stderr)
        return 1

    macro = bundle.get("macro") or {}
    if not _macro_has_rows(macro):
        print(
            "ERROR: existing snapshot has no macro data to preserve. "
            "Run the full ETL instead.",
            file=sys.stderr,
        )
        return 1
    print(
        f"  preserved macro.monthly: {macro['monthly'].shape}, "
        f"calendar_quarter: {macro['calendar_quarter'].shape}"
    )

    print("Re-pulling Google Sheets...")
    dfs = sheets_client.load_mlp_fast_casual_dataframes(args.spreadsheet_id)
    hv = dfs.get("historical_values")
    if hv is None or hv.empty:
        print(
            "ERROR: Sheets returned no data — check credentials. Aborting "
            "to avoid overwriting good sheets data with empty.",
            file=sys.stderr,
        )
        return 1
    print(f"  historical_values: {hv.shape}")
    print(f"  fiscal_dates:      {dfs['fiscal_dates'].shape}")
    print(f"  sss_forecasts:     {dfs['sss_forecasts'].shape}")

    print("Rebuilding brand_period_wide from new sheets...")
    brand_period_wide = sheets_client.build_mlp_brand_period_wide_df(
        args.spreadsheet_id, dfs=dfs
    )
    print(f"  brand_period_wide: {brand_period_wide.shape}")

    print("Rebuilding feature_tables (new sheets + preserved macro)...")
    feature_tables = feature_panel.build_macro_joined_panels(
        brand_period_wide,
        dfs["fiscal_dates"],
        macro,
    )

    bundle["mlp_sheets"] = dfs
    bundle["brand_period_wide"] = brand_period_wide
    bundle["feature_tables"] = feature_tables

    print(f"Writing merged bundle to {_LOCAL_SNAPSHOT_PATH}")
    mlp_gcs_snapshot.save_bundle_to_local_path(bundle, _LOCAL_SNAPSHOT_PATH)

    if args.gcs_snapshot_uri:
        uri = str(args.gcs_snapshot_uri).strip()
        print(f"Uploading merged bundle to {uri}")
        mlp_gcs_snapshot.upload_bundle_gzip_pickle(bundle, uri)

    print()
    print("=== Surgical refresh complete ===")
    print("  Sheets       : REFRESHED")
    print("  brand_wide   : REBUILT from new sheets")
    print("  feature_tabs : REBUILT from new sheets + preserved macro")
    print("  macro        : PRESERVED (untouched from previous snapshot)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
