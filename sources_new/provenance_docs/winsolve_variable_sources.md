# Data Collection Brief: OBR Macroeconomic Model Inputs

## Context

We are building a replication of the OBR's macroeconomic model (called "Winsolve") so that CBP can run its own fiscal scenarios. The model has ~370 equations that describe how the UK economy fits together — GDP components, tax receipts, public spending, debt, etc.

To run the model, we need to feed it ~180 input variables: things like quarterly GDP, tax receipts, interest rates, population, and tax policy parameters. We have already loaded about 80 of these from the OBR's published Economy forecast tables. This document describes the remaining ~100 variables and where to get them.

**All of this data is publicly available.** The OBR uses the same sources — ONS, HMRC, Bank of England — they just have an internal database that automates the collection. We are building the equivalent mapping by hand.

### How to read this document

The work is split into 8 jobs, organised by data source. Each job lists:
- **Where to get the data** (publication name, URL, format)
- **What to extract** (specific series, with the internal model variable name)
- **How to process it** (units, frequency conversion, etc.)
- **How many model variables it covers**

You do not need to understand the model to do this work. You are collecting time series and saving them in a consistent format. The variable names (like `VREC` or `TYEM`) are the model's internal codes — just treat them as labels.

### Deliverable format

For each job, deliver a single CSV per source with columns:

```
date,VARIABLE1,VARIABLE2,...
2008Q1,123.4,56.7,...
2008Q2,125.1,57.2,...
```

- Dates as `YYYYQN` (e.g., `2008Q1`, `2024Q3`)
- Values in **£ billion** unless otherwise noted (price indices stay as index levels)
- Calendar quarters: Q1 = Jan–Mar, Q2 = Apr–Jun, Q3 = Jul–Sep, Q4 = Oct–Dec
- Coverage: as far back as the source allows, ideally from 1997Q1

Save files to `data/timeseries/` with a clear filename (e.g., `hmrc_quarterly_receipts.csv`).

---

## What we already have (for reference)

77 variables are loaded from OBR Economy forecast tables and model constants. You don't need to touch these. They cover:

- Real and nominal GDP expenditure components (sheets 1.1, 1.2)
- Labour market indicators (sheet 1.6)
- Price indices — CPI, RPI, GDP deflator (sheet 1.7)
- Interest rates, exchange rates, oil price, equity prices (sheet 1.9)
- Balance of payments (sheet 1.8)
- Household income and balance sheet (sheets 1.11, 1.12)
- ~20 fixed model constants (depreciation rates, index weights)

---

## Job 1: HMRC Quarterly Tax Receipts

**This is the highest-priority job.** It unlocks the largest number of model equations (~80).

### Where to get it

HMRC publishes monthly tax receipts for every major tax head:
- **Publication**: *HMRC Tax and NICs Receipts for the UK*
- **URL**: https://www.gov.uk/government/statistics/hmrc-tax-and-nics-receipts-for-the-uk
- **Format**: Excel workbook. One sheet per tax, monthly figures in £ million.
- **Updated**: Monthly, about 3 weeks after month end.

### What to do

1. Download the latest workbook.
2. For each tax head listed below, extract the monthly series.
3. Sum to calendar quarters (Jan+Feb+Mar = Q1, etc.).
4. Convert from £m to £bn (divide by 1000).

### Variables to extract

| Model name | HMRC tax head | Notes |
|------------|--------------|-------|
| TYEM | Income tax — PAYE | Largest line. Steady monthly profile |
| TSEOP | Income tax — Self Assessment | Lumpy: big payments in January and July |
| TCINV | Income tax — other | May need: total IT minus PAYE minus SA |
| EENIC | National Insurance — employee | HMRC splits employee/employer since ~2008 |
| EMPNIC | National Insurance — employer | |
| VREC | VAT (net of refunds) | |
| NSCTP | Corporation tax — North Sea | HMRC may label as "offshore" |
| NNSCTP | Corporation tax — non-North Sea | Main CT line minus North Sea |
| CGT | Capital gains tax | Very lumpy (SA-driven) |
| INHT | Inheritance tax | |
| TSD | Stamp duty (land tax + shares) | Sum both stamp duty lines |
| TXFUEL | Fuel duties | "Hydrocarbon oil duties" in HMRC |
| TXTOB | Tobacco duties | |
| TXALC | Alcohol duties | Sum: beer + wine + spirits + cider |
| CCL | Climate change levy | |
| IPT | Insurance premium tax | |
| TXCUS | Customs duties | |
| PRT | Petroleum revenue tax | Near zero now; still in model |
| AL | Aggregates levy | |
| BETLEVY | Bank levy | |
| BETPRF | Energy profits levy | Only exists from 2022 onwards |

**~21 variables.**

### Watch out for

- HMRC publishes in **£ million**. The model uses **£ billion**.
- Some lines are labelled differently across vintages of the workbook. Match by tax concept, not column position.
- Self Assessment receipts have extreme seasonality (Jan spike). This is correct — don't smooth it.
- Pre-2008 data may not split employee/employer NICs. If so, note the gap.

---

## Job 2: ONS Trade Price Indices

### Where to get it

- **Publication**: ONS, *UK Trade* and *Balance of Payments* quarterly tables
- **URL**: https://www.ons.gov.uk/economy/nationalaccounts/balanceofpayments
- **Format**: CSV download or ONS API. Quarterly index levels.
- **Also**: ONS Producer Price Indices (PPI), dataset `MM22`

### What to extract

| Model name | Concept | Notes |
|------------|---------|-------|
| PMNOG | Import price index — goods excluding oil | ONS trade tables, or derive from total goods imports deflator minus SITC 33 (oil) |
| PXNOG | Export price index — goods excluding oil | Same approach on exports side |
| PMS | Import price index — services | ONS BoP services deflator |
| PXS | Export price index — services | ONS BoP services deflator |
| PMOIL | Import price of oil (in sterling) | Can compute from data we already have: Brent price ÷ USD/GBP exchange rate. Cross-check against ONS |
| PXOIL | Export price of oil | Same as PMOIL |
| PPIY | Producer price index — output, manufacturing | ONS PPI dataset |

**~7 variables.**

### Notes

- Price indices should be levels (e.g., 2019=100), not percentage changes.
- Check the base year — ONS rebases periodically. Record which base year your download uses.
- For PMOIL/PXOIL: we already have Brent crude in USD (`PBRENT`) and USD/GBP rate (`RXD`). Sterling oil price = PBRENT / RXD. Extract this from ONS as a cross-check, but computing it is acceptable.

---

## Job 3: Population and Public Sector Employment

### 3a. Population

- **Source**: ONS mid-year population estimates
- **URL**: https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates
- **Format**: Excel, annual (mid-year = 30 June)

| Model name | What to get |
|------------|------------|
| POPAL | Total population, all ages |
| POP16 | Population aged 16 and over |
| GAD1 | Population aged 0–15 |
| GAD2 | Population aged 16–64 |
| GAD3 | Population aged 65 and over |

Since these are annual, **linearly interpolate to quarterly**. Mid-year (Q2 of each year) gets the published value; other quarters are interpolated between adjacent years.

### 3b. Additional labour market series

- **Source**: ONS Labour Force Survey, via NOMIS or ONS download
- **URL**: https://www.nomisweb.co.uk/ or ONS labour market statistics page

| Model name | What to get |
|------------|------------|
| ETLFS | Total employment, LFS basis, in thousands |
| ESLFS | Self-employment, LFS basis, in thousands |
| ES | Self-employment, workforce jobs basis |

Note: we already have total employment in millions (`ET`) from the OBR. `ETLFS` should be the same concept but in thousands. Verify they match (ETLFS ≈ ET × 1000).

### 3c. Public sector employment

- **Source**: ONS Public Sector Employment Statistics
- **URL**: https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/publicsectorpersonnel
- **Format**: Excel, quarterly, headcount in thousands

| Model name | What to get |
|------------|------------|
| EGG | General government employment (= central + local) |
| ECG | Central government employment |
| ELA | Local authority employment |

**~10 variables total across 3a–3c.**

---

## Job 4: OBR Supplementary Tables

Before downloading anything new, check whether these are already in the workbooks we have in `data/`.

### Files to check first

- `data/Forecast-evaluation-report-–-July-2025-annex-A-–-supplementary-economy-tables.xlsx`
- `data/Economy_Detailed_forecast_tables_March_2025.xlsx` (sheets beyond 1.1–1.12)
- `data/Long-term-economic-determinants-March-2025-EFO.xlsx`

### Variables to find

| Model name | What it is | Where to look |
|------------|-----------|---------------|
| TRGDP | Trend (potential) real GDP, £bn | OBR output gap data or supplementary Table 1.4. Alternative: compute from actual GDP and published output gap |
| XS | Exports of services, real £bn | OBR trade decomposition |
| XOIL | Exports of oil, real £bn | OBR trade decomposition |
| MS | Imports of services, real £bn | OBR trade decomposition |
| MOIL | Imports of oil, real £bn | OBR trade decomposition |
| NSGVA | North Sea GVA, real £bn | OBR supplementary |
| MAJGDP | World GDP index (trade-weighted) | OBR world economy assumptions |
| WPG | World goods price index (foreign currency) | OBR world economy assumptions |
| WEQPR | World equity price index | OBR world economy assumptions |

**~8 variables.** Some of these may be in OBR files we already have but haven't parsed yet. If you find them, note the exact sheet and column.

---

## Job 5: Tax Policy Parameters

These are **not time series** in the usual sense. They are statutory rates that change when the government changes policy at a Budget. You are building a lookup table of rates by quarter.

### Where to find them

- HMRC Rates and Allowances pages: https://www.gov.uk/government/collections/tax-rates-and-allowances
- Budget/Autumn Statement documentation
- IFS Briefing Notes on Budget measures (for historical changes)

### Parameters to collect

| Model name | What it is | Current value |
|------------|-----------|---------------|
| TCPRO | Corporation tax main rate | 25% (from April 2023) |
| NIS | Employer NI rate above secondary threshold | 13.8% → 15% (from April 2025) |
| DISCO | HM Treasury discount rate | 3.5% (Green Book rate) |
| FP | First-year plant & machinery allowance | 100% (full expensing, from April 2023) |
| SP | Writing-down allowance, main pool | 18% |
| SV | Writing-down allowance, special rate pool | 6% |
| IIB | Structures & buildings allowance rate | 3% (from 2018) |
| SIB | Structures writing-down allowance | 0% (SBA replaced WDA) |
| TPBRZ | Mortgage interest relief rate | 0% (abolished April 2000) |

For each parameter, build a quarterly time series from 1997Q1 showing the rate in force that quarter. Most will be constant for long stretches, stepping when legislation changes.

**~9 variables.**

---

## Job 6: ONS Sector Accounts (Public Expenditure Components)

### Where to get it

- **Source**: ONS Quarterly Sector Accounts and Blue Book
- **URL**: https://www.ons.gov.uk/economy/nationalaccounts
- **Also check**: `data/Expenditure_Detailed_forecast_tables_March_2025.xlsx` — the OBR may publish these breakdowns at fiscal year frequency

### Variables to extract

These are all quarterly, £bn, split by government sub-sector:

| Model name | What it is |
|------------|-----------|
| RCGIM | Central government capital consumption (depreciation) |
| RLAIM | Local authority capital consumption |
| PCCON | Public corporation capital consumption |
| CGIPS | Central government gross investment, nominal |
| LAIPS | Local authority gross investment, nominal |
| IBPC | Public corporation gross investment |
| CGSB | Central government social benefits paid |
| LASBHH | Local authority social benefits to households |
| CGSUBPR | Central government subsidies to private sector |
| OSPC | Public corporation operating surplus |
| NDIV | Non-financial corporate sector dividends |
| NNSGTP | Non-North-Sea gross trading profits |

Look in ONS Blue Book tables 5.2.4S (sector income/expenditure accounts) and 9.4 (GFCF by sector). These may also be in the quarterly sector accounts release.

For government earnings (ERCG, ERLA), check the ONS Annual Survey of Hours and Earnings (ASHE), public sector tables.

**~14 variables.**

---

## Job 7: Financial Accounts and Debt Components

**This is the lowest priority.** Only needed for detailed debt stock reconciliation.

### Where to get it

- ONS Financial Accounts (Blue Book chapter 6 / dataset UKEA)
- Debt Management Office (DMO) quarterly reports
- Bank of England Statistical Interactive Database

### Variables

| Model name | What it is | Source |
|------------|-----------|--------|
| CGGILTS | Outstanding gilt stock | DMO |
| NATSAV | National Savings stock | NS&I annual report |
| ILGAC | Index-linked gilt inflation accrual | DMO |
| CONACC | Conventional gilt accruals | DMO |
| OFLPS | Other financial liabilities of public sector | ONS |
| PSFA | Public sector financial assets | ONS |
| MKTIG | Marketable instruments outstanding | DMO |
| M4OFC | M4 held by other financial corporations | BoE |
| STUDENT | Student loan stock outstanding | Student Loans Company |

**~9 variables.** Before sourcing from primary providers, check `data/Aggregates_Detailed_forecast_tables_March_2025.xlsx` — the OBR Aggregates workbook has public sector debt components in Table 6.16 and adjacent sheets.

---

## Programmatic Data Access (APIs)

About 60% of the variables can be fetched via API rather than manual Excel downloads. This section documents what's available, how to access it, and which jobs benefit.

### Setup

You need three Python packages beyond what's already installed (`requests`, `pandas`, `openpyxl` are present). Install with:

```
pip3 install --break-system-packages fredapi sdmx1 wbgapi
```

The `--break-system-packages` flag is required on macOS because Homebrew Python enforces PEP 668 (externally-managed environment). This is safe for user-installed packages.

- `fredapi` — FRED (St. Louis Fed) client. Requires a free API key from https://fred.stlouisfed.org/docs/api/api_key.html
- `sdmx1` — IMF, Eurostat, and other SDMX sources
- `wbgapi` — Official World Bank client

For ONS, NOMIS, and Bank of England, use `requests` directly — the dedicated Python clients (`onspy`, `bank-of-england`) are immature. Raw HTTP with the documented endpoints is more reliable.

### API-by-API Reference

#### ONS Beta API (no auth required)

The primary source for national accounts, trade, prices, and labour market data. The old v0 API (`api.ons.gov.uk`) was retired November 2024. Use the beta API only.

```
Base URL: https://api.beta.ons.gov.uk/v1
```

**Fetching a series by CDID code** (e.g., ABMI for GDP):

```python
import requests

# Step 1: Find the data URI via search
r = requests.get("https://api.beta.ons.gov.uk/v1/search",
                  params={"content_type": "timeseries", "cdids": "ABMI"})
uri = r.json()["items"][0]["uri"]

# Step 2: Fetch the full time series
data = requests.get(f"https://api.beta.ons.gov.uk/v1/data?uri={uri}").json()
# data["quarters"] or data["months"] contains the observations
```

The CDID codes for model variables (ABMI, ABJR, etc.) are in `docs/OBR_Model_Variables_March_2025.xlsx`. Look up the ONS code column.

**Gotchas**: The API is dataset-oriented, not series-oriented — you need the search step to discover which dataset a CDID belongs to. Rate-limited; don't hammer it.

#### NOMIS API (optional free key for higher rate limits)

Best source for Labour Force Survey data, population estimates, and public sector employment.

```
Base URL: https://www.nomisweb.co.uk/api/v01/
```

**Example — population estimates by age:**

```python
# UK total population, annual, all ages
url = ("https://www.nomisweb.co.uk/api/v01/dataset/NM_162_1.data.csv"
       "?geography=2092957699"  # UK
       "&date=latestMINUS25-latest"
       "&age=0&measures=20100")
df = pd.read_csv(url)
```

Key dataset IDs:
- `NM_162_1` — Mid-year population estimates (for POP16, POPAL, GAD1-3)
- `NM_17_5` — Annual Population Survey / LFS (for ETLFS, ESLFS)
- `NM_30_1` — ASHE earnings (for ERCG, ERLA)

Register at https://www.nomisweb.co.uk/myaccount/userjoin.asp for higher rate limits. Geography codes are non-obvious — query the `.def.sdmx.json` sub-endpoint to discover valid codes.

#### Bank of England IADB (no auth required)

Construct a URL with series codes and get CSV back. No JSON endpoint.

```python
import io

series = "IUMABEDR"  # Bank Rate
url = (f"https://www.bankofengland.co.uk/boeapps/database/"
       f"_iadb-fromshowcolumns.asp?csv.x=yes"
       f"&Datefrom=01/Jan/2000&Dateto=01/Mar/2026"
       f"&SeriesCodes={series}&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
df = pd.read_csv(io.BytesIO(requests.get(url).content))
```

Useful series codes:
- `IUMABEDR` — Official Bank Rate
- `XUDLGBD` — GBP/USD spot rate
- `LPMAUZI` — M4 money supply
- `LPMVWYR` — M4 lending to OFCs (check exact code for M4OFC)

Up to 300 series codes per request, comma-separated. Date format must be `dd/Mon/yyyy`.

#### FRED API (free key required)

Mirrors BoE and OECD UK series. Useful for world data we can't get from ONS.

```python
from fredapi import Fred
fred = Fred(api_key='YOUR_KEY')

bank_rate = fred.get_series('BOERUKM')       # Bank Rate (monthly)
fx_rate = fred.get_series('DEXUSUK')          # USD/GBP (daily)
uk_gdp = fred.get_series('CLVMNACSCAB1GQUK') # UK real GDP (quarterly)
```

Register for a free key at https://fred.stlouisfed.org/docs/api/api_key.html. Rate limit: 120 requests/minute.

#### IMF (no auth required)

For world GDP and trade data (MAJGDP, WPG variables).

```python
import sdmx

imf = sdmx.Client('IMF')

# UK quarterly real GDP from International Financial Statistics
data = imf.data('IFS', key='Q.GB.NGDP_R_XDC')
df = sdmx.to_pandas(data)

# World Economic Outlook forecasts
data = imf.data('WEO', key='..NGDPD')  # All countries, nominal GDP
```

Key databases: `IFS` (International Financial Statistics), `WEO` (World Economic Outlook), `DOT` (Direction of Trade).

#### World Bank (no auth required)

```python
import wbgapi as wb

# UK GDP growth
df = wb.data.DataFrame('NY.GDP.MKTP.KD.ZG', economy='GBR', time=range(2000, 2025))

# World population (useful for MAJGDP trade weights)
df = wb.data.DataFrame('SP.POP.TOTL', economy='WLD')
```

#### HMRC (no API)

Tax receipts are published as Excel workbooks only. The publication page URL is stable but the download link changes monthly:

```
https://www.gov.uk/government/statistics/hmrc-tax-and-nics-receipts-for-the-uk
```

Approach: download the Excel manually (or scrape the publication page for the latest .xlsx link), then parse with `pandas.read_excel()`.

#### OBR (no API)

All OBR data is Excel downloads from their website. We already have the relevant workbooks in `data/`.

### Which jobs can use APIs

| Job | API source | Variables covered |
|-----|-----------|------------------|
| 1. HMRC receipts | **None** — Excel download | 0 of 21 |
| 2. Trade prices | ONS Beta API (CDID codes) | ~7 of 7 |
| 3a. Population | NOMIS (NM_162_1) | ~5 of 5 |
| 3b. LFS employment | NOMIS (NM_17_5) | ~3 of 3 |
| 3c. Public sector employment | ONS Beta or NOMIS | ~3 of 3 |
| 4. OBR supplements | **None** — Excel in data/ | 0 of 8 |
| 5. Tax parameters | **None** — desk research | 0 of 9 |
| 6. Sector accounts | ONS Beta API (CDID codes) | ~12 of 14 |
| 7. BoE monetary | BoE IADB | ~2 of 2 |
| 7. DMO debt | **None** — PDF/Excel | 0 of 7 |
| 7. ONS financial | ONS Beta API | ~2 of 2 |
| World data (MAJGDP, WPG, WEQPR) | IMF / FRED / World Bank | ~3 of 3 |
| **Total API-accessible** | | **~37 of ~100** |

The remaining ~63 variables come from Excel downloads (HMRC, OBR, DMO) or desk research (tax parameters). Job 1 (HMRC, 21 variables, highest priority) has no API — that one is always a manual download + parse.

---

## Summary and Suggested Sequence

| Job | What | Variables | New downloads needed? |
|-----|------|----------|----------------------|
| **1. HMRC receipts** | Quarterly tax receipts by tax head | ~21 | Yes — one HMRC Excel |
| **5. Tax parameters** | Statutory tax rates by quarter | ~9 | No — desk research from HMRC website |
| **3. Population/labour** | Population by age, public sector employment | ~10 | Yes — ONS Excel + NOMIS |
| **4. OBR supplements** | Trend GDP, trade decomposition, world assumptions | ~8 | Check existing files first |
| **2. Trade prices** | Import/export deflators by commodity type | ~7 | Yes — ONS trade tables |
| **6. Sector accounts** | Government expenditure detail by sub-sector | ~14 | Yes — ONS sector accounts |
| **7. Financial accounts** | Debt stock components | ~9 | Yes — DMO, BoE, ONS |

Start with **Job 1** (HMRC receipts) — it's one download, straightforward processing, and has the highest impact on the model.

Then **Job 5** (tax parameters) — no downloads, just a few hours reading HMRC rates pages and building a lookup table.

Then work through Jobs 3, 4, 2, 6, 7 in order.

---

## Questions? Ask about...

- **"What does variable X mean?"** — Check `docs/OBR_Model_Variables_March_2025.xlsx`, which has definitions for all 636 model variables.
- **"Which ONS series code?"** — The exact ONS 4-letter codes (e.g., ABJR, ABMI) are in the OBR's variable list. Cross-reference there.
- **"The HMRC workbook layout changed"** — This happens. Match by tax concept (e.g., "Value Added Tax"), not by column/row position.
- **"I can't find a quarterly version"** — Some series are only published annually. Note this and move on. We can interpolate if needed.
- **"How far back should the data go?"** — As far as the source provides, ideally from 1997Q1. The model's historical estimation window starts in the late 1980s, but 1997+ is sufficient for our purposes.
