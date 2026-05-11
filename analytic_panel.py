"""Join brand fiscal-quarters to **calendar-quarter** national macro.

``Prd_Nm`` in the wide panel is **fiscal** and calendars differ by ticker: CMG/BROS often align with
Gregorian quarters; CAVA uses 83‑83‑83‑111‑style quarters; **WING**, **SHAK**, and **SG** use ~90‑day
quarters (year-end near Dec 31), with occasional **53rd-week** quarters (~every 20–24 quarters), and
each peer’s fiscal schedule can **differ**. Actual boundaries come from the sheet—no ticker-specific logic
here. Macro from :func:`macro_data.load_macro_dataframes`
``calendar_quarter`` uses standard **Gregorian** quarters (``QE-DEC``: Mar/Jun/Sep/Dec ends).

Mapping rule (transparent default):

- ``macro_calendar_quarter_join`` = calendar quarter label of **``Prd_End``** from the workbook
  ``FiscalDates`` tab (**end-date rule**).

If ``Prd_Start`` and ``Prd_End`` fall in **different** calendar quarters,
``fiscal_spans_calendar_quarters`` is ``True`` — macro for that row stays a **single** calendar
quarter (end-aligned); interpret carefully for long or offset fiscal windows.

Usage::

    bundle = load_all_mlp_data(...)
    q_panel = join_wide_with_calendar_macro_quarterly(...)
    m_panel = join_wide_with_calendar_macro_monthly(
        bundle["brand_period_wide"],
        bundle["mlp_sheets"]["fiscal_dates"],
        bundle["macro"]["monthly"],
    )
    # Or use :mod:`feature_panel` for both in one call.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def calendar_quarter_label_from_datetime(dt: Any) -> str | None:
    """Return ``YYYYQN`` for naive Timestamp/date (pandas calendar ``.quarter``)."""
    ts = pd.to_datetime(dt, errors="coerce")
    if pd.isna(ts):
        return None
    ts = pd.Timestamp(ts).normalize()
    return f"{int(ts.year)}Q{int(ts.quarter)}"


def fiscal_dates_macro_join_keys(fiscal_dates: pd.DataFrame) -> pd.DataFrame:
    """One row per (Ticker, Prd_Nm) with calendar-quarter join helper columns.

    Expects workbook ``FiscalDates``: ``Ticker``, ``Prd_Nm``, ``Prd_End``; optional ``Prd_Strt``.
    """
    fd = fiscal_dates.copy()
    for col in ("Ticker", "Prd_Nm"):
        if col not in fd.columns:
            raise KeyError(f"fiscal_dates missing column {col!r}")
        fd[col] = fd[col].astype(str).str.strip()
    if "Prd_End" not in fd.columns:
        raise KeyError("fiscal_dates missing Prd_End")

    fd["Prd_End_cal"] = pd.to_datetime(fd["Prd_End"], errors="coerce").dt.normalize()
    fd["macro_calendar_quarter_join"] = fd["Prd_End_cal"].map(calendar_quarter_label_from_datetime)

    if "Prd_Strt" in fd.columns:
        fd["Prd_Start_cal"] = pd.to_datetime(fd["Prd_Strt"], errors="coerce").dt.normalize()
        fq_start = fd["Prd_Start_cal"].map(calendar_quarter_label_from_datetime)
        fq_end = fd["macro_calendar_quarter_join"]
        fd["calendar_quarter_at_period_start"] = fq_start
        fd["fiscal_spans_calendar_quarters"] = (
            fq_start.notna()
            & fq_end.notna()
            & (fq_start.astype(str) != fq_end.astype(str))
        )
    else:
        fd["fiscal_spans_calendar_quarters"] = False

    keep = [
        "Ticker",
        "Prd_Nm",
        "macro_calendar_quarter_join",
        "calendar_quarter_at_period_start",
        "Prd_Start_cal",
        "Prd_End_cal",
        "fiscal_spans_calendar_quarters",
    ]
    out = fd[[c for c in keep if c in fd.columns]].drop_duplicates(subset=["Ticker", "Prd_Nm"])

    bad_end = out["macro_calendar_quarter_join"].isna()
    if bad_end.any():
        sample = out.loc[bad_end, ["Ticker", "Prd_Nm"]].merge(
            fd[["Ticker", "Prd_Nm", "Prd_End"]].drop_duplicates(),
            on=["Ticker", "Prd_Nm"],
            how="left",
        ).head(15)
        raise ValueError(f"Could not parse Prd_End for some fiscal rows:\n{sample}")

    return out


def join_wide_with_calendar_macro_quarterly(
    wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
    macro_calendar_quarter_wide: pd.DataFrame,
    *,
    macro_column_prefix: str | None = "macro_cq_",
) -> pd.DataFrame:
    """Left-join wide (Ticker × fiscal ``Prd_Nm``) to national macro calendar-quarter columns."""
    keys = fiscal_dates_macro_join_keys(fiscal_dates)

    base = wide.copy()
    if "Ticker" not in base.columns or "Prd_Nm" not in base.columns:
        raise KeyError("wide requires Ticker and Prd_Nm")

    merged = base.merge(keys, on=["Ticker", "Prd_Nm"], how="left", validate="m:1")

    mc = macro_calendar_quarter_wide.copy()
    if "calendar_quarter" not in mc.columns:
        raise KeyError('macro_calendar_quarter_wide requires column "calendar_quarter"')

    key_col = "calendar_quarter"
    if macro_column_prefix:
        ren = {
            c: f"{macro_column_prefix}{c}"
            for c in mc.columns
            if c != key_col
        }
        mc = mc.rename(columns=ren)

    out = merged.merge(
        mc,
        left_on="macro_calendar_quarter_join",
        right_on=key_col,
        how="left",
    )
    out = out.drop(columns=[key_col], errors="ignore")
    return out


def _month_end_timestamp_from_datetime_series(s: pd.Series) -> pd.Series:
    """Calendar month-end (normalized) for each parsed timestamp; NaT where parse fails."""
    ts = pd.to_datetime(s, errors="coerce").dt.normalize()
    return ts + pd.offsets.MonthEnd(0)


def fiscal_dates_macro_month_join_keys(fiscal_dates: pd.DataFrame) -> pd.DataFrame:
    """One row per (Ticker, Prd_Nm) with **calendar month-end** join key for macro monthly.

    ``macro_month_end_join`` = last calendar day of the month containing **``Prd_End``**
    (matches :func:`macro_data.load_macro_dataframes` ``monthly`` index ``month_end``).
    """
    fd = fiscal_dates.copy()
    for col in ("Ticker", "Prd_Nm"):
        if col not in fd.columns:
            raise KeyError(f"fiscal_dates missing column {col!r}")
        fd[col] = fd[col].astype(str).str.strip()
    if "Prd_End" not in fd.columns:
        raise KeyError("fiscal_dates missing Prd_End")

    fd["Prd_End_cal"] = pd.to_datetime(fd["Prd_End"], errors="coerce").dt.normalize()
    fd["macro_month_end_join"] = _month_end_timestamp_from_datetime_series(fd["Prd_End"])

    if "Prd_Strt" in fd.columns:
        fd["Prd_Start_cal"] = pd.to_datetime(fd["Prd_Strt"], errors="coerce").dt.normalize()
        ms = _month_end_timestamp_from_datetime_series(fd["Prd_Strt"])
        fd["calendar_month_end_at_period_start"] = ms
        same_cal_month = (
            fd["Prd_Start_cal"].notna()
            & fd["Prd_End_cal"].notna()
            & (fd["Prd_Start_cal"].dt.to_period("M") == fd["Prd_End_cal"].dt.to_period("M"))
        )
        fd["fiscal_spans_calendar_months"] = (
            fd["Prd_Start_cal"].notna()
            & fd["Prd_End_cal"].notna()
            & ~same_cal_month
        )
    else:
        fd["fiscal_spans_calendar_months"] = False

    keep = [
        "Ticker",
        "Prd_Nm",
        "macro_month_end_join",
        "calendar_month_end_at_period_start",
        "Prd_Start_cal",
        "Prd_End_cal",
        "fiscal_spans_calendar_months",
    ]
    out = fd[[c for c in keep if c in fd.columns]].drop_duplicates(subset=["Ticker", "Prd_Nm"])

    bad = out["macro_month_end_join"].isna()
    if bad.any():
        sample = out.loc[bad, ["Ticker", "Prd_Nm"]].merge(
            fd[["Ticker", "Prd_Nm", "Prd_End"]].drop_duplicates(),
            on=["Ticker", "Prd_Nm"],
            how="left",
        ).head(15)
        raise ValueError(f"Could not derive month-end from Prd_End for some fiscal rows:\n{sample}")

    return out


def join_wide_with_calendar_macro_monthly(
    wide: pd.DataFrame,
    fiscal_dates: pd.DataFrame,
    macro_monthly_wide: pd.DataFrame,
    *,
    macro_column_prefix: str | None = "macro_m_",
) -> pd.DataFrame:
    """Left-join wide (Ticker × fiscal ``Prd_Nm``) to national macro **monthly** rows.

    ``macro_monthly_wide`` must use :func:`macro_data.load_macro_dataframes` ``monthly``:
    DatetimeIndex named ``month_end`` (or a column ``month_end`` after ``reset_index``).
    """
    keys = fiscal_dates_macro_month_join_keys(fiscal_dates)

    base = wide.copy()
    if "Ticker" not in base.columns or "Prd_Nm" not in base.columns:
        raise KeyError("wide requires Ticker and Prd_Nm")

    merged = base.merge(keys, on=["Ticker", "Prd_Nm"], how="left", validate="m:1")

    mm = macro_monthly_wide.copy()
    if mm.index.name == "month_end" or isinstance(mm.index, pd.DatetimeIndex):
        mm = mm.reset_index()
    if "month_end" not in mm.columns:
        raise KeyError('macro_monthly_wide needs DatetimeIndex or column "month_end"')

    mm["month_end"] = pd.to_datetime(mm["month_end"], errors="coerce").dt.normalize()

    key_col = "month_end"
    if macro_column_prefix:
        ren = {
            c: f"{macro_column_prefix}{c}"
            for c in mm.columns
            if c != key_col
        }
        mm = mm.rename(columns=ren)

    out = merged.merge(
        mm,
        left_on="macro_month_end_join",
        right_on=key_col,
        how="left",
    )
    out = out.drop(columns=[key_col], errors="ignore")
    return out
