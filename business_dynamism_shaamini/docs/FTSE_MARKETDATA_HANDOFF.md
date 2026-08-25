# FTSE market-data backfill 2001–2015 — task brief

## Goal
Fill the missing FTSE 100 market data for **2001–2015** — for each constituent-year:
**year-end share price (pence), shares outstanding, market cap (£), dividend per share (pence)** —
each value carrying a **source URL**. Accuracy over completeness. Never fabricate.

## The worklist
`FTSE_marketdata_worklist.csv` (in this folder) — **441 constituent-years, 83 companies**.
Columns: `company_number, composition_name, ticker, year, need_price, need_shares,
need_marketcap, need_dividend` (the `need_*` flags show which values are missing).
Only 33 have a modern ticker; the rest are dead/former constituents, so most work is
per-company annual-report research, not a price feed.

## What each value means (get the YEAR-END figure)
- **year_end_price_pence** — closing share price on the last trading day of the calendar year.
- **shares_outstanding** — ordinary shares in issue at year-end (from the annual report balance
  sheet / capital note, or a year-end filing).
- **market_cap_gbp** — year_end_price × shares_outstanding (compute it; £). If you find a stated
  market cap, use it and note the source.
- **annual_dividend_pence** — total ordinary dividend per share declared for that financial year.

## Where to find it (each value needs a real source URL)
- **Annual reports** — the company's own annual report (investor-relations site, annualreports.com,
  or Companies House filing) gives shares outstanding + dividend per share, exact.
- **Historical prices** — LSE historical data, stooq.com (`https://stooq.com/q/d/l/?s=<ticker>.uk&i=d`),
  Wall Street Journal / investing.com historical, or the annual report's "share price range" table.
- **Dead/renamed firms** — trace the entity as it was in that year (watch ticker reuse and
  reincorporations); use the annual report of the company that was actually in the index then.

## HARD RULES (this project's standard)
1. **Never invent a number.** If a value can't be found from a real source, leave it blank.
2. **Source URL on every value** — the exact page the figure came from.
3. **Currency = GBP**, price in **pence**, dividend in **pence per share**. Convert if a source
   reports in £ or another currency, and note it.
4. **Flag estimates** — if a figure is approximate (e.g. mid-year proxy), mark it and say why.
5. Watch **ticker reuse / reincorporations** — make sure the figure is for the entity that was in
   the FTSE 100 that year, not a modern namesake.

## Output format
Save `FTSE_marketdata_filled.csv` in this folder with columns exactly:
```
company_number,year,year_end_price_pence,price_source_url,shares_outstanding,shares_source_url,market_cap_gbp,marketcap_source_url,annual_dividend_pence,dividend_source_url,notes
```
One row per company-year from the worklist. Leave a cell blank (not zero) where not found.

## Merging back (whoever integrates it)
Join `FTSE_marketdata_filled.csv` to `ftse100_compositions` on `(company_number, year)` and
fill-where-null. The database lives both in Neon (`ftse100_compositions`, writable) and the local
`business_dynamism_v2_20260820.duckdb`. Keep the source URLs — they are the provenance.

## Scope reality
441 company-years × up to 4 values with sourced URLs is a large manual research job. Prioritise:
(1) companies/years with the most missing fields, (2) larger/longer-tenure constituents first.
Partial, accurate, sourced progress is the goal — not fabricated completeness.
