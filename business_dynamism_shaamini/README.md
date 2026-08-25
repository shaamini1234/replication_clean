# combined_dataset — the active workspace & combined database

This folder holds the current combined database, the publish-ready deliverables, the analysis, and
the scripts that build them. It supersedes the older per-dataset folders. This README replaces the
former `DATABASE_ARCHITECTURE.md`, `PLAN.md`, `ROADMAP.md`, `HANDOVER.md`, and `entrant_methodology.md`
(their content is folded in below).

## 1. The database (single source of truth)

**`business_dynamism_v2_20260820.duckdb`** — one file, both readable and writable, holds every
table. `business_dynamism_v2_20260820.duckdb.zst` is a compressed backup (~2.8 GB) for Drive.

Tables: `firm_master` (7.88M — the UK spine: birth, death, financials, provenance),
`combined_firm_year` (39.36M), `firm_year_panel` (39.08M), `exit_events` (583k), `companies`
(CH register), `gazette_events` (insolvency notices), `ch_company_profile` (dead-firm birth/death
from the CH API), `ftse100_*`, `sp500_*`, plus the enriched analysis tables `ftse100_consolidated`,
`sp500_consolidated`, `sp500_sec_supplement`.

**Data homes.** Local Postgres `business_dynamism` is canonical for the huge `financial_filings`
(~39.5M rows, too big for free Neon). Neon Postgres is cloud staging + writable target for crawlers.
The DuckDB file is the portable, Claude-accessible mirror. UK tables join on **Companies House number**
(canonical 8-char); S&P sits on **CIK/ticker** (separate key space — for comparison, not join).

## 2. Deliverables (publish-ready CSVs)
- `FTSE100_consolidated.csv` / `SP500_consolidated.csv` — one row per company-year: market data +
  fundamentals + spine + source URLs.
- `FTSE_company_founding.csv` / `sp500_company_founding.csv` — every constituent's founding date
  (exact where possible, else month/year), with source URLs and precision flags.
- `ftse_entrants_classified.csv` / `sp500_entrants_classified.csv` — every index entrant classified
  genuinely-new vs corporate-action (spin-off/merger/reincorporation/etc.), source-adjudicated.
- `entrant_final_summary.csv`, `entrant_trend_summary.csv`, `adjudication_results.csv`,
  `adjudication_by_ticker.csv` — the entrant analysis + its sourced calls.
- Supporting: `sec_supplement.csv`, `sp500_founded_fill*.csv`, `FTSE_founded_research.csv`.

## 3. Reports (HTML)
`business_dynamism_report.html` (manager-facing), `analysis.html`, `database_explorer.html`,
`findings.html`, `database_overview.html`, `entrant_analysis.html`.

## 4. Scripts (`python/`, `sql/`)
`sql/01..12` build the derived spine on local Postgres. `python/` has the current tooling:
`build_duckdb.py` (assemble the DB), `build_consolidated_csvs.py`, `sec_shares_provenance.py`,
`build_entrant_analysis.py` + `build_entrant_chart.py` + `merge_adjudication.py`,
`ch_api_extract.py` (CH dead-firm birth/death extractor), `ch_pdf_reader.py`/`ch_pdf_ocr_extract.py`
(CH scanned-accounts OCR), `fmp_fetch.py`, `04_export_parquet.py`. `sync_and_rebuild.sh` pulls
Neon→local and rebuilds; `deploy_ch_server.sh` deploys the CH extractor to a cloud VM.

## 5. Active task briefs (handed to other agents — kept as standalone files)
- `SP500_MARKETDATA_HANDOFF.md` + `SP500_marketdata_worklist.csv` — fill S&P market cap / shares /
  employees (15.6k symbol-years) from SEC, with URLs.
- `FTSE_MARKETDATA_HANDOFF.md` + `FTSE_marketdata_worklist.csv` — fill FTSE 2001–2015 market data
  (441 company-years) from annual reports, with URLs.
- `LSEG_PULL_SPEC.md` + `LSEG_pull_universe.csv` — spec for pulling FTSE fundamentals 2000+ from LSEG.
- `OCR_HANDOFF.md` — spec for OCR'ing CH scanned FTSE accounts (`ch_pdfs/`).

## 6. Status / what's in flight
- **CH API extraction** (`ch_company_profile`, dead-firm birth+dissolution dates): running on a GCP
  VM under systemd (`deploy_ch_server.sh`), 7 keys, ~7 rows/s, ~354k+ done of 3.4M remaining
  (~5–6 days). Resumable; lands in Neon.
- **Coverage reality:** FTSE market data ~55% overall (near-complete 2018+, thin pre-2001);
  FTSE fundamentals only 2021+ (CH holds only scanned PDFs for big firms; NSM has no API; LSEG/FMP
  Premium are the paid routes to 2000). S&P financials 90%+ back to 2000, near-complete 2009+;
  market cap/shares 0% pre-2009; employees ~1% (the market-data briefs above address these).

## 7. Founding-date / entrant method (folded from entrant_methodology.md)
"Genuinely new at index entry" = business founded ≤~12y before entry, entering on its own (not a
spin-off/merger/demutualisation/reincorporation) and not a re-entry. Age = entry − founding, using
CH incorporation (UK) or researched business founding (not holdco reincorporation). Every
young-at-entry case is source-adjudicated with a URL. Headline: genuinely-new firms are a small
minority of entrants (verified: 7 FTSE, 31 S&P) — most "new" members are repackaged established firms.

## 8. Coverage boundaries to state in any publication
CH financials 2008+ only; Gazette 1998+; insolvency ≠ all exits (voluntary strike-offs are a
separate, larger route via CH dissolution); CH `companies` snapshot is survivor-biased; S&P is a
separate US key space. Pre-XBRL (pre-2009) US and pre-2001 UK market data are structural gaps.

## Folder layout
- `database/` — the canonical DuckDB + its `.zst` backup (NOTE: still in the old `business_shaamini/combined_dataset/` until tonight's bulk fetch finishes — see docs/CLEANUP_INSTRUCTIONS.md).
- `deliverables/` — final outputs: `ftse_sources.xlsx`, `sp500_sources.xlsx`, per-parameter CSVs in `ftse/` and `sp500/`, finished analysis in `consolidated/`.
- `reports/` — HTML views; open in a browser.
- `docs/` — specs and task briefs.
- `source_inputs/` — raw inputs, uploaded agent files, worklists.
- `python/`, `sql/` — code; `deploy_ch_server.sh`, `sync_and_rebuild.sh` — runners.
