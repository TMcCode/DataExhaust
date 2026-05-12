# MLP Restaurant — Fast-Casual Same-Store-Sales Case Study

A Streamlit dashboard and ETL pipeline analyzing U.S. fast-casual same-store
sales against macro and alternative data. Anchored on **CMG**, **CAVA**, and
**BROS** with **SHAK**, **WING**, and **SG** as peers.

> **Live dashboard:** _(paste your Streamlit Community Cloud URL here after deploy)_

The narrative content (what the analysis says, charts, forecasts, limitations) lives
inside the dashboard itself — start at the **Overview** page. This README explains
how the code is laid out and how to run it.

---

## Quick start (zero credentials, ~2 minutes)

```bash
git clone https://github.com/TMcCode/DataExhaust.git
cd DataExhaust
pip install -r requirements.txt
streamlit run app.py
```

The dashboard ships with a frozen 250 KB data snapshot
(`data/snapshots/mlp_dashboard_bundle.pkl.gz`) so it renders end-to-end without
any API keys, service-account JSON, or network access. Everything you'd see on
the live URL is what you'll see locally.

> Python 3.9–3.12 should all work; the snapshot is pickle-protocol-portable.

---

## Two processes

The repo contains a deliberate split between **ETL** (rebuilds the data) and
**serving** (renders the dashboard):

```
                          ┌──────────────────────────────────────┐
   Live sources           │              ETL  (CLI)              │
                          │                                      │
   FRED ─────────────────▶│  load_mlp_master.py orchestrates     │
   BLS ──────────────────▶│  per-source pulls and writes:        │
   USDA paste CSVs ──────▶│    - merged CSVs                     │
   Google Sheets ────────▶│    - gzip+pickle bundle to GCS       │
   GDELT / Trends ───────▶│      (gs://.../mlp_dashboard_bundle) │
   OpenTable / MTA / BART▶│                                      │
                          └──────────────────┬───────────────────┘
                                             │
                                             ▼
                          ┌──────────────────────────────────────┐
                          │       Dashboard  (Streamlit)         │
                          │                                      │
                          │  app.py + streamlit_dashboard/       │
                          │                                      │
                          │  Reads (in order):                   │
                          │    1. GCS pickle snapshot            │
                          │    2. local snapshot in data/        │
                          │    3. live-API rebuild               │
                          │                                      │
                          │  Never writes to disk at runtime.    │
                          └──────────────────────────────────────┘
```

Why split it: the ETL is slow, hits rate-limited APIs, and needs credentials.
The dashboard should be fast, deterministic, and runnable by anyone. Serving
from a precomputed snapshot lets a reviewer click a link and have everything
load instantly.

---

## Data sources

All free / public. Detailed treatment, columns, and series codes are documented
on the **Overview** page of the dashboard.

| Source | What it provides | Module |
|---|---|---|
| **Google Sheets workbook** | Per-ticker historical fiscal metrics (traffic / ticket / mix), fiscal calendar, metric names, SSS forecasts | `sheets_client.py` |
| **FRED** (St. Louis Fed) | Unemployment, real income, sentiment, CPI (headline / core / FAFH), PPI retail rent, gas, retail sales | `macro_data.py` |
| **BLS CES** | Industry employment & wages — leisure / hospitality / food-service splits | `bls_data.py` |
| **USDA NASS paste CSVs** | Monthly broiler/turkey ($/lb) and beef cattle ($/cwt) prices received | `commodity_paste_csv.py` |
| **OpenTable State of Industry** | U.S. monthly YoY seated diners + fast-casual-exposed city basket | `opentable_state_industry.py` |
| **Google Trends** (pytrends) | Monthly keyword / brand interest for category and consumer-intent reads | `gtrends_monthly_brands.py` |
| **GDELT DOC 2.0** | Monthly brand article counts, article share per 100k, average tone | `gdelt_monthly_brands.py` |
| **MTA** | Manhattan subway entries — NYC office / commuter mobility proxy | `mta_manhattan_subway.py` |
| **BART** | SF financial-district origin trips — SF office / commuter mobility proxy | `bart_sf_ridership.py` |

The dashboard reads the **outputs** of these pulls (frozen in the snapshot
bundle or, if rebuilding live, in CSVs). The ingestion code itself runs only
during ETL.

---

## Project layout

```
.
├── app.py                          # Streamlit entrypoint
├── app_appendix.py                 # secondary appendix app (optional)
├── requirements.txt                # runtime deps
├── README.md                       # this file
│
├── streamlit_dashboard/            # dashboard package
│   ├── data_loader.py              # GCS -> local snapshot -> live API
│   ├── theme.py                    # global styles, dark-mode toggle
│   ├── gtrends_loader.py
│   ├── peer_gtrends_utils.py
│   └── pages/                      # multipage nav
│       ├── overview.py
│       ├── data_sourced.py
│       ├── macro_industry_sss.py
│       ├── sss_forecast.py
│       └── data_roadmap_limitations.py
│
├── data/                           # input CSVs (read at runtime by some pages)
│   └── snapshots/
│       └── mlp_dashboard_bundle.pkl.gz   # 250 KB frozen demo bundle
│
├── load_mlp_master.py              # ETL orchestrator
├── build_feature_tables.py         # standalone feature-table CLI
├── macro_data.py                   # FRED + BLS + commodity + alt-data merge
├── feature_panel.py                # fiscal × macro joined panels
├── analytic_panel.py
├── sheets_client.py
├── mlp_gcs_snapshot.py             # gzip+pickle snapshot upload/download/local-read
│
├── bls_data.py                     # BLS CES pulls
├── usda_nass_data.py               # USDA NASS Quick Stats pulls (optional path)
├── commodity_paste_csv.py          # broilers + beef from analyst-pasted CSVs
├── opentable_state_industry.py     # OpenTable State of Industry scraper / loader
├── gtrends_monthly_brands.py       # pytrends puller
├── gdelt_monthly_brands.py         # GDELT DOC 2.0 puller
├── mta_manhattan_subway.py         # MTA entries
├── bart_sf_ridership.py            # BART trips
│
├── scripts/
│   ├── setup_mlp_venv.sh           # one-shot venv bootstrap
│   ├── run_dashboard.sh
│   ├── check_gcs_permissions.py    # LIST/READ/WRITE/DELETE probe on the GCS bucket
│   ├── upload_runtime_csvs_to_gcs.py  # publish runtime CSVs to gs://.../source/csvs/
│   └── test_gcs_snapshot.py        # smoke-test the GCS snapshot URI
│
├── .env.example                    # template — copy to .env (gitignored)
└── .streamlit/
    ├── config.toml                 # theme defaults
    └── secrets.toml.example        # template — copy to secrets.toml (gitignored)
```

---

## Configuration

The dashboard works **without** any configuration thanks to the local snapshot.
The variables below are only needed if you want to override that path or run
the ETL.

| Variable | Purpose |
|---|---|
| `MLP_GCS_SNAPSHOT_URI` | When set, dashboard prefers this gzip+pickle bundle over the local snapshot |
| `GOOGLE_APPLICATION_CREDENTIALS` / `GOOGLE_SHEETS_CREDENTIALS` | Service-account JSON path; required for GCS and live Sheets |
| `FRED_API_KEY` | Required by the ETL (and the live-API fallback) for FRED pulls |
| `BLS_REGISTRATION_KEY` | Optional but recommended for higher BLS rate limits |
| `MLP_GDELT_CSV`, `MLP_GDELT_LONG_CSV`, `MLP_GTRENDS_CSV`, `BART_SF_RIDERSHIP_MONTHLY_CSV`, `MTA_MANHATTAN_SUBWAY_MONTHLY_CSV`, `OPENTABLE_US_SEATED_DINERS_MONTHLY_CSV`, `MLP_BROILERS_CSV`, `MLP_BEEF_CSV` | Each accepts a local path or `gs://...` URI to override the repo-bundled CSV for that source |

Copy `.env.example` to `.env` (and/or `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml`) and fill in only what you need. Both are gitignored.

---

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub (public or private).
2. On <https://share.streamlit.io>, **New app** → select the repo → entrypoint
   `app.py`.
3. **Settings → Secrets** is optional. With nothing pasted, the app serves
   from the frozen snapshot. To enable the GCS fast path, paste:
   ```toml
   MLP_GCS_SNAPSHOT_URI = "gs://your-bucket/source/mlp_dashboard_bundle.pkl.gz"
   GOOGLE_SERVICE_ACCOUNT_JSON = """{ ...the data-exhaust-key.json contents... }"""
   ```
4. Deploy. First load takes ~30–60 s while dependencies install; subsequent
   loads are near-instant because Streamlit's `@st.cache_data` warms the bundle.

---

## Refreshing the snapshot (production workflow)

The frozen `data/snapshots/mlp_dashboard_bundle.pkl.gz` is what ships with the
repo. To refresh it from live sources:

```bash
# 1. Make sure FRED_API_KEY, BLS_REGISTRATION_KEY, and the GCS service account
#    are set (see .env.example).

# 2. Rebuild the bundle and upload it to GCS.
python load_mlp_master.py \
    --gcs-snapshot-uri gs://data-exhaust_cloudbuild/source/mlp_dashboard_bundle.pkl.gz

# 3. Re-publish the 8 runtime input CSVs to GCS (idempotent — skips md5 matches).
python scripts/upload_runtime_csvs_to_gcs.py

# 4. Re-sync the in-repo snapshot to match what's now in GCS, and commit.
gsutil cp gs://data-exhaust_cloudbuild/source/mlp_dashboard_bundle.pkl.gz \
          data/snapshots/mlp_dashboard_bundle.pkl.gz
git add data/snapshots/mlp_dashboard_bundle.pkl.gz
git commit -m "chore: refresh snapshot bundle (YYYY-MM-DD)"
```

---

## Limitations

Documented in detail on the dashboard's **Dataset info** page. Short version:
national series are not local comps, search / news are not sales, commodity
indexes are not contract COGS, two transit markets are not the national store
base, and fiscal vs. calendar alignment is approximate.

---

## Author

Tim McLynn — May 2026
