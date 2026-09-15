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

## 3b. Public site (`vercel_site/`)
A self-contained static site, deploy-ready for Vercel. `python/build_site_data.py` queries the
DuckDB and writes every figure, chart series, axis tick and prose number into
`vercel_site/data/site.json`; `vercel_site/index.html` holds no numbers and does no arithmetic — it
renders what the build produced. Sections follow the August 2026 visualisations
review: survival curves by birth cohort, an age-specific hazard rate (invariant
to how long a firm has existed), young-firm failure by the year it happened,
entry rate as a ratio alongside the absolute count, index entrant share, the
granular exit mix, recession shading on every time series, Tobin's Q framing for
the valuation gap, and three choropleths (UK local authorities, England & Wales
MSOAs, value added by area). Rebuild after any database change with
`python python/build_site_data.py --verify` (the `--verify` flag is a wiring gate: it fails if the
page references a figure the build did not produce, if a figure goes unused, if a canvas has no
chart spec, or if any number has been hardcoded into the prose). Deploy notes: `vercel_site/README.md`.

## 4. Scripts (`python/`, `sql/`)
`sql/01..12` build the derived spine on local Postgres. `python/` has the current tooling:
`build_duckdb.py` (assemble the DB), `build_consolidated_csvs.py`, `sec_shares_provenance.py`,
`build_entrant_analysis.py` + `build_entrant_chart.py` + `merge_adjudication.py`,
`build_site_data.py` (the public site's back end: DuckDB → `vercel_site/data/*.json`),
`fetch_ons_geography.py` (caches the ONS postcode directory + boundaries the maps need),
`ch_api_extract.py` (CH dead-firm birth/death extractor), `ch_pdf_reader.py`/`ch_pdf_ocr_extract.py`
(CH scanned-accounts OCR), `fmp_fetch.py`, `04_export_parquet.py`. `sync_and_rebuild.sh` pulls
Neon→local and rebuilds; `deploy_ch_server.sh` deploys the CH extractor to a cloud VM.

### 4a. Identity: join on CIK / company number, never ticker

Tickers are reused once a company delists, so a ticker join attaches one
company's data to another's. This is not theoretical here: `sp500_companies_full`
held the wrong company for seven symbols (Compuware/Ocean Thermal,
Anadarko/ARKO, El Paso/Empire Petroleum, ...), and in the FTSE composition record
`RSA` maps to three different companies and `GAA` to three. CIK was also stored in
four different types across five tables (`'0000875570'`, `875570`, `875570.0`), so
CIK joins matched nothing and everything silently fell back to the ticker.

Three scripts fix and maintain this; run them in this order after any
`build_duckdb.py neon`, which re-imports the raw tables and drops the repairs:

```bash
python python/build_identity_crosswalk.py     # CIK -> VARCHAR(10) everywhere; builds sp500_identity
python python/sp500_edgar_sector_fetch.py     # EDGAR sector/SIC for delisted constituents
python python/apply_sector_enrichment.py      # lands it, joining on CIK
python python/build_ftse_sector_crosswalk.py  # FTSE sector file -> company_number
python python/build_consolidated_csvs.py
python python/build_entrant_analysis.py
python python/merge_adjudication.py
python python/build_site_data.py --verify
```

Rules that follow from this:

- **Join on `cik` (S&P) or `company_number` (FTSE).** A ticker may be used to
  *look up* an identifier via `sp500_identity`, never as the join key itself.
- **Read identifiers as strings.** `cik` and `company_number` are zero-padded;
  `pd.read_csv` turns `0000773910` into `773910` and the join then silently
  matches nothing. Pass `dtype={"cik": str, "company_number": str}`.
- **Collapse to one row per identifier before merging.** One company can hold
  several tickers (GOOG/GOOGL, FB/META, BSY/SKY), so an uncollapsed CIK merge
  multiplies rows instead of matching them.
- **Hand-resolved CIKs** live in `source_inputs/sp500_manual_cik_resolution.csv`,
  one row per company with the EDGAR record cited.

### 4b. Sector provenance

`sector` used to come only from the live constituent list, so it was present for
100% of current members and 27% of those that had left — survivorship bias in the
field the whole sector analysis rests on, worst for the dot-com cohort. It is now
backfilled from each company's SEC SIC code via `python/sic_gics_map.py`, taking
coverage to 1,048 of 1,049 symbols.

Every row records where its sector came from in `sector_basis`:
`index_list_gics` (authoritative, never overwritten), or `company_override` /
`sic4` / `sic3` / `sic2` from the mapping. Validated against the 503 symbols
holding both a real GICS sector and a SIC, the mapping agrees 86.7% of the time;
SIC cannot separate Visa from Accenture, so the residual is irreducible and the
`sector_basis` column is what lets a reader weight it.

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
- `vercel_site/` — the deploy-ready public site (static; every figure computed at build time).
- `docs/` — specs and task briefs.
- `source_inputs/` — raw inputs, uploaded agent files, worklists.
- `python/`, `sql/` — code; `deploy_ch_server.sh`, `sync_and_rebuild.sh` — runners.
