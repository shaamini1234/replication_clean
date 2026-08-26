# UK Business Dynamism Database
## Project handover

### 1. Where the project stands

The database links the birth, life and death of British companies at whole-population scale, and overlays the FTSE 100 and S&P 500 as tracked indices. It is a single DuckDB file (21 tables, ~39M firm-year rows) plus fully-sourced CSVs and two Excel workbooks. Every value either carries a source URL (or a document citation where the source is licensed) or is left blank. Sourced is not validated: a few filed-accounts and market-cap values are implausible and are filtered at the point of use (section 5).

The whole-population Companies House and Gazette layers are complete. S&P 500 financials are strong (revenue, profit and assets 90–95% from 2000). FTSE 100 membership and recent market data are complete, with a pre-2022 fundamentals gap that needs a licensed source.

The universe is 7,877,348 companies (`firm_master`): 4.12M with registry incorporation dates, 3.76M with birth years estimated from the sequential company number, and all but 112 present in the filings panel. One background job is completing this — see section 7.

### 2. The folder

| Folder | What's in it |
| --- | --- |
| `database/` | The canonical DuckDB file (21 tables). The `.zst` backup is an earlier build — section 5. |
| `deliverables/` | The ready-to-use outputs — start here. |
| `source_inputs/` | Raw and handover CSVs, plus `ftse100_sector_classification.csv`. |
| `python/` | Build and fetch scripts. |
| `sql/` | Postgres build steps 01–12, run in order before the DuckDB assembly. |
| `docs/` | Task briefs and method notes, including the LSEG spec. |
| `reports/` | Standalone HTML reports. |
| `vercel_site/` | The public site; every figure computed from the database by `build_site_data.py`. |

**The deliverables**, in order of preference: two Excel workbooks (`ftse_sources.xlsx`, `sp500_sources.xlsx`) with one tab per parameter, each value paired with its `source_url`, plus Spine and Founding tabs; per-parameter CSVs in `deliverables/ftse/` and `deliverables/sp500/`; and wide consolidated CSVs in `deliverables/consolidated/` alongside the founding-date and entrant-classification files.

S&P entry/exit and financials carry per-company URLs (SEC EDGAR, the Wurgler S&P-changes dataset, SPGlobal). FTSE entry/exit carry a citation rather than a URL, the LSEG source being licensed with no public link.

### 3. The database

One file, no server or login:

```python
import duckdb
c = duckdb.connect('database/business_dynamism_v2_20260824d.duckdb', read_only=True)
c.execute('show tables').fetchall()
```

| Group | Key tables (rows) | What it is |
| --- | --- | --- |
| Whole-population | `firm_master` (7.9M), `companies` (5.7M), `combined_firm_year` (39.4M), `firm_year_panel` (39.1M) | Every UK company: identity, birth year, SIC, status, and the year-by-year panel from filings. |
| Exit / death | `exit_events` (583k), `gazette_events` (1.0M) | Insolvency, from London Gazette notices. |
| FTSE 100 | `ftse100_membership`, `ftse100_compositions`, `ftse100_consolidated`, `ftse100_fundamentals`, `ftse_birth_audited` | Membership spells, per-year market data, fundamentals (2021+), audited founding dates. Sectors sit outside the database, in `source_inputs/ftse100_sector_classification.csv`. |
| S&P 500 | `sp500_financials` (15.9k), `sp500_consolidated`, `sp500_founding`, `sp500_membership`, `sp500_sec_supplement` | Symbol-year financials, membership, founding dates. |

`company_number` is the key on the UK side, `symbol`/`cik` on the S&P side. `combined_firm_year` is the main analytical table (one row per company per fiscal year); `_build_info` records build provenance.

### 4. Coverage

#### S&P 500 — 15,857 symbol-years, 1,049 companies, 2000–2026

| Parameter | Coverage | Note |
| --- | --- | --- |
| Net income | 95% (15,061) | SEC EDGAR XBRL |
| Total assets | 94% (14,840) | SEC EDGAR XBRL |
| Revenue | 90% (14,232) | SEC EDGAR XBRL |
| Shares outstanding | 63% (10,048) | XBRL from 2009; pre-2009 backfilled |
| Market cap | 59% (9,343) | year-end price × shares; thinner pre-2009 |
| Employees | 1% (236) | not a standard XBRL fact — open gap |

![S&P 500 parameter coverage by fiscal year](docs/handover/sp500_coverage.png)

Market cap and shares step up in 2009 because the SEC's XBRL mandate phased in then; earlier filings carry no machine-readable share count. Pre-2009 market caps were attempted from price feeds (stooq and Yahoo raw endpoints, then yfinance) but stooq and Yahoo rate-limit (HTTP 429) and yfinance returns nothing for constituents since delisted or acquired.

The chart stops at 2024, the last settled year for every parameter. Filed figures for 2025 are near-complete (675 symbol-years; net income 99%) but market cap is not yet computed for that year (5%), so plotting 2025 would show a collapse that is an artefact of the pipeline. 2026 is a part-year at 64 rows.

#### FTSE 100 — 4,200 constituent-years, 1983–2024

| Parameter | Coverage (from 2000) | Note |
| --- | --- | --- |
| Dividend / share | 71% (1,957) | near-complete from 2010; back-research earlier |
| Share price (year-end) | 71% (1,957) | as above |
| Shares outstanding | 70% (1,937) | as above |
| Market cap | 70% (1,938) | as above |
| Revenue / profit / assets | 2022–2026 only | free sources reach 2021; pre-2021 needs LSEG |

![FTSE 100 parameter coverage by year](docs/handover/ftse100_coverage.png)

The four market-data series track closely and thin going back. Fundamentals — revenue, net income, total assets — exist from 2021 in `ftse100_fundamentals` and 2022 in the consolidated table the deliverables are built from: the free feed carries only recent years, older statutory accounts sit at Companies House as scanned image PDFs, and no free API reaches 2000. Independently reported year-end market caps for BT and BG have been folded in, lifting pre-2008 coverage by about two points.

#### Companies House & Gazette — whole population

![New companies and insolvencies per year](docs/handover/population_pulse.png)

*New-firm formations per year (left) and insolvency notices per year (right).*

7.88M companies, ~100% with a birth year and 583,548 (7.4%) with an observed exit. `combined_firm_year` holds 39.4M firm-year rows. The Gazette layer holds 1,015,738 notices (1998–2026); exits split 431,104 insolvent / 152,329 solvent.

The extract covers **insolvency procedures only** — creditors' and members' voluntary winding-up, petitions, winding-up orders, administration, receivership, and register restorations. It contains no strike-off notices, and strike-off is the larger route out of the register, so the notices are a subset of dissolution rather than a census and cannot reconstruct which companies were active in a past year. That is the purpose of the extraction in section 7.

### 5. Data limits

- **FTSE fundamentals before 2021 do not exist for free.** The single biggest gap; closing it needs LSEG Datastream, a paid seat — see `docs/LSEG_PULL_SPEC.md`.
- **S&P market cap and shares thin out before 2009**, where SEC XBRL begins.
- **S&P employee counts are almost entirely missing (1%).**
- **A few values are implausible and are filtered at the point of use.** Two firm-years in `combined_firm_year` carry staff costs and operating profit in the hundreds of billions against a largest legitimate value of about £2bn; several 2023–24 S&P market caps rest on share counts that are not split-adjusted (NVDA reads $15tn). Both should be corrected at source.
- **Founding dates are business-founding, not holding-company dates.** Later holdco or reincorporation dates are parked in `legal_entity_founded_year` and never used; unresolved cases are left blank, so an old firm is never made to look new.
- **Founding-date basis differs by index.** FTSE dates come from Companies House, whose incorporation date resets on reincorporation, so it understates age; S&P dates are true business-founding years. FTSE entrant ages are corrected to audited operating-birth dates for 275 of 327 entrants (median age at entry rises from 15 to 38, against the S&P's 35); the remaining ~50 fall back to incorporation dates. Cross-index age comparisons should use the corrected figure.
- **The FTSE sector classification was rebuilt.** The original existed only as a DuckDB table and was lost with that file, and is in neither the `.zst` backup nor Neon. `source_inputs/ftse100_sector_classification.csv` reconstructs it on the same GICS-style basis, reproducing the published sector shares to within a percentage point, and is committed.
- **The `.zst` backup is an earlier build**, holding 263,600 Companies House profiles against 450,900 now in Neon and lacking the sector table. Re-cut it after the next refresh.
- **The Neon credential is shared and cannot be rotated.** It now lives in `.env` at the repo root (gitignored, see `.env.example`) rather than in ten source files, but it remains in git history. A fresh clone needs `.env` created before any Neon script will run.

### 6. Routes taken and abandoned

Both indices sit on the whole-population foundation: Companies House bulk register and filings history → `firm_master` and `combined_firm_year`; London Gazette notices → `exit_events`.

**FTSE 100.** Taken: LSEG "Historic Additions & Deletions" plus prior CBP research for the membership spine; yfinance for recent market data and 2021+ fundamentals; annual reports and manual back-research for older market data. Abandoned: OCR of Companies House scanned accounts (200–400pp image scans, unreliable extraction), replaced by the CH API route; free sources for pre-2021 fundamentals (none exist at index scale).

**S&P 500.** Taken: SEC EDGAR company-facts (XBRL) for financials and shares; yfinance month-end prices × shares for market cap; the Wurgler dataset plus SEC and SPGlobal for the membership spine. Abandoned: stooq and Yahoo raw price endpoints (rate-limited), replaced by yfinance; per-company agent scraping (too slow), replaced by bulk fetches.

### 7. In progress

**Companies House company profiles.** A background job (`ch-extract`, a Google Cloud VM in us-central1-a, using the Companies House API across several keys at ~7 records/second) pulls incorporation date, dissolution date, status and SIC for every company in a ~3.3M queue. Phase 1, ~93% done, covers the 481,661 firms that already have a dated Gazette exit and yields exact dates for firms whose fate was known. Phase 2 covers the remaining ~3.3M, the firms of unknown fate.

**This is load-bearing, not additive.** Phase 2 determines whether the active-company population can be measured in any past year, and with it the entry rate, the age structure, and any reading of the survival curves not confounded by missing deaths. At ~7 records/second it is roughly five and a half days of continuous running, and it stalls silently, requiring a manual `systemctl restart chextract`; a durable fix (`Restart=always`, plus a statement timeout and keepalives on the Neon connection) should be applied before relying on it unattended.

### 8. Next steps

- **Merge the CH profiles** when the job finishes, then refresh the workbooks and re-push. Note that `add_spine_sources.py`, `commit_marketdata_fast.py` and `fold_ch_and_rebuild.py` are named in the refresh routine but absent from `python/`, and `GUIDE.md`, which documented the sequence, has been deleted; both need recovering first.
- **Extend the entrant analysis.** S&P establishment dates are a recent addition and want checking. The ~50 FTSE entrants still on Companies House incorporation dates need auditing so both indices sit on one business-founding basis; then age-at-entry and the genuinely-new-firm figures can be finalised from the classified entrant and adjudication files in `deliverables/consolidated/`.
- **Close the FTSE pre-2021 fundamentals gap.** LSEG is expensive; watch for alternatives.
- **Fill S&P employee counts** from 10-K cover pages or a headcount source (`docs/SP500_MARKETDATA_HANDOFF.md`).
- **Fix the implausible values at source** so the filters are no longer needed.

**Refresh routine:** commit staged CSVs to Neon (`commit_marketdata_fast.py`) → fold into DuckDB (`build_duckdb.py neon`) → rebuild workbooks (`build_source_workbooks.py`, then `add_spine_sources.py`) → rebuild the site (`build_site_data.py --verify`) → redraw these charts (`build_handover_charts.py`) → regenerate this document (`build_handover_doc.py`).
