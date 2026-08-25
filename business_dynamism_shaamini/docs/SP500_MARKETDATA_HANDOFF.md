# S&P 500 market-data / employees backfill — task brief

## Goal
Fill missing values in `sp500_financials` — **market cap, shares outstanding, employees**
(and any other clearly-useful missing field) — for each symbol-year, each with a **source URL**.
Absolute accuracy over completeness. Never fabricate.

## The worklist
`SP500_marketdata_worklist.csv` (this folder) — **15,647 symbol-years, 1,049 companies**.
Columns: `symbol, cik, fiscal_year, need_market_cap, need_shares, need_employees`.
Every row has a **CIK** — use SEC EDGAR to resolve the company and pull filings.
Gap sizes: employees ~15,621 (almost all), market cap ~6,514, shares ~4,695.

## What each value means (get the value AS OF that fiscal year)
- **shares_outstanding** — common shares outstanding at fiscal year-end (10-K cover page
  "shares outstanding", or balance-sheet / XBRL `dei:EntityCommonStockSharesOutstanding`).
- **market_cap** — share price at/near fiscal year-end × shares outstanding (USD). If a source
  states market cap directly, use it and cite it. Otherwise compute price × shares and cite both.
- **employees** — number of employees, from the 10-K (usually "Item 1. Business" / "Human
  Capital"), for that fiscal year.

## Where to find it (each value needs a real source URL)
- **SEC EDGAR** (primary, most reliable): the company's **10-K** for that fiscal year —
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=<cik>&type=10-K&dateb=&owner=include&count=40`
  → open the 10-K for the year → employees + shares outstanding are stated in it.
  XBRL facts: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
  (`dei:EntityCommonStockSharesOutstanding` for shares; note XBRL only reliably exists 2009+).
- **Historical price** (for market cap): stooq (`https://stooq.com/q/d/l/?s=<ticker>.us&i=d`),
  WSJ / investing.com historical, or macrotrends — take the year-end close.
- Pre-2009 employees/shares come from the **10-K text** (EDGAR has 10-Ks back to ~1994), not XBRL.

## HARD RULES (this project's standard)
1. **Never invent a number.** If a value isn't in a real source, leave it blank.
2. **Source URL on every value** — the exact EDGAR filing / page it came from.
3. **Units:** USD for market cap; shares and employees as integer counts. Note any unit oddities.
4. **Right entity, right year** — watch ticker reuse and reincorporations; use the filing of the
   registrant that had that CIK for that fiscal year.
5. **Flag estimates** — if market cap uses an approximate year-end price, say so in `notes`.

## Output format
Save `SP500_marketdata_filled.csv` in this folder, columns exactly:
```
symbol,cik,fiscal_year,market_cap,marketcap_source_url,shares_outstanding,shares_source_url,employees,employees_source_url,notes
```
One row per worklist symbol-year attempted. Blank (not zero) where not found.

## Priority order (it's a big list — do highest-value first)
1. **Employees** for current/large S&P constituents (most analytically useful, and 10-K text has it).
2. **Shares + market cap for 2000–2008** (currently 0% — the biggest structural gap).
3. Remaining market-cap gaps 2009+ (price × the shares we already hold).

## Merging back
Join `SP500_marketdata_filled.csv` to `sp500_financials` on `(symbol, fiscal_year)` (cik as
tiebreak) and fill-where-null, keeping the source URLs. DB is in Neon (`sp500_financials`,
writable) and local `business_dynamism_v2_20260820.duckdb`.

## Scope reality
~15.6k symbol-years × up to 3 sourced values is very large — a single pass won't finish it.
Split the worklist across several runs (by fiscal-year range or symbol range) and combine the
`SP500_marketdata_filled.csv` outputs. Accurate sourced partial progress is the goal.
