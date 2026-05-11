import streamlit as st


st.title("Dataset info")

st.markdown(
    """
This tab is a quick roadmap for the data I would add next: which sources are most useful for predicting
**same-store sales**, which help explain **restaurant-level profitability**, and where those sources can be
overstated. The best incremental data falls into three buckets: restaurant operating inputs, awareness /
mobility signals, and raw purchase / company-level data.

The core caution is that no single data set is a clean proxy for SSS. Restaurant comps are a mix of
traffic, price, menu mix, digital mix, discounting, new-store cannibalization, local market exposure, and
weather / calendar effects. The right workflow is to combine a few imperfect signals and validate them
against reported comps.
"""
)

st.subheader("Highest-Value Adds")
st.markdown(
    """
| Use case | Best data | Why |
|---|---|---|
| **SSS / brand demand** | Raw card transactions, mobility / foot traffic, Similarweb, app data, and mature-market exposure | These get closest to the funnel: awareness, visits, transactions, frequency, and check. |
| **Profitability** | Food commodities, labor, rent / real estate, utilities / energy, and company pricing / mix | Margins depend on whether price and traffic can offset COGS, labor, occupancy, and delivery / digital costs. |
| **Initiatives and category context** | Receipt panels, loyalty / app data, Circana / NPD, Black Box, Technomic, and social attention tools | These help test whether a menu item, promotion, or category shift is actually changing behavior. |

If I had to buy only a few data sets, I would start with **stable-panel card transactions**, **mobility /
trade-area data**, **receipt data**, and **local labor / commodity / rent inputs**. For SSS, transaction
and mobility data generally matter more than broad macro. For profitability, cost inputs and company
pricing / mix disclosures matter more than awareness signals.
"""
)

st.subheader("1) Restaurant Business Inputs")
st.markdown(
    """
These are the highest-value additions for understanding the **cost function** and local operating backdrop
of a fast casual restaurant. This is mostly a paid-data roadmap: the goal is to get closer to store-level
costs, local conditions, and weather / calendar noise than broad national macro can provide. I would still
keep public data where it creates a useful baseline or free cross-check.

| Data set | Stronger for | Why it matters | Main limitation |
|---|---|---|---|
| **Paid commodity / procurement data, with USDA NASS and CME as public cross-checks** | Costs / profitability | Better reads on proteins, produce, dairy, eggs, grains, packaging, and freight than broad CPI. Useful for chains with known menu concentration and commodity exposure. | Still may not match contracted purchasing, hedging, freight lanes, supplier mix, or company-specific specs. |
| **Local labor data: ADP, Homebase, UKG, minimum-wage trackers, with BLS as baseline** | Labor costs / profitability | Labor is a major restaurant cost. Local wage pressure, hours worked, hiring difficulty, and minimum-wage changes can affect both margins and service capacity. | Mix of hourly roles, tips, franchisees, and scheduling productivity is hard to infer externally. |
| **Weather: Planalytics / Tomorrow.io / local NOAA history** | SSS / traffic / margins | Weather can move restaurant traffic, delivery mix, daypart, patio usage, and local demand. It is also useful for explaining noisy quarters and separating brand weakness from storms, heat, or unusual precipitation. | Needs ticker-level, store-level, or trade-area matching; weather effects vary by region, concept, daypart, and delivery exposure. |
| **Energy and transportation data: OPIS / GasBuddy / EIA** | Consumer pressure and costs | Gasoline, diesel, electricity, and natural gas help frame commuting burden, delivery costs, utility pressure, and consumer wallet pressure. | Energy is usually an indirect SSS driver and only a partial restaurant cost driver unless paired with unit-level economics. |
| **CoStar / Green Street / local CRE data** | Occupancy cost / unit economics | Rent and site quality matter for store profitability, expansion, and mature-unit productivity. | Lease economics are negotiated and local; public store counts do not reveal occupancy costs. |

For any of these, I would prioritize data that can be joined by **MSA / ZIP / trade area** rather than only
national time series. The unique use of free macro data is as a baseline: CPI / PPI, BLS labor, USDA, CME,
EIA, and NOAA can help sanity-check the paid feeds and make the analysis reproducible when a paid panel is
not available.
"""
)

st.subheader("2) Awareness & Mobility Signals")
st.markdown(
    """
These sources help explain whether the consumer has the occasion, awareness, and digital intent to visit a
brand. For fast casual, that means office traffic, convenience, local visitation, branded attention, and app
engagement. This group is most useful for predicting **traffic, visit frequency, awareness, and channel
mix**, then validating whether those signals show up in SSS.

| Data set | Stronger for | Best use | Main limitation |
|---|---|---|---|
| **Kastle RTO office data** | SSS / lunch occasions | Measures return-to-office patterns that affect lunch, urban, and commuter-heavy restaurant occasions. | Office badge data is concentrated in certain buildings and markets; not a universal measure of work behavior. |
| **MTA Manhattan subway entries / BART SF financial-district trips** | SSS / lunch occasions | Free public commuter proxies for NYC and SF office-district recovery, useful for urban concepts and lunch-heavy dayparts. | Only covers two transit-heavy markets; ridership can reflect commuting, tourism, events, fare policy, and station disruptions rather than restaurant demand alone. |
| **PlaceIQ / Placer.ai / SafeGraph / Veraset mobility** | SSS / traffic | Foot traffic, trade-area visitation, competitive leakage, and local market health. Useful for mature-market SSS and unit productivity. | Device panels change over time; visits do not equal transactions and can be biased by phone ownership or app permissions. |
| **Google Trends** | Awareness / demand intent | Free search-interest series for brands, menu terms, value-seeking, health / GLP-1 pressure, delivery, takeout, and category demand. | Relative index, not volume; geography and query wording matter, and spikes can reflect media attention instead of purchases. |
| **Similarweb** | Digital demand / awareness | Website traffic, referral sources, app / web engagement, and digital funnel checks. | Digital traffic can reflect promotions, hiring, PR, investor events, or menu browsing rather than purchases. |
| **GDELT / Google News volume** | Brand buzz / media attention | Free downloadable time series for brand-level article volume and normalized article share. Useful as a media-attention proxy for public chains and product / controversy spikes. | Measures press coverage, not consumer visits or purchases; broad brand names and acronyms need carefully scoped queries. |
| **TickerTrends / social attention tools** | Consumer attention | Consumer attention, viral products, new menu launches, and awareness inflections. | Social buzz can be loud but financially small; demographics and bot / media amplification can distort signal. |
| **Apptopia / Sensor Tower / data.ai** | Digital engagement | App downloads, rank, sessions, loyalty adoption, and digital ordering engagement. | App activity is more relevant for brands with strong digital mix; downloads can spike from promotions without durable traffic. |

These are useful leading indicators, but I would not treat them as sales on their own. The best workflow is
to use them to identify likely changes in awareness, occasion, or traffic, then validate the signal against
reported comps, card transactions, receipts, or mobility-confirmed visits.
"""
)

st.subheader("3) Raw Transaction, Receipt, and Industry Data")
st.markdown(
    """
This bucket is most useful for understanding which brands are actually having success individually. These
sources sit closer to the purchase event than awareness or mobility data, so they are better for separating
brand-specific momentum from category growth, new-unit growth, or broad macro noise.

| Data set | Stronger for | Best use | Main limitation |
|---|---|---|---|
| **RawCard transaction data** | SSS / check / frequency | Best source for estimating brand-level spend, transactions, frequency, and average check. If store-level identifiers are available, it can approximate SSS directly by holding the comparable-store base constant; if not, states or markets with limited new-unit growth can help isolate same-store demand from expansion. | Requires careful panel stability, merchant mapping, tender mix adjustment, and separation of new units, closures, relocations, and delivery marketplace transactions from same-store behavior. |
| **Receipt data: Numerator, Fetch, Circana / NPD receipt panels** | Basket / initiative impact | Basket composition, attach rates, specific initiatives, limited-time offers, discounting, and household repeat behavior. | Receipt panels are not a census; sample bias and receipt capture quality can overstate precision. |
| **Traditional industry data: Circana / NPD, Black Box Intelligence, Technomic** | Industry benchmark / profitability context | Industry traffic, ticket, pricing, daypart, menu category, and operator benchmarking. | Strong benchmarking, but definitions may differ from company-reported SSS and panels may underrepresent private / regional competitors. |

For SSS forecasting, the strongest version would combine raw card data with mobility and awareness signals
at the **mature-market level**. Raw transactions can get close to the math of SSS by decomposing spend into
transaction count and average check, while non-growth states or mature trade areas help reduce the
distortion from new restaurant openings. Receipt data then explains what changed inside the basket, and
traditional industry data provides the category benchmark.
"""
)

st.subheader("Limitations and Common Overstatements")
st.markdown(
    """
- **National macro is not local demand.** The public data in this case is mostly national. Restaurant SSS is
  local: income, office recovery, weather, competition, and store density differ by market.
- **Calendar macro does not perfectly match fiscal reporting.** The dashboard aligns macro data to fiscal
  period end dates, but fiscal periods can span calendar months or quarters.
- **SSS is not the same as total brand sales.** New units, closures, relocations, franchise mix, delivery
  marketplaces, and cannibalization can make brand-level spend look better or worse than same-store demand.
- **Traffic is not transactions; only transaction data can be sure of a sale.** Card data sees tendered
  spend; receipt data sees captured baskets; mobility sees visits. Each is a proxy with a different denominator.
- **Awareness is not conversion.** Google Trends, Similarweb, Semrush, and social attention can identify
  interest, but they should not be interpreted as sales without validating against transactions or visits.
- **Commodity data is not company COGS.** Public USDA / BLS / futures data can explain broad inflation
  pressure, but chains buy through contracts, suppliers, freight lanes, hedges, and menu-specific specs.
- **Panels drift.** Card, receipt, and mobility panels can change because of issuer relationships, app
  permissions, device mix, geography, and user demographics. Stable-panel methods are critical.
- **Coverage varies by brand.** Some concepts have stronger digital, loyalty, urban, or office exposure,
  making a given data set more predictive for one brand than another.
- **Backtests can overstate precision.** Small public-company peer sets, few fiscal periods, and overlapping
  macro cycles make it easy to find a relationship that does not hold out-of-sample.

The strongest claim I would make from these data sets is directional: they can improve the odds of
identifying traffic pressure, pricing power, cost inflation, and brand-specific momentum. I would not claim
that any one third-party data source fully predicts reported SSS without company disclosure and careful
out-of-sample validation.
"""
)
