import streamlit as st

st.title("Company deep dive")
st.markdown(
    """
Per-ticker trajectory views (traffic vs ticket, comps vs peers) will go here once chart helpers are wired.

Underlying table: **`brand_period_wide`** from Sheets (same grain as **`Prd_Nm`**).
"""
)
st.info(
    "**Fiscal vs calendar:** `Prd_Nm` and every metric in the wide table are **fiscal** periods. "
    "National macro (FRED/BLS) is on a **calendar** month or quarter grid. When we join them "
    "(see `analytic_panel`), macro is attached using the **calendar month or quarter of `Prd_End`** — "
    "so a fiscal row can sit next to macro that is not “the same fiscal quarter” as another company’s "
    "row in the same calendar bucket. **Industry backdrop** now plots the multi-ticker SSS block on "
    "**Gregorian calendar quarters only** so the dashed peer line is a simple mean of peer `sss` in "
    "that quarter; workbook `PeerSSSIndex` stays fiscal-`Prd_Nm`-keyed and is a different object."
)
