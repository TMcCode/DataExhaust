import streamlit as st

import macro_data

st.title("Overview")

st.markdown(
    rf"""
Hi -- thanks for checking out my case study. I've put together this project similar to how I'd build out the team's data products.
I spent a good amount of time planning:
determining what questions I wanted to get answers to, how to frame the dashboard, and make sure it could be extended and not just treated as a one-off notebook.
Then I did the work. I've added an approximate workflow and time to complete below.

I chose to focus the center of the project on understanding and forecasting **U.S. fast casual same-store sales**.
I focused on **CMG**, **CAVA**, and **BROS** as the three primary tickers (largest system-scale names in this basket) and pulled **SG**, **WING**, and **SHAK** metrics as peers.

**tldr;**

- **Macro- and industry-level analysis; where is SSS vs history; what is most useful for predicting SSS?** On **Macro & industry** I tie **spend-equiv** (**{macro_data.SPEND_EQUIV_BASE_YEAR}** basket), peer **SSS / pricing / traffic**, and **CPI–PPI–commodities** into one narrative: the peer group ran **hot** post-Covid as pricing offset input inflation, then **2025** shows **traffic softening** after years of mid-single-digit increases—more **give-back in traffic** than a collapse in the macro backdrop. For predicting SSS in without any paid data, the highest-value layer is still pulling metrics from filings: **traffic**, **ticket**, and **mix**. **OpenTable** seated diners add an industry demand check; **NYC/SF** transit is a narrow office-commuter read; **Google Trends** / **GDELT** add **awareness**. Broad **national macro** data is best treated as broad context, not a chain-specific SSS engine. None are nearly as helpful as **transaction data**.

- **Three tickers (CMG, CAVA, BROS): which data has better predictive power for SSS; four quarters forward.** I chose to make forecasts for **CMG**, **CAVA**, and **BROS** because they anchor the largest system-scale story in this basket. **Company-reported drivers** have the best “predictive” link to **SSS** here because they *are* the same decomposition management uses. **Macro** is largely common across the three. Among free proxies, **Trends** is usually more informative than **GDELT** for **ongoing** consumer pull (**CAVA** and **CMG** stand out in the current charts); **GDELT** is more **event**-driven. **BROS** needs extra discipline on **system vs company** reporting that I didn't model. **Four forward fiscal quarters** of **SSS** per name sit on **SSS forecast**, built from **traffic + menu price + check mix** with defaults overridable from the **SSSForecasts** sheet—that is my base-case path from the analysis, explicitly as an **organizing** forecast rather than a calibrated ML model.

- **Limitations of the data (where others might overstate scope).** **National** series are not **local** comps; **search and news** are not **sales**; **commodity indexes** are not **contract COGS**; **two** transit markets are not the national store base; **fiscal vs calendar patterns** means alignment is often approximate. More detail sits under **Dataset info**.


**Macro & industry** → answers first bullet; **SSS forecast** → answers second bullet; **Dataset info** → answers third bullets—or use the nav / buttons below: 
"""
    )
_PAGE_BASE = "streamlit_dashboard/pages"
_c1, _c2, _c3 = st.columns(3)
with _c1:
    st.page_link(f"{_PAGE_BASE}/macro_industry_sss.py", label="Macro & industry", use_container_width=True)
with _c2:
    st.page_link(f"{_PAGE_BASE}/sss_forecast.py", label="SSS forecast", use_container_width=True)
with _c3:
    st.page_link(f"{_PAGE_BASE}/data_roadmap_limitations.py", label="Dataset info", use_container_width=True)

st.subheader("A few notes")
st.markdown(
    """
- I am using these six names as a working view of the **fast casual** space, but this is not meant to imply
  they are the entire category. There are more public and private brands that would belong in a fuller
  coverage universe.
- I did not pull **SBUX** metrics because I ran out of time, and because it is the least similar of the group:
  international expansion, licensed stores, loyalty, and broader beverage occasions make it a more complex
  comp than the rest of this basket.
- The analysis generally starts in **2021** to focus on the post-Covid restaurant landscape. That also kept
  the manual metric pull manageable while still capturing the recovery, inflation cycle, and more recent
  consumer softness.
"""
)

st.subheader("Workflow")
st.markdown(
    """
| Workstream | Hours |
|---|---:|
| Planning the dashboard and data model | 3 |
| Pulling company metrics | 10 |
| Reading earnings transcripts | 2 |
| Pulling public API data | 4 |
| Building the data ETL | 4 |
| Analysis and interpretation | 5 |
| Fixing the icon in the top left of the screen | 5 |
| Arguing with ChatGPT over Streamlit spacing | 4 |
"""
)

st.subheader("Free Sources I Pulled Data From")
st.markdown(
    f"""
- **Company workbook** — Google Sheet tabs *HistoricalValues*, *FiscalDates*, and *MetricNames*.
  Fiscal period metrics are joined to calendar macro using `Prd_End`.
- **FRED** — unemployment, income, sentiment, gas, retail sales, restaurant / broad **CPI-U** (FAFH,
  headline `CPIAUCSL`, core `CPILFESL`, food at home `CUSR0000SAF11`), plus **BLS PPI** shopping &
  retail leasing rent index (`PCU5311205311201`; broad lessors `PCU531120531120` remains in the monthly export).
- **BLS CES** — industry employment & wages for leisure / hospitality and food-service splits.
- **USDA NASS commodity paste CSVs** — broilers/turkeys (`$/lb`) and cattle (`$/cwt`), merged in `macro_data`.
- **OpenTable State of Industry** — U.S. monthly YoY change in seated diners from online reservations,
  `opentable_us_seated_diners_online_reservations_yoy_pct`, plus an equal-weight fast-casual-exposed
  city basket index, `opentable_fast_casual_exposed_city_index_yoy_pct`, sourced from
  [OpenTable State of the Restaurant Industry](https://www.opentable.com/c/state-of-industry/#seated-diners-chart).
- **Google Trends** — pytrends monthly keyword and brand interest (`gtrends_fast_casual_monthly.csv`)
  used for category, brand, and consumer-intent checks.
  AI overviews and assistants are changing how people search, so standalone interest is noisier; **relative**
  peer comparisons are the safer read, and the unofficial API caps a comparison at **four** terms—why some
  charts show four Trend lines while GDELT still covers six tickers.
- **MTA Manhattan subway entries** — monthly Manhattan station entries,
  `mta_manhattan_subway_entries_monthly_sum`, used as an NYC office / commuter mobility proxy.
- **BART SF financial-district origin trips** — monthly origin trips from Embarcadero, Montgomery,
  Powell, and Civic Center, `bart_sf_financial_district_origin_trips_monthly`, used as an SF office /
  commuter mobility proxy.
- **GDELT DOC 2.0** — free brand-level media buzz for CMG/CAVA/BROS/SHAK/WING/SG:
  monthly article counts, article share per 100k monitored GDELT articles, and average tone
  (`gdelt_fast_casual_monthly.csv`).
- **Spend anchor ({macro_data.SPEND_EQUIV_BASE_YEAR})** — `equiv_usd_1000_at_{macro_data.SPEND_EQUIV_BASE_YEAR}avg_*`
  on monthly / quarterly (dollars today for a $1000 basket at **{macro_data.SPEND_EQUIV_BASE_YEAR}**
  average prices), including **`{macro_data.SPEND_EQUIV_HEADLINE_CPI_U_ALL_ITEMS_EQUIV_USD_COL}`**
  (headline CPI-U all items, SA — for narrative / CSV, not the restaurant-ingredient chart);
  yearly means in `{macro_data.spend_equiv_annual_dict_key()}` → `mlp_macro_annual_{macro_data.SPEND_EQUIV_BASE_YEAR}_spend_equiv.csv`.
"""
)

st.divider()
st.markdown(
    """
<footer style="text-align: center; padding: 1.5rem 1rem 0.5rem 1rem; margin-top: 0.5rem; font-size: 0.875rem; line-height: 1.65; opacity: 0.88;">
  <div style="font-size: 0.7rem; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 600; margin-bottom: 0.6rem;">Prepared by</div>
  <div style="font-size: 1.05rem; font-weight: 600; letter-spacing: 0.04em;">Tim McLynn</div>
  <div style="margin-top: 0.45rem; font-size: 0.9rem;">May 11, 2026</div>
</footer>
""",
    unsafe_allow_html=True,
)
