import streamlit as st

st.title("Limitations")

st.markdown(
    """
- **Public macro** is national; chains are regional brands — residual idiosyncratic risk stays large.
- **Fiscal vs calendar**: macro aligns to **`Prd_End`**; fiscal periods spanning two calendar quarters
  or months are flagged in feature tables (`fiscal_spans_calendar_*`).
- **Peer disclosure** varies (traffic/ticket completeness for WING/SHAK/SG vs focus names).
- **Commodity benchmarks** come from pasted monthly CSVs, not live USDA API (by design for stability).

More items will be filled in as modeling choices harden.
"""
)
