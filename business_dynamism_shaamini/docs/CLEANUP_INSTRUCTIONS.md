# Cleanup brief — tidy `business_shaamini/combined_dataset` into a self-contained, documented folder

You (the executing agent) have a working shell. Goal: **no stray files at the top level, every
subfolder has a README, irrelevant files moved to `_to_delete/`.** Move files (`mv`) — never delete
(the folder mount blocks deletion anyway; the user empties `_to_delete/` in Finder later).

## PRECONDITIONS — do NOT run until these are true
1. Tonight's `bulk_sp500_fetch_to_csv.py` has finished (it writes `sp500_shares_marketcap_bulk.csv`).
2. The morning Neon commit (`commit_uploaded_marketdata.py`) has run.
3. `build_source_workbooks.py` has been re-run so `ftse_sources.xlsx` / `sp500_sources.xlsx` are current.
Running mid-flight would move files the scripts expect in place and break them.

Work in: `/Users/shaaminiprinja/Documents/CBP/business_dynamism-master/business_shaamini/combined_dataset`

---

## TARGET STRUCTURE
```
combined_dataset/
  README.md                 (keep; update the index at the end)
  CLEANUP_INSTRUCTIONS.md    (this file; move to docs/ when done)
  python/                    (keep — code)
  sql/                       (keep — code)
  deploy_ch_server.sh        (keep — runner)
  sync_and_rebuild.sh        (keep — runner)
  database/                  (NEW)  the canonical DuckDB + its .zst backup
  deliverables/              (EXISTS) final outputs — see below
  reports/                   (NEW)  the HTML reports
  docs/                      (NEW)  handoff briefs + methodology
  source_inputs/             (NEW)  raw inputs, uploaded agent files, worklists
  _to_delete/                (EXISTS) cruft
```

---

## STEP 1 — create the subfolders
```
cd /Users/shaaminiprinja/Documents/CBP/business_dynamism-master/business_shaamini/combined_dataset
mkdir -p database reports docs source_inputs deliverables/consolidated _to_delete
```

## STEP 2 — MOVE (mv) each file to its home

### database/  (the canonical DB + backup)
```
mv business_dynamism_v2_*.duckdb database/ 2>/dev/null
mv business_dynamism_v2_*.duckdb.zst database/ 2>/dev/null
```
(If both a `.duckdb` and `.duckdb.zst` match, both move. Keep only the NEWEST `v2_*` — if older
`v2_*` dupes exist, move the older ones to `_to_delete/`.)

### reports/  (HTML)
```
mv findings.html database_overview.html database_explorer.html analysis.html business_dynamism_report.html entrant_analysis.html reports/ 2>/dev/null
```

### docs/  (briefs + this file)
```
mv LSEG_PULL_SPEC.md OCR_HANDOFF.md FTSE_MARKETDATA_HANDOFF.md SP500_MARKETDATA_HANDOFF.md CLEANUP_INSTRUCTIONS.md docs/ 2>/dev/null
```

### deliverables/consolidated/  (the finished analysis outputs)
```
mv ftse_sources.xlsx sp500_sources.xlsx deliverables/ 2>/dev/null
mv FTSE100_consolidated.csv SP500_consolidated.csv deliverables/consolidated/ 2>/dev/null
mv ftse_entrants_classified.csv sp500_entrants_classified.csv entrant_final_summary.csv entrant_trend_summary.csv adjudication_results.csv adjudication_by_ticker.csv deliverables/consolidated/ 2>/dev/null
mv ftse_birth_audited.csv FTSE_company_founding.csv sp500_company_founding.csv deliverables/consolidated/ 2>/dev/null
```
(`deliverables/ftse/` and `deliverables/sp500/` per-parameter CSVs already exist — leave them.)

### source_inputs/  (raw + uploaded + worklists + intermediate research)
```
mv "FTSE100_CANONICAL_DATABASE(20260818-161735).csv" "FTSE100_WORKLIST(20260818-161737).csv" "sp500_amended_database(9).csv" "sp500_membership_worklist(20260818-161214).csv" source_inputs/ 2>/dev/null
mv LSEG_pull_universe.csv sec_supplement.csv source_inputs/ 2>/dev/null
mv SP500_marketdata_filled_pre_bulk.csv FTSE_marketdata_handover_2026-08-24_completed_best_evidence.csv sp500_shares_marketcap_bulk.csv source_inputs/ 2>/dev/null
mv sp500_founded_fill.csv sp500_founded_fill2.csv FTSE_founded_research.csv sp500_founding_final.csv source_inputs/ 2>/dev/null
mv FTSE_marketdata_worklist.csv SP500_marketdata_worklist.csv FTSE_birth_review_worklist.csv source_inputs/ 2>/dev/null
```

### _to_delete/  (cruft, scratch, superseded, abandoned)
```
mv _ftse102_verified.csv _to_delete/ 2>/dev/null
mv FTSE_marketdata_filled.csv SP500_marketdata_filled.csv SP500_marketdata_review.csv _to_delete/ 2>/dev/null
mv ch_pdfs_financial_extraction.csv _to_delete/ 2>/dev/null
mv ch_pdfs _to_delete/ 2>/dev/null
mv output _to_delete/ 2>/dev/null
mv .venv source _to_delete/ 2>/dev/null
```
(`output/` held a superseded Parquet snapshot + OCR scratch; the DuckDB is the master. `.venv`/`source`
are leftover Python virtualenvs — the user uses `~/bd-venv`, so these are dead weight.)

---

## STEP 3 — FIX SCRIPT PATHS (important — the DB moved into `database/`)
Several scripts locate the DB with `glob(os.path.join(HERE,"business_dynamism_v2_*.duckdb"))` where
`HERE` = the `combined_dataset` root. After the move it's in `database/`. In each of these files,
change that glob to look in `database/`:
- `python/build_source_workbooks.py`
- `python/build_parameter_csvs.py`
- `python/bulk_sp500_fetch_to_csv.py`
- `python/build_duckdb.py` (writes there — point its output/read to `database/`)

Edit: replace `os.path.join(HERE,"business_dynamism_v2_*.duckdb")` →
`os.path.join(HERE,"database","business_dynamism_v2_*.duckdb")` (and the same for any `.duckdb` write).
Also `commit_uploaded_marketdata.py` / `build_source_workbooks.py` read the uploaded CSVs from `HERE`;
point those globs at `source_inputs/`. Then smoke-test:
`python3 python/build_parameter_csvs.py` should still run without a "DB not found" error.

(If you'd rather not touch the scripts, INSTEAD leave the `.duckdb`, the uploaded CSVs, and the
worklists at the top level and skip STEP 3 — the folder is still tidy, just with the DB + a few
active inputs visible at root. State clearly which choice you made.)

---

## STEP 4 — write a README.md in every new subfolder (verbatim content below)

`database/README.md`:
```
# database — the canonical combined database
business_dynamism_v2_<date>.duckdb : single-file DuckDB, every table, readable with no cloud.
.duckdb.zst : compressed backup. Rebuild the .zst locally with:  zstd business_dynamism_v2_<date>.duckdb
This is the source of truth. Neon is only cloud staging; local Postgres holds the raw financial_filings.
```

`reports/README.md`:
```
# reports — HTML views
business_dynamism_report.html : manager-facing overview.
entrant_analysis.html : "are new index members genuinely new?" chart.
analysis.html / database_explorer.html / findings.html / database_overview.html : exploratory views.
Open in a browser; no server needed.
```

`docs/README.md`:
```
# docs — specs & task briefs
LSEG_PULL_SPEC.md : how to pull FTSE fundamentals 2000+ from LSEG (the paid gap).
OCR_HANDOFF.md : CH scanned-accounts OCR spec (abandoned route, kept for record).
FTSE_MARKETDATA_HANDOFF.md / SP500_MARKETDATA_HANDOFF.md : market-data backfill briefs + worklists.
CLEANUP_INSTRUCTIONS.md : this reorganisation brief.
```

`source_inputs/README.md`:
```
# source_inputs — raw inputs, agent-produced files, worklists
Uploaded agent files (SP500_marketdata_filled_pre_bulk.csv, FTSE_marketdata_handover_*best_evidence.csv,
sp500_shares_marketcap_bulk.csv), raw reference tables (FTSE100_CANONICAL_DATABASE, sp500_amended_database,
membership worklists), founding-research intermediates (sp500_founded_fill*, FTSE_founded_research,
sp500_founding_final), and the LSEG/SEC pull inputs. These feed the scripts; not final deliverables.
```

`deliverables/consolidated/README.md`:
```
# consolidated — finished analysis outputs
FTSE100_consolidated.csv / SP500_consolidated.csv : one row per company-year, all params + source URLs.
ftse_birth_audited.csv / FTSE_company_founding.csv / sp500_company_founding.csv : founding/birth dates + sources.
*_entrants_classified.csv, entrant_*_summary.csv, adjudication_*.csv : the "genuinely new entrant" analysis.
The two workbooks ftse_sources.xlsx / sp500_sources.xlsx (one tab per parameter) are one level up in deliverables/.
```

## STEP 5 — update the top-level `combined_dataset/README.md`
Add a short "Folder layout" section pointing to database/, deliverables/, reports/, docs/,
source_inputs/, python/, sql/. Keep the existing content.

## STEP 6 — verify
```
ls -la          # top level should show only: README.md, python/, sql/, *.sh, and the new subfolders
find . -maxdepth 1 -type f | grep -v -E "README|\.sh$"   # should be EMPTY (no stray top-level files)
```
Report: the final `ls`, whether you did STEP 3 (script paths) or left DB/inputs at root, and any file
you were unsure where to place (leave those at root and list them rather than guessing).
```
```
