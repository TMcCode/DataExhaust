#!/usr/bin/env python3
"""CLI: load Sheets + macro and write two feature tables (month + calendar-quarter macro joins)."""

from __future__ import annotations

import argparse
from pathlib import Path

import feature_panel
import load_mlp_master


def main() -> None:
    default_out = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        description=(
            "Build reproducible fiscal-wide × macro panels (calendar month-end and calendar-quarter "
            "attach via FiscalDates Prd_End). Writes two CSV files."
        ),
    )
    p.add_argument(
        "--spreadsheet-id",
        default=None,
        help="Google Sheet ID override (default: sheets_client constant)",
    )
    p.add_argument(
        "--macro-start",
        default="2000-01-01",
        metavar="YYYY-MM-DD",
        help="Observation start for macro_data.load_macro_dataframes",
    )
    p.add_argument(
        "--export-dir",
        type=Path,
        default=default_out,
        help=f"Directory for feature CSV outputs (default: {default_out})",
    )
    p.add_argument(
        "--no-commodity-csvs",
        action="store_true",
        help="Same as load_mlp_master: skip commodity paste CSV merge in macro",
    )
    args = p.parse_args()

    bundle = load_mlp_master.load_all_mlp_data(
        spreadsheet_id=args.spreadsheet_id,
        macro_observation_start=args.macro_start,
        include_commodity_csvs=not args.no_commodity_csvs,
        join_analytic_macro=False,
    )
    panels = feature_panel.build_macro_joined_panels(
        bundle["brand_period_wide"],
        bundle["mlp_sheets"]["fiscal_dates"],
        bundle["macro"],
    )
    paths = feature_panel.export_macro_joined_panel_csvs(panels, directory=args.export_dir)
    for logical, csv_path in paths.items():
        print(f"{logical}: {panels[logical].shape} → {csv_path}")


if __name__ == "__main__":
    main()
