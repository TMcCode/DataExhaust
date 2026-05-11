import streamlit as st

from streamlit_dashboard.data_loader import get_dashboard_bundle_or_stop

st.title("Supplemental data")
st.markdown(
    "Workbook plus **`brand_period_wide`** and calendar macro joins—a quick QA view, "
    "not the primary analytic cut."
)

bundle = get_dashboard_bundle_or_stop()
wide = bundle["brand_period_wide"]
feat_m = bundle["feature_tables"]["fiscal_wide_x_macro_calendar_month"]
feat_q = bundle["feature_tables"]["fiscal_wide_x_macro_calendar_quarter"]
monthly_macro = bundle["macro"]["monthly"]

c1, c2, c3 = st.columns(3)
c1.metric("Wide rows × cols", f"{wide.shape[0]} × {wide.shape[1]}")
c2.metric("Feature (month macro) cols", feat_m.shape[1])
c3.metric("Feature (CQ macro) cols", feat_q.shape[1])

st.subheader("`brand_period_wide` (preview)")
st.dataframe(wide.head(25), use_container_width=True, hide_index=True)

st.subheader("Macro monthly (tail) — columns containing `commodity_`")
comm_cols = [c for c in monthly_macro.columns if "commodity_" in str(c)]
st.caption(f"{len(comm_cols)} commodity-related column(s) in macro monthly.")
if comm_cols:
    show = monthly_macro.tail(12)[comm_cols[:12]]
else:
    show = monthly_macro.tail(6)
st.dataframe(show, use_container_width=True)

csv_wide = wide.to_csv(index=False).encode("utf-8")
st.download_button(
    "Export wide CSV",
    data=csv_wide,
    file_name="brand_period_wide_export.csv",
    mime="text/csv",
)
