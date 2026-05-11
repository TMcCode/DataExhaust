"""Monthly commodity benchmarks from analyst-pasted USDA-style tables (CSV), no Quick Stats API.

Expected files beside this module (same folder as ``macro_data`` / ``load_mlp_master``):

- ``broilers_turkeys_monthly_paste.csv`` — columns include ``calendar_month_end``, broiler/turkey $/lb
- ``beef_cattle_prices_received_monthly_paste.csv`` — ``calendar_month_end`` + cattle categories $/cwt

Missing files emit a warning and omit those columns; macro still loads without them.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

_POULTRY_FILENAME = "broilers_turkeys_monthly_paste.csv"
_BEEF_FILENAME = "beef_cattle_prices_received_monthly_paste.csv"

_POULTRY_RENAME = {
    "broilers_usd_per_lb": "commodity_broilers_price_received_usd_per_lb_monthly_paste",
    "turkeys_usd_per_lb": "commodity_turkeys_price_received_usd_per_lb_monthly_paste",
}

_BEEF_RENAME = {
    "all_beef_cattle_price_received_usd_per_cwt": (
        "commodity_all_beef_cattle_price_received_usd_per_cwt_monthly_paste"
    ),
    "calves_price_received_usd_per_cwt": "commodity_calves_price_received_usd_per_cwt_monthly_paste",
    "cows_price_received_usd_per_cwt": "commodity_cows_price_received_usd_per_cwt_monthly_paste",
    "steers_and_heifers_price_received_usd_per_cwt": (
        "commodity_steers_and_heifers_price_received_usd_per_cwt_monthly_paste"
    ),
}

def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _load_one_csv(path: Path, rename: dict[str, str]) -> pd.DataFrame | None:
    if not path.is_file():
        warnings.warn(
            f'Commodity paste CSV missing ({path.name}) — skipping those columns. '
            "Add the file next to commodity_paste_csv.py or use macro without commodity CSV join.",
            stacklevel=3,
        )
        return None
    df = pd.read_csv(path)
    if "calendar_month_end" not in df.columns:
        warnings.warn(f"{path.name}: no calendar_month_end column — skipped.", stacklevel=3)
        return None
    drop_cols = {"year", "month", "calendar_month_end"}
    cols = [c for c in df.columns if c not in drop_cols]
    raw_ix = pd.to_datetime(df["calendar_month_end"]).dt.normalize()
    # Use ndarray values so pandas does not re-align Series onto the DatetimeIndex.
    out = pd.DataFrame(
        {c: pd.to_numeric(df[c], errors="coerce").to_numpy() for c in cols},
        index=pd.DatetimeIndex(raw_ix, name="month_end"),
        dtype="float64",
    )
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    return out.sort_index()


def load_commodity_paste_monthly_dataframe() -> pd.DataFrame:
    """Wide monthly panel keyed by normalized month-end. Empty when no usable CSVs."""
    root = _repo_root()
    chunks: list[pd.DataFrame] = []
    p = _load_one_csv(root / _POULTRY_FILENAME, _POULTRY_RENAME)
    if p is not None and not p.empty:
        chunks.append(p)
    b = _load_one_csv(root / _BEEF_FILENAME, _BEEF_RENAME)
    if b is not None and not b.empty:
        chunks.append(b)

    if not chunks:
        return pd.DataFrame()

    out = chunks[0]
    for c in chunks[1:]:
        out = out.join(c, how="outer")
    out = out.sort_index()
    return out.astype("float64")


def probe_commodity_csvs() -> int:
    """Print whether paste files exist and row counts."""
    root = _repo_root()
    for fn in (_POULTRY_FILENAME, _BEEF_FILENAME):
        path = root / fn
        if not path.is_file():
            print(f"MISSING {fn}")
            continue
        n = sum(1 for _ in path.open(encoding="utf-8")) - 1
        print(f"OK {fn} (~{n} data rows)")
    df = load_commodity_paste_monthly_dataframe()
    if df.empty:
        print("Merged commodity frame is empty.")
        return 1
    print("Merged columns:", list(df.columns))
    print(df.tail(2))
    return 0
