"""Orchestrate MLP workbook (Google Sheets) + U.S. macro (FRED + BLS + commodity CSVs).

Optional ``--gtrends`` refreshes the monthly Google Trends CSV via :mod:`gtrends_monthly_brands`
(pytrends; separate from Sheets/FRED). Optional ``--gdelt`` refreshes the free GDELT brand-buzz CSV
via :mod:`gdelt_monthly_brands`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

import analytic_panel
import bls_data
import commodity_paste_csv
import feature_panel
import macro_data
import mlp_gcs_snapshot
import sheets_client


def _sheets_loaded_ok(dfs: dict[str, Any]) -> bool:
    """``True`` iff Sheets returned non-empty workbook tables (i.e., credentials worked)."""
    hv = dfs.get("historical_values")
    return hv is not None and not hv.empty


def _macro_loaded_ok(macro: dict[str, Any]) -> bool:
    """``True`` iff the FRED-backed monthly macro frame has rows."""
    m = macro.get("monthly")
    return m is not None and not m.empty


def load_all_mlp_data(
    spreadsheet_id: str | None = None,
    macro_observation_start: str = "2000-01-01",
    *,
    build_wide: bool = True,
    load_macro: bool = True,
    include_commodity_csvs: bool = True,
    join_analytic_macro: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    """Pull Sheets once, optionally build wide panel reuse that snapshot, fetch macro.

    Each upstream source skips gracefully on missing credentials (see
    :func:`sheets_client.load_mlp_fast_casual_dataframes` and
    :func:`macro_data.load_macro_dataframes`). Dependent steps (wide panel,
    analytic panel) are skipped here when their inputs came back empty, so a
    reviewer with **no API keys at all** can run this without crashing.

    Returns:
        ``mlp_sheets`` — same keys as :func:`sheets_client.load_mlp_fast_casual_dataframes`
            (empty DataFrames with expected columns when credentials missing)
        ``macro`` — ``monthly``, ``calendar_quarter``, plus ``annual_<year>_spend_equiv`` (see
            :func:`macro_data.spend_equiv_annual_dict_key`) from :func:`macro_data.load_macro_dataframes`
            (empty when ``FRED_API_KEY`` missing or ``load_macro=False``)
        ``brand_period_wide`` — if ``build_wide`` **and** sheets loaded with rows
        ``analytic_panel`` — if ``join_analytic_macro`` **and** both sheets + macro loaded with rows

    ``verbose``: print progress (off for Streamlit / embedded callers).
    """
    if verbose:
        print("Loading Google Sheets...", flush=True)
    dfs = sheets_client.load_mlp_fast_casual_dataframes(spreadsheet_id)
    sheets_ok = _sheets_loaded_ok(dfs)
    if verbose and not sheets_ok:
        print("  → skipped (no credentials); continuing with empty workbook frames.", flush=True)

    if load_macro and verbose:
        if include_commodity_csvs:
            msg = "Loading macro (FRED + weekly gas + BLS CES + commodity paste CSVs)."
        else:
            msg = "Loading macro (FRED + weekly gas + BLS CES; skipping commodity CSVs)."
        print(msg, flush=True)
    macro = (
        macro_data.load_macro_dataframes(
            macro_observation_start,
            include_commodity_csvs=include_commodity_csvs,
        )
        if load_macro
        else {"monthly": pd.DataFrame(), "calendar_quarter": pd.DataFrame()}
    )
    macro_ok = _macro_loaded_ok(macro)
    if verbose and load_macro and not macro_ok:
        print("  → skipped (no FRED_API_KEY); continuing with empty macro frames.", flush=True)

    out: dict[str, Any] = {"mlp_sheets": dfs, "macro": macro}

    if build_wide:
        if sheets_ok:
            out["brand_period_wide"] = sheets_client.build_mlp_brand_period_wide_df(
                spreadsheet_id,
                dfs=dfs,
            )
        elif verbose:
            print(
                "Brand wide panel: skipped (Sheets workbook is empty; needs HistoricalValues rows).",
                flush=True,
            )

    if join_analytic_macro:
        cq = macro.get("calendar_quarter")
        if sheets_ok and macro_ok and "brand_period_wide" in out and cq is not None and not cq.empty:
            out["analytic_panel"] = analytic_panel.join_wide_with_calendar_macro_quarterly(
                out["brand_period_wide"],
                dfs["fiscal_dates"],
                cq,
            )
        elif verbose:
            missing = []
            if not sheets_ok:
                missing.append("Sheets")
            if not macro_ok:
                missing.append("macro")
            print(
                f"Analytic panel: skipped (requires non-empty {' + '.join(missing) or 'wide + macro'}).",
                flush=True,
            )
    return out


def main() -> None:
    repo_dir = Path(__file__).resolve().parent
    default_csv = repo_dir / "mlp_cmg_bros_cava_wide.csv"
    parser = argparse.ArgumentParser(
        description=(
            "Load MLP Google Sheets + FRED macro (requires credentials / FRED_API_KEY). "
            "Optional --gtrends refreshes the Google Trends monthly CSV (pytrends)."
        ),
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=None,
        help="Override workbook ID (default: sheets_client.MLP_FAST_CASUAL_SPREADSHEET_ID)",
    )
    parser.add_argument(
        "--macro-start",
        default="2000-01-01",
        metavar="YYYY-MM-DD",
        help="FRED observation_start passed to macro_data.load_macro_dataframes",
    )
    parser.add_argument(
        "--export-wide-csv",
        nargs="?",
        default=None,
        const=str(default_csv),
        metavar="PATH",
        help=(
            "Optional PATH for wide CSV (flag alone = default path beside this script). "
            f"Unless you pass --skip-export-wide-csv, the wide panel is written after every run "
            f"({default_csv.name} by default)."
        ),
    )
    parser.add_argument(
        "--skip-export-wide-csv",
        action="store_true",
        help=(
            "Do not write brand-period CSV to disk "
            "(overrides automatic export that includes YoY revenue $ + bridge columns)."
        ),
    )
    parser.add_argument(
        "--no-wide",
        action="store_true",
        help="Skip building brand_period_wide (sheets raw + macro only)",
    )
    parser.add_argument(
        "--no-macro",
        action="store_true",
        help="Skip FRED macro fetch (Google Sheets + optional wide CSV only)",
    )
    parser.add_argument(
        "--no-commodity-csvs",
        action="store_true",
        help=(
            "Omit broilers/turkeys/beef paste CSV commodity columns "
            "(default: merge broilers_turkeys_monthly_paste.csv & beef_*_paste.csv next to scripts)."
        ),
    )
    parser.add_argument(
        "--macro-csv-dir",
        default=None,
        metavar="DIR",
        help=(
            "Directory for mlp_macro_monthly.csv and mlp_macro_calendar_quarter.csv "
            "(default: project folder next to this script)"
        ),
    )
    parser.add_argument(
        "--no-macro-csv",
        action="store_true",
        help="Skip writing macro CSV files (when macro is loaded)",
    )
    parser.add_argument(
        "--fred-probe",
        action="store_true",
        help="Only test FRED_API_KEY (no Google Sheets). Prints which file/env supplied the key.",
    )
    parser.add_argument(
        "--bls-probe",
        action="store_true",
        help="Only test BLS CES fetch (requires network; BLS_REGISTRATION_KEY optional)",
    )
    parser.add_argument(
        "--commodity-csv-probe",
        action="store_true",
        help="Verify commodity paste CSVs exist beside load_mlp_master.py (no network).",
    )
    parser.add_argument(
        "--analytic-panel",
        action="store_true",
        help=(
            "Build analytic_panel: brand_period_wide + fiscal-to-calendar macro join "
            "(Prd_End → calendar quarter; see analytic_panel.py)."
        ),
    )
    parser.add_argument(
        "--export-feature-csvs",
        nargs="?",
        default=None,
        const=str(repo_dir),
        metavar="DIR",
        help=(
            "Write two inspection-only CSVs: fiscal-wide × macro (month-end + calendar quarter). "
            f"Optional directory (default: {repo_dir.name} next to this script)."
        ),
    )
    parser.add_argument(
        "--gcs-snapshot-uri",
        default=None,
        metavar="gs://BUCKET/PATH.pkl.gz",
        help=(
            "After load: gzip+pickle the full dashboard bundle "
            "(mlp_sheets + macro + brand_period_wide + feature_tables) to this GCS URI. "
            "Requires google-cloud-storage and credentials with Storage write on the bucket."
        ),
    )
    default_gtrends_csv = repo_dir / "gtrends_fast_casual_monthly.csv"
    parser.add_argument(
        "--gtrends",
        action="store_true",
        help=(
            "After load: refresh Google Trends monthly CSV (pytrends; one API call per term in "
            "gtrends_monthly_brands.DEFAULT_COMPONENTS). By default, if the output CSV already exists, "
            "it is used as merge history: **overlapping months keep the new pull**, older months are "
            "filled from the file (appendix). Pass --gtrends-no-auto-merge for a pull with no prior file. "
            "Override history with --gtrends-merge-csv PATH."
        ),
    )
    parser.add_argument(
        "--gtrends-output",
        default=None,
        metavar="PATH",
        help=f"Output CSV for --gtrends (default: {default_gtrends_csv.name} beside this script).",
    )
    parser.add_argument(
        "--gtrends-geo",
        default="US",
        help="Trends geo for --gtrends (default US).",
    )
    parser.add_argument(
        "--gtrends-timeframe",
        default="today 5-y",
        help="pytrends timeframe when --gtrends-start-date is not set (default: today 5-y).",
    )
    parser.add_argument(
        "--gtrends-start-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Optional --gtrends window start (with --gtrends-end-date or defaults end to today).",
    )
    parser.add_argument(
        "--gtrends-end-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Optional --gtrends window end.",
    )
    parser.add_argument(
        "--gtrends-merge-csv",
        default=None,
        metavar="PATH",
        help=(
            "Monthly Trends CSV to merge into the new pull for --gtrends (overlapping months keep the "
            "new pull; gaps filled from this file). If omitted and the output CSV already exists, that "
            "file is used automatically unless --gtrends-no-auto-merge."
        ),
    )
    parser.add_argument(
        "--gtrends-no-auto-merge",
        action="store_true",
        help=(
            "With --gtrends: do not auto-use the output CSV as merge history even if it exists "
            "(API window only; no appendix from disk)."
        ),
    )
    parser.add_argument(
        "--gtrends-upload-gcs",
        default=None,
        metavar="gs://BUCKET/path.csv",
        help="After --gtrends writes the CSV, upload it to this GCS URI.",
    )
    parser.add_argument(
        "--gtrends-sleep",
        type=float,
        default=5.0,
        help="Seconds to sleep after each successful Google Trends API call (default 5).",
    )
    parser.add_argument(
        "--gdelt",
        action="store_true",
        help=(
            "After load: refresh free GDELT monthly brand-buzz CSV "
            "(article counts/share for CMG/CAVA/BROS/SHAK/WING/SG; optional tone)."
        ),
    )
    parser.add_argument(
        "--gdelt-output",
        default=None,
        metavar="PATH",
        help="Output wide CSV for --gdelt (default: gdelt_fast_casual_monthly.csv beside this script).",
    )
    parser.add_argument(
        "--gdelt-long-output",
        default=None,
        metavar="PATH",
        help="Output long CSV for --gdelt (default: data/gdelt_fast_casual_monthly_long.csv).",
    )
    parser.add_argument(
        "--gdelt-start-date",
        default="2024-01-01",
        metavar="YYYY-MM-DD",
        help="GDELT window start for --gdelt (default: 2024-01-01; enough for 2025+ YoY).",
    )
    parser.add_argument(
        "--gdelt-end-date",
        default=None,
        metavar="YYYY-MM-DD",
        help="GDELT window end for --gdelt (default: today).",
    )
    parser.add_argument(
        "--gdelt-upload-gcs",
        default=None,
        metavar="gs://BUCKET/path.csv",
        help="After --gdelt writes the wide CSV, upload it to this GCS URI.",
    )
    parser.add_argument(
        "--gdelt-sleep",
        type=float,
        default=10.0,
        help="Seconds to sleep after each GDELT API call (default 10; public API is tightly rate-limited).",
    )
    parser.add_argument(
        "--gdelt-include-tone",
        action="store_true",
        help="With --gdelt, also request tone timelines. Slower and more likely to hit public API throttles.",
    )
    args = parser.parse_args()

    if args.fred_probe:
        raise SystemExit(macro_data.probe_fred_api_key())
    if args.bls_probe:
        raise SystemExit(bls_data.probe_bls_ces())
    if args.commodity_csv_probe:
        raise SystemExit(commodity_paste_csv.probe_commodity_csvs())

    bundle = load_all_mlp_data(
        spreadsheet_id=args.spreadsheet_id,
        macro_observation_start=args.macro_start,
        build_wide=not args.no_wide,
        load_macro=not args.no_macro,
        include_commodity_csvs=not args.no_commodity_csvs,
        join_analytic_macro=args.analytic_panel,
    )

    s = bundle["mlp_sheets"]
    sheets_ok = _sheets_loaded_ok(s)
    print("MLP Sheets:" if sheets_ok else "MLP Sheets: SKIPPED (no credentials)")
    print(f"  historical_values: {s['historical_values'].shape}")
    print(f"  fiscal_dates:      {s['fiscal_dates'].shape}")
    print(f"  metric_names:      {s['metric_names'].shape}")

    m = bundle["macro"]
    macro_ok = _macro_loaded_ok(m)
    if args.no_macro:
        print("Macro (FRED): skipped (--no-macro)")
    elif not macro_ok:
        print("Macro (FRED): SKIPPED (FRED_API_KEY not set)")
        print(f"  monthly:           {m['monthly'].shape}")
        print(f"  calendar_quarter: {m['calendar_quarter'].shape}")
    else:
        print("Macro (FRED):")
        print(f"  monthly:           {m['monthly'].shape}")
        print(f"  calendar_quarter: {m['calendar_quarter'].shape}")
        if not args.no_macro_csv:
            dest = (
                Path(args.macro_csv_dir).expanduser().resolve()
                if args.macro_csv_dir
                else Path(__file__).resolve().parent
            )
            mp = macro_data.export_macro_csvs(m, dest)
            print(f"  wrote {mp['monthly'].name}")
            print(f"  wrote {mp['calendar_quarter'].name}")
            ak = macro_data.spend_equiv_annual_dict_key()
            if ak in mp:
                print(f"  wrote {mp[ak].name}")
            comm = [c for c in m["monthly"].columns if str(c).startswith("commodity_")]
            if comm:
                print(f"  monthly includes {len(comm)} commodity_* column(s) (search CSV for 'commodity_')")
            elif not args.no_commodity_csvs:
                print(
                    "  note: no commodity_* columns in monthly — use --commodity-csv-probe or add "
                    "paste CSVs beside commodity_paste_csv.py (or you passed --no-commodity-csvs)."
                )

    if "brand_period_wide" in bundle:
        w = bundle["brand_period_wide"]
        print(f"brand_period_wide: {w.shape}")
        _got = sorted({str(x) for x in w["Ticker"].dropna().unique()})
        print(f"  tickers present: {_got}")
        _miss = [t for t in sheets_client.MLP_WIDE_TABLE_TICKERS if t not in set(_got)]
        if _miss:
            print(
                "  ⚠️  Missing from wide (need **HistoricalValues** rows **and** **MetricNames** "
                "rows with matching Metric for an inner join): "
                + ", ".join(_miss)
            )
        _bridge = (
            "new_dollars",
            "sss_dollars",
            "restaurant_rev_yoy_dollars",
            "new_plus_sss_dollars",
            "restaurant_rev_yoy_bridge_residual",
        )
        _have = [c for c in _bridge if c in w.columns]
        print(f"  revenue-bridge columns in frame: {_have}")
    elif args.no_wide:
        print("brand_period_wide: (skipped --no-wide)")
    else:
        print("brand_period_wide: SKIPPED (Sheets workbook empty — needs credentials)")

    if args.analytic_panel:
        if "analytic_panel" not in bundle:
            print("analytic_panel: SKIPPED (requires non-empty Sheets + macro)")
        else:
            ap = bundle["analytic_panel"]
            print(f"analytic_panel: {ap.shape}")
            if "fiscal_spans_calendar_quarters" in ap.columns:
                n_spans = int(ap["fiscal_spans_calendar_quarters"].fillna(False).sum())
                print(f"  fiscal_spans_calendar_quarters True: {n_spans} rows")

    if "brand_period_wide" in bundle and not args.skip_export_wide_csv:
        out_path = (
            Path(args.export_wide_csv).expanduser().resolve()
            if args.export_wide_csv is not None
            else default_csv
        )
        path_written = sheets_client.export_mlp_brand_period_wide_csv(
            path=out_path,
            spreadsheet_id=args.spreadsheet_id,
            dfs=bundle["mlp_sheets"],
            wide=bundle["brand_period_wide"],
        )
        print(f"Wrote wide CSV: {path_written}")
    elif args.export_wide_csv is not None and "brand_period_wide" not in bundle:
        print("Wide CSV: SKIPPED (Sheets workbook is empty — needs credentials).")

    if args.export_feature_csvs is not None:
        if "brand_period_wide" not in bundle or not macro_ok:
            print(
                "Feature CSVs: SKIPPED (requires Sheets + macro; one or both came back empty)."
            )
        else:
            dest = Path(args.export_feature_csvs).expanduser().resolve()
            tables = feature_panel.build_macro_joined_panels(
                bundle["brand_period_wide"],
                bundle["mlp_sheets"]["fiscal_dates"],
                bundle["macro"],
            )
            fp_paths = feature_panel.export_macro_joined_panel_csvs(tables, directory=dest)
            for key, csv_path in fp_paths.items():
                print(f"Wrote inspection feature CSV ({key}): {csv_path}")

    if args.gcs_snapshot_uri:
        if "brand_period_wide" not in bundle or not macro_ok or args.no_wide:
            print(
                "GCS snapshot upload: SKIPPED (requires Sheets + macro; one or both came back empty)."
            )
        else:
            bundle["feature_tables"] = feature_panel.build_macro_joined_panels(
                bundle["brand_period_wide"],
                bundle["mlp_sheets"]["fiscal_dates"],
                bundle["macro"],
            )
            uri = str(args.gcs_snapshot_uri).strip()
            mlp_gcs_snapshot.upload_bundle_gzip_pickle(bundle, uri)
            print(f"Uploaded dashboard bundle to {uri}")
            # Also refresh the in-repo snapshot fallback so a single ETL run keeps
            # both surfaces (GCS + zero-credential local) in sync. Streamlit Cloud
            # has no GCP creds, so it always reads from this local pickle.
            local_path = (
                Path(__file__).resolve().parent / "data" / "snapshots" / "mlp_dashboard_bundle.pkl.gz"
            )
            mlp_gcs_snapshot.save_bundle_to_local_path(bundle, local_path)
            print(f"Refreshed local snapshot bundle at {local_path}")

    print()
    print("=== ETL summary ===")
    print(f"  Google Sheets    : {'OK' if sheets_ok else 'SKIPPED (no service-account JSON)'}")
    if args.no_macro:
        print("  FRED macro       : SKIPPED (--no-macro)")
    else:
        print(f"  FRED macro       : {'OK' if macro_ok else 'SKIPPED (FRED_API_KEY not set)'}")
    print(
        "  Brand wide panel : "
        + ("OK" if "brand_period_wide" in bundle else "SKIPPED (depends on Sheets)")
    )
    if args.analytic_panel:
        print(
            "  Analytic panel   : "
            + ("OK" if "analytic_panel" in bundle else "SKIPPED (depends on Sheets + macro)")
        )
    if not (sheets_ok and macro_ok):
        print()
        print(
            "  Note: this is a partial run. The dashboard ships a frozen bundle at\n"
            "        data/snapshots/mlp_dashboard_bundle.pkl.gz that already contains every\n"
            "        chart's data; you only need to re-run this ETL if you want fresh pulls."
        )

    if args.gtrends:
        import gtrends_monthly_brands

        gt_out = (
            Path(args.gtrends_output).expanduser().resolve()
            if args.gtrends_output
            else default_gtrends_csv
        )
        merge_csv = args.gtrends_merge_csv
        if merge_csv is None and not args.gtrends_no_auto_merge and gt_out.is_file():
            merge_csv = str(gt_out)
            print(
                "Google Trends: auto-merge existing output CSV as history "
                "(overlapping months = new pull; older months kept from file).",
                flush=True,
            )
        elif merge_csv is None and args.gtrends_no_auto_merge and gt_out.is_file():
            print(
                "Google Trends: --gtrends-no-auto-merge — not merging prior output file.",
                flush=True,
            )
        elif merge_csv is None:
            print(
                "Google Trends: no prior CSV at output path — API window only (no appendix).",
                flush=True,
            )
        print("Google Trends: refreshing monthly CSV (pytrends)...", flush=True)
        gtrends_monthly_brands.write_gtrends_monthly_csv(
            gt_out,
            geo=str(args.gtrends_geo),
            timeframe=str(args.gtrends_timeframe),
            start_date=args.gtrends_start_date,
            end_date=args.gtrends_end_date,
            merge_csv=merge_csv,
            upload_gcs=args.gtrends_upload_gcs,
            sleep_after=float(args.gtrends_sleep),
            verbose=True,
        )

    if args.gdelt:
        import gdelt_monthly_brands

        gdelt_out = (
            Path(args.gdelt_output).expanduser().resolve()
            if args.gdelt_output
            else repo_dir / "gdelt_fast_casual_monthly.csv"
        )
        gdelt_long = (
            Path(args.gdelt_long_output).expanduser().resolve()
            if args.gdelt_long_output
            else repo_dir / "data" / "gdelt_fast_casual_monthly_long.csv"
        )
        print("GDELT: refreshing monthly brand-buzz CSV...", flush=True)
        gdelt_monthly_brands.write_gdelt_monthly_csvs(
            gdelt_out,
            long_output=gdelt_long,
            start_date=args.gdelt_start_date,
            end_date=args.gdelt_end_date,
            sleep_s=float(args.gdelt_sleep),
            include_tone=bool(args.gdelt_include_tone),
            upload_gcs=args.gdelt_upload_gcs,
            verbose=True,
        )


if __name__ == "__main__":
    main()
