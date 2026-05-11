# Streamlit SSS Forecast Dashboard Plan

## Objective

Build a Streamlit app that answers the case prompt as an interactive investment research memo.

The app should forecast same-store sales / same-shop sales for the primary names and use other restaurant companies as industry context.

### Primary forecast tickers

- `CMG`
- `CAVA`
- `BROS`

### Peer / industry read tickers

- `WING`
- `SHAK`
- `SG` (Sweetgreen — wide panel + peer baskets in `sheets_client`)
- `SBUX` (optional / not in current wide build)

### Core framework

Restaurant same-store sales should be decomposed as:

```text
SSS = Traffic + Ticket / Price-Mix
```

The main investment question is:

> Is SSS growth being driven by real traffic demand, or mostly by price / ticket growth?

---

# 1. App Structure

Use the sidebar to navigate between these pages:

```text
1. Overview
2. Data Sourced
3. Industry Backdrop
4. Company Deep Dive
5. Predictive Power
6. SSS Forecast
7. Limitations
8. Supplemental Data
```

---

# 2. Page 1 — Overview

## Purpose

This page introduces the project and explains the modeling framework.

### Suggested text

> This dashboard forecasts same-store sales for CMG, CAVA, and BROS using public company filings, BLS/Census/FRED macro data, and peer restaurant SSS trends. The framework decomposes SSS into traffic and ticket/price-mix. Public data is strongest at forecasting nominal SSS and pricing/ticket growth. It is weaker at forecasting company-specific traffic because traffic depends on brand momentum, promotions, geography, operations, loyalty, and execution.

## Summary table

| Category | Primary tickers | Peer tickers |
|---|---|---|
| Forecast names | CMG, CAVA, BROS | — |
| Industry read | — | SBUX, WING, SHAK |
| Target variable | SSS / same-shop sales | Peer SSS index |
| Main equation | SSS = Traffic + Ticket | Peer demand backdrop |

## Key questions answered

1. What data was sourced?
2. What does the restaurant industry backdrop look like?
3. Which datasets have better predictive power for SSS?
4. What are the four-quarter forward SSS forecasts?
5. What are the limitations?
6. What datasets would improve the work?

---

# 3. Page 2 — Data Sourced

This page answers:

> Identify the datasets that can inform forecasts for SSS and/or costs.

Even if the current app focuses on SSS, include a small note that cost datasets could later be used for margin work.

---

## 3.1 Company-level data table

Create a table with one row per company.

| Ticker | SSS metric | Traffic metric | Ticket metric | Unit metric | Productivity metric |
|---|---|---|---|---|---|
| CMG | Comparable restaurant sales | Transactions | Average check | Company-owned units | Avg restaurant sales |
| CAVA | Same-restaurant sales | Guest traffic | Price/product mix | CAVA restaurants | AUV |
| BROS | System same-shop sales | Transactions | Ticket | Company/franchise shops | AUV / sales per operating week |
| SBUX | U.S. comps | Transactions | Ticket | Stores | Optional |
| WING | Domestic SSS | Limited / not always disclosed | Limited / not always disclosed | Domestic units | AUV |
| SHAK | Same-Shack sales | Optional | Optional | Shacks | AUV / Shack sales |

---

## 3.2 Macro data table

Create a separate table for macro / public datasets.

| Dataset | Source | Use |
|---|---|---|
| Limited-service meals CPI | BLS | Pricing / ticket proxy |
| Food away from home CPI | BLS | Restaurant inflation |
| Food services & drinking places sales | Census | Industry demand |
| Unemployment rate | FRED / BLS | Consumer pressure |
| Gas prices | FRED / EIA | Lower-income consumer pressure |
| Disposable personal income | FRED / BEA | Spending power |
| Consumer sentiment | FRED / University of Michigan | Demand backdrop |

---

# 4. Standardized Data Schema

The dashboard should rely on a standardized table where each row is:

```text
ticker x quarter
```

## 4.1 Core standardized columns

| Column | Description |
|---|---|
| `ticker` | Company ticker |
| `quarter` | Fiscal quarter, e.g. `2026Q1` |
| `quarter_end_date` | Fiscal quarter end date |
| `sss` | Reported comparable / same-store / same-shop sales growth |
| `traffic` | Transactions / guest traffic growth |
| `ticket` | Average check / ticket / price-mix growth |
| `company_sales` | Company-operated restaurant/shop sales |
| `system_sales` | Systemwide sales, if applicable |
| `total_rev` | GAAP reported total revenue |
| `auv` | Reported AUV, if available |
| `auv_ttm` | Reported trailing-twelve-month AUV, if applicable |
| `digital_mix` | Digital / loyalty / rewards mix, if available |
| `owned_units_begin` | Company-operated units at beginning of period |
| `owned_units_open` | Company-operated openings |
| `owned_units_close` | Company-operated closures |
| `owned_units_end` | Company-operated units at end of period |
| `franchise_units_begin` | Franchise/licensed units at beginning of period |
| `franchise_units_open` | Franchise/licensed openings |
| `franchise_units_close` | Franchise/licensed closures |
| `franchise_units_end` | Franchise/licensed units at end of period |
| `system_units_end` | Total system units at end of period |

---

# 5. Company Metric Mapping

## 5.1 CMG mapping

CMG is primarily company-operated. Do not call its revenue `system_sales` unless you footnote it. Use `company_sales` for food & beverage revenue.

| Raw CMG metric | Standard name |
|---|---|
| `SSS` | `sss` |
| `Transaction` | `traffic` |
| `AvgCheck` | `ticket` |
| `FoodBevRev` | `company_sales` |
| `Total` | `total_rev` |
| `DigitalMix` | `digital_mix` |
| `OwnedUnitsBegin` | `owned_units_begin` |
| `OwnedUnitsOpen` | `owned_units_open` |
| `OwnedUnitClose` | `owned_units_close` |
| `OwnedUnitsEnd` | `owned_units_end` |
| `AvgRestSales` | `auv` |

### CMG-specific fields

| Raw CMG metric | Suggested name |
|---|---|
| `IncrCompSales` | `comp_sales_rev_contribution` |
| `Sales not in SSS from CY` | `noncomp_sales_current_year` |
| `Sales not in SSS from LY` | `noncomp_sales_prior_year` |
| `Closure Rev` | `closure_rev_impact` |
| `OtherRev` | `other_rev_bridge` |
| `MenuPrice` | `menu_price` |
| `CheckMix` | `check_mix` |

These are useful for CMG detail pages, but they do not need to be part of the core cross-company forecast model.

---

## 5.2 CAVA mapping

CAVA is company-operated. Use CAVA Revenue as `company_sales`. Do not call it `system_sales`.

| Raw CAVA metric | Standard name |
|---|---|
| `SSS` | `sss` |
| `Traffic` | `traffic` |
| `PriceProductMix` | `ticket` |
| `CAVA Revenue` | `company_sales` |
| `Total Revenue` | `total_rev` |
| `AUV` | `auv` |
| `DigitalMix` | `digital_mix` |
| `OwnedUnitsBegin` | `owned_units_begin` |
| `OwnedUnitsOpen` | `owned_units_open` |
| `OwnedUnitsClose` | `owned_units_close` |
| `OwnedUnitsEnd` | `owned_units_end` |

### CAVA-specific fields

| Raw CAVA metric | Suggested name |
|---|---|
| `ZoeConversionYr` | `zoe_conversion_year_flag` |
| `ExtraWkRevImpact` | `extra_week_rev_impact` |
| `Zoe Revenue` | `zoe_revenue` |
| `ZoeConversion` | `zoe_conversions` |
| `SSS vs 2019` | `sss_vs_2019` |

Use these as context, not core model variables.

---

## 5.3 BROS mapping

BROS should be tracked at both the systemwide and company-operated level.

| Raw BROS metric | Standard name |
|---|---|
| `SSS` | `sss` |
| `Ticket` | `ticket` |
| `Transactions` | `traffic` |
| `CompanySSS` | `company_sss` |
| `CompanyTicket` | `company_ticket` |
| `CompanyTransactions` | `company_traffic` |
| `system_sales` | `system_sales` |
| `CompanyRev` | `company_sales` |
| `TotalRev` | `total_rev` |
| `YrCumAUV` | `auv_ttm` |
| `YrCumCompAUV` | `company_auv_ttm` |
| `DutchRewardsMix` | `rewards_mix` |
| `SystemShopBase` | `system_comp_shop_base` |
| `CompanyShopBase` | `company_comp_shop_base` |
| `CompanyWeeks` | `company_operating_weeks` |
| `FranchiseWeeks` | `franchise_operating_weeks` |

### BROS unit mapping

| Raw BROS metric | Standard name |
|---|---|
| `OwnedUnitsStart` | `owned_units_begin` |
| `OwnedUnitsOpen` | `owned_units_open` |
| `OwnedUnitsClose` | `owned_units_close` |
| `OwnedUnitsEnd` | `owned_units_end` |
| `FranchiseUnitsStart` | `franchise_units_begin` |
| `FranchiseUnitsOpen` | `franchise_units_open` |
| `FranchiseUnitsClosed` | `franchise_units_close` |
| `FranchiseUnitsEnd` | `franchise_units_end` |

### Important BROS revenue note

If `FranchiseRev` is royalty/franchise revenue, do not treat it as franchisee shop sales.

Franchisee shop sales should be estimated as:

```text
estimated_franchise_shop_sales = system_sales - company_sales
```

---

## 5.4 WING mapping

WING is primarily useful as a peer / industry SSS data point.

| Raw WING metric | Standard name |
|---|---|
| `SystemSales` | `system_sales` |
| `AUV` | `auv` |
| `SSS` | `sss` |
| `companySSS` | `company_sss` |
| `DigitalMix` | `digital_mix` |
| `SystemUnit` | `system_units_end` |
| `DomesticUnits` | `domestic_units_end` |
| `IntlUnits` | `international_units_end` |

---

## 5.5 SHAK mapping

SHAK is a simple peer SSS data point unless more metrics are collected.

| Raw SHAK metric | Standard name |
|---|---|
| `SystemSales` | `system_sales` |
| `SSS` | `sss` |

Optional adds if available:

| Metric | Standard name |
|---|---|
| Shack sales | `company_sales` |
| Same-Shack traffic / transactions | `traffic` |
| Price/mix | `ticket` |
| Shack count | `owned_units_end` |
| New openings | `owned_units_open` |

---

# 6. Page 3 — Industry Backdrop

This page answers:

> Please summarize your macro- and industry-level analysis.

---

## 6.1 Chart 1 — Industry sales vs inflation

Plot the following time series:

```text
Census restaurant sales YoY
Food away from home CPI YoY
Limited-service meals CPI YoY
```

Create derived metric:

```text
real_restaurant_demand = restaurant_sales_yoy - food_away_cpi_yoy
```

### Interpretation guide

| Condition | Interpretation |
|---|---|
| Restaurant sales growth > CPI | Real demand / traffic likely healthy |
| Restaurant sales growth ≈ CPI | Growth mostly pricing |
| Restaurant sales growth < CPI | Real demand likely weakening |

---

## 6.2 Chart 2 — Peer SSS index

Build a peer SSS index using the peer names.

```text
peer_sss_index = average(SSS_SBUX, SSS_WING, SSS_SHAK)
```

Plot:

```text
Peer SSS Index
CMG SSS
CAVA SSS
BROS SSS
```

This answers whether the forecast names are outperforming or lagging the broader restaurant group.

---

## 6.3 Chart 3 — Traffic vs ticket

For companies with traffic/ticket data, plot:

```text
Average traffic
Average ticket
Limited-service CPI
```

This answers:

> Is SSS growth being driven by traffic, or mostly by price/ticket?

---

# 7. Page 4 — Company Deep Dive

Add a ticker selector:

```python
ticker = st.selectbox("Select ticker", ["CMG", "CAVA", "BROS", "SBUX", "WING", "SHAK"])
```

## 7.1 KPI cards

For the selected ticker, show:

| KPI | Description |
|---|---|
| Latest SSS | Most recent reported SSS |
| Latest traffic | Most recent transaction / traffic growth |
| Latest ticket | Most recent ticket / price-mix |
| Real SSS | SSS minus limited-service CPI |
| Unit growth | YoY unit growth |
| Peer-relative SSS | Company SSS minus peer SSS index |

---

## 7.2 Chart 1 — SSS bridge

For CMG, CAVA, BROS, and SBUX if available:

```text
SSS
Traffic
Ticket
```

Formula:

```text
SSS ≈ Traffic + Ticket
```

---

## 7.3 Chart 2 — SSS versus macro

Plot:

```text
Company SSS
Peer SSS Index
Limited-service CPI
Real restaurant demand
```

---

## 7.4 Chart 3 — Unit growth / productivity

Use ticker-specific logic.

### CMG

Show:

```text
Owned units
Openings
Food & beverage revenue per average unit
CMG revenue bridge
```

### CAVA

Show:

```text
Units
Net new units
AUV
Zoes conversion flag
```

### BROS

Show:

```text
System units
Company units
Franchise units
System comp shop base coverage
Sales per operating week
```

---

# 8. Page 5 — Predictive Power

This page answers:

> Which datasets have better predictive power for SSS or profitability measures?

Focus on SSS for now.

---

## 8.1 Predictors to test

For each primary forecast ticker, test the relationship between future SSS and:

| Predictor | Target |
|---|---|
| Lagged SSS | Next-quarter SSS |
| Peer SSS index | Company SSS |
| Limited-service CPI | Ticket / SSS |
| Real restaurant demand | Traffic / SSS |
| Consumer sentiment | Traffic |
| Gas prices | Traffic |
| Unit growth | SSS / productivity |

---

## 8.2 Display table

Show a table like:

| Ticker | Best predictor | Correlation | Directional accuracy | Comment |
|---|---:|---:|---:|---|
| CMG | Peer SSS / lagged SSS | x | x | Mature concept, macro-sensitive |
| CAVA | Lagged traffic / peer SSS | x | x | Brand momentum matters |
| BROS | Transactions / rewards mix / ticket | x | x | Frequency-driven beverage model |

Include both:

```text
Correlation with same-quarter SSS
Correlation with next-quarter SSS
```

The next-quarter version is more useful for forecasting.

---

## 8.3 Regression model

Base model:

```text
SSS_t = β0 + β1 * LaggedSSS_t-1 + β2 * PeerSSSIndex_t + β3 * LimitedServiceCPI_t + β4 * RealRestaurantDemand_t
```

For BROS, optionally add:

```text
+ β5 * RewardsMix_t
```

Display model results:

| Ticker | Model R² | MAE | Best variables |
|---|---:|---:|---|
| CMG | x | x | Lagged SSS, peer SSS, CPI |
| CAVA | x | x | Lagged SSS, traffic, peer SSS |
| BROS | x | x | Transactions, ticket, rewards mix |

Important: because the sample is small, keep the model simple and explain that it is directional.

---

# 9. Page 6 — Four-Quarter SSS Forecast

This page is the core prompt answer.

## 9.1 Forecast table

Show:

| Ticker | Quarter | Traffic forecast | Ticket forecast | SSS forecast | Confidence |
|---|---|---:|---:|---:|---|
| CMG | Q+1 | x% | x% | x% | Medium |
| CMG | Q+2 | x% | x% | x% | Medium |
| CMG | Q+3 | x% | x% | x% | Medium |
| CMG | Q+4 | x% | x% | x% | Low |
| CAVA | Q+1 | x% | x% | x% | Medium |
| BROS | Q+1 | x% | x% | x% | Medium |

Forecast equation:

```text
SSS forecast = traffic forecast + ticket forecast
```

---

## 9.2 Forecast logic by company

### CMG

Use:

```text
Lagged SSS
Lagged traffic
Average check
Peer SSS index
Limited-service CPI
Real restaurant demand
```

Interpretation:

> CMG is mature, so peer and macro data should have stronger predictive power than unit-growth metrics.

---

### CAVA

Use:

```text
Lagged SSS
Traffic
Price/product mix
Peer SSS index
Unit growth context
Zoes conversion flag
```

Interpretation:

> CAVA has strong brand momentum but short public history, so forecasts should rely more on recent traffic/ticket trends than regression alone.

---

### BROS

Use:

```text
System SSS
System transactions
Ticket
Company SSS
Rewards mix
Comp shop base coverage
Peer beverage/restaurant SSS
```

Interpretation:

> BROS is frequency-driven. Transactions, ticket, rewards mix, and comp-base coverage are especially important because the company is a high-growth beverage concept with company-operated and franchised shops.

---

# 10. Page 7 — Limitations

This directly answers:

> Describe the limitations of the data.

Show a table:

| Limitation | Why it matters |
|---|---|
| Different SSS definitions | CMG, CAVA, BROS, SBUX, WING, and SHAK define comp bases differently |
| CAVA short history | Limited public quarterly sample |
| BROS comp base excludes newer shops | SSS does not represent the full system |
| BROS AUV definition changed in 2026 | AUV should be treated as directional |
| CPI is category-level | Does not equal company-specific menu pricing |
| Census sales are broad | Includes full-service, fast food, bars, etc. |
| Traffic/ticket not always disclosed | Limits peer decomposition |
| Peer index is noisy | Peers have different concepts and consumer bases |
| Public data is lagged | Not real-time enough for intra-quarter forecasting |
| Promotions and mix are hard to observe | Can distort traffic/ticket |

Suggested text:

> The model should be viewed as a directional forecasting framework, not a precise quarterly earnings model.

---

# 11. Page 8 — Supplemental Data

This answers:

> What datasets can supplement or improve the above?

Use this table:

| Dataset | Improves | Why |
|---|---|---|
| Credit/debit card data | SSS | Real-time spend and ticket |
| Foot traffic data | Traffic | Direct visit read |
| Menu price scraping | Ticket | Company-specific pricing |
| Mobile app / loyalty data | Traffic | Frequency and engagement |
| Google Trends | Demand | Brand interest proxy |
| Delivery app scraping | Ticket / mix | Promo and delivery dynamics |
| Placer.ai / SafeGraph | Traffic | Location-level visits |
| Technomic / Black Box | Industry comps | Better restaurant benchmark |
| Job postings | Unit growth / labor | Opening pace and staffing |
| Weather data | Traffic | Especially relevant for beverage concepts |

---

# 12. Core Calculations

## 12.1 SSS bridge

```text
sss_check = traffic + ticket
```

## 12.2 Real SSS

```text
real_sss = sss - limited_service_cpi_yoy
```

## 12.3 Peer SSS index

```text
peer_sss_index = average(sss for SBUX, WING, SHAK)
```

## 12.4 Peer-relative performance

```text
relative_sss = company_sss - peer_sss_index
```

## 12.5 Real restaurant demand

```text
real_restaurant_demand = census_restaurant_sales_yoy - food_away_from_home_cpi_yoy
```

## 12.6 Unit growth

```text
unit_growth_yoy = units_end_t / units_end_t_minus_4 - 1
```

## 12.7 BROS comp-base coverage

```text
system_comp_base_coverage = system_comp_shop_base / system_units_end
company_comp_base_coverage = company_comp_shop_base / owned_units_end
```

## 12.8 BROS operating-week productivity

```text
system_operating_weeks = company_operating_weeks + franchise_operating_weeks
system_sales_per_operating_week = system_sales / system_operating_weeks
company_sales_per_operating_week = company_sales / company_operating_weeks
```

## 12.9 BROS estimated franchise shop sales

```text
estimated_franchise_shop_sales = system_sales - company_sales
```

---

# 13. Suggested Streamlit Implementation Notes

## 13.1 Data model

Recommended files:

```text
data/company_metrics_raw.csv
 data/company_metrics_standardized.csv
 data/macro_quarterly.csv
 data/metric_mapping.csv
```

## 13.2 Suggested app folders

```text
app.py
pages/
    1_Overview.py
    2_Data_Sourced.py
    3_Industry_Backdrop.py
    4_Company_Deep_Dive.py
    5_Predictive_Power.py
    6_SSS_Forecast.py
    7_Limitations.py
    8_Supplemental_Data.py
utils/
    data_loader.py
    calculations.py
    charts.py
    modeling.py
```

## 13.3 Keep raw and common names

Use both the original metric label and the standardized field.

| Field | Purpose |
|---|---|
| `metric` | Raw company label |
| `common_name` | Standardized dashboard label |
| `metric_group` | SSS, Traffic, Ticket, Revenue, Units, Productivity, Company-Specific |
| `unit_type` | %, dollars, units, weeks |
| `source_type` | reported or calculated |
| `use_in_model` | yes/no |

Example:

| Ticker | Metric | Common Name | Metric Group | Unit Type | Use In Model |
|---|---|---|---|---|---|
| BROS | Transactions | traffic | SSS Bridge | % | yes |
| BROS | CompanyWeeks | company_operating_weeks | Productivity | weeks | no |
| CMG | IncrCompSales | comp_sales_rev_contribution | Revenue Bridge | dollars | no |
| CAVA | ZoeConversionYr | zoe_conversion_year_flag | Company-Specific | flag | no |

---

# 14. Final App Narrative

The dashboard should tell this story:

> Restaurant SSS is best understood as traffic plus ticket. Public macro data, especially limited-service CPI and restaurant sales, helps explain the pricing and broad demand backdrop. Peer SSS adds a useful industry momentum signal. For CMG, macro and peer trends should have relatively strong predictive power. For CAVA, recent traffic/ticket momentum and brand maturity matter more because the public history is short. For BROS, transactions, ticket, rewards mix, and comp-base coverage are especially important because the company is a high-growth beverage concept with a mix of company-operated and franchised shops.

---

# 15. What Not To Overbuild Yet

Do not prioritize these for the initial SSS dashboard:

| Item | Reason |
|---|---|
| Food, beverage, and packaging costs | Margin analysis, not SSS |
| Labor costs | Margin analysis |
| Occupancy costs | Margin analysis |
| G&A | Corporate profitability, not SSS |
| EPS / EBITDA | Outside current SSS scope |
| Detailed commodity baskets | Useful later for cost/profitability module |

These can become a second version of the app focused on restaurant-level profitability.

