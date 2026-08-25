# shaamini_new — Guide & Map

The self-contained UK Business Dynamism handoff package. Everything needed to read, verify,
and rebuild the database is inside this one folder (~8.4 GB, almost all of it the database file).

## Where to start

1. **Just want the data?** → `deliverables/` — clean CSVs and two Excel workbooks, every value with a source.
2. **Want the whole database?** → `database/business_dynamism_v2_20260824d.duckdb` — one file, 21 tables, opens in DuckDB with no cloud/login.
3. **Want to know how it was built or rebuild it?** → `python/` + `sql/` + `docs/`.

---

## Map

```
shaamini_new/
├── README.md                     short orientation
├── GUIDE.md                      this file
│
├── database/                    (8.4 GB) the canonical single-file database
│   ├── business_dynamism_v2_20260824d.duckdb      21 tables, whole-population + FTSE/S&P overlays
│   └── business_dynamism_v2_20260824d.duckdb.zst  compressed backup
│
├── deliverables/                the ready-to-use outputs (start here)
│   ├── ftse_sources.xlsx        FTSE workbook: one tab per parameter, value + source_url
│   ├── sp500_sources.xlsx       S&P workbook: one tab per parameter, value + source_url
│   ├── consolidated/            wide "everything" CSVs + the entrant/founding analysis
│   ├── ftse/                    one CSV per FTSE parameter (revenue, market_cap, spine, …)
│   └── sp500/                   one CSV per S&P parameter (revenue, market_cap, spine, …)
│
├── source_inputs/               the raw/handover CSVs the database was built from
├── python/                      all build & fetch scripts
├── sql/                         the DuckDB build steps (01…12, run in order)
├── docs/                        handoff specs & method notes
└── reports/                     standalone HTML reports (open in a browser)
```

---

## deliverables/ — the outputs in detail

**Two Excel workbooks** (the "source" files): `ftse_sources.xlsx`, `sp500_sources.xlsx`.
Each has one tab per financial parameter — Revenue, Net_Income, Total_Assets, Market_Cap,
Shares, (FTSE: Share_Price, Dividend / S&P: Employees) — plus a **Spine** tab (identity +
entry/exit dates with their source) and a Birth/Founding tab. Every parameter tab pairs the
value with a `source_url`.

**consolidated/** — the wide, one-file-each views and the analysis:
- `FTSE100_consolidated.csv`, `SP500_consolidated.csv` — every parameter + source columns in one sheet (now including entry/exit-date sources).
- `ftse_birth_audited.csv`, `FTSE_company_founding.csv`, `sp500_company_founding.csv` — founding dates.
- `*_entrants_classified.csv`, `entrant_final_summary.csv`, `entrant_trend_summary.csv`, `adjudication_*` — the "genuinely new company at index entry" analysis (establishment date vs entry date).

**ftse/** and **sp500/** — one dedicated CSV per parameter, each with value + source_url.
The `*_spine.csv` files hold identity + entry/exit dates: FTSE carries `entry_source`/`exit_source`
(LSEG "Historic Additions & Deletions" for exits, the CBP 1984 launch roster for founders —
citations, because the LSEG source is licensed); S&P carries `entry_source_url`/`exit_source_url`
(real per-company links — Wurgler S&P-changes dataset, SEC, SPGlobal press releases).

---

## database/ — the DuckDB file

One file, no server. Open read-only:

```
python3 -c "import duckdb; c=duckdb.connect('database/business_dynamism_v2_20260824d.duckdb', read_only=True); print(c.execute('show tables').fetchall())"
```

Key tables: `combined_firm_year` (39.4M), `firm_year_panel` (39.1M), `firm_master` (7.9M),
`companies` (5.7M), `exit_events` (583k), `gazette_events` (1.0M), `ch_company_profile` (384k),
plus FTSE overlays (`ftse100_*`, `ftse_birth_audited`) and S&P overlays (`sp500_financials` with
the market-cap boost, `sp500_consolidated`, `sp500_founding`, `sp500_membership`, `sp500_sec_supplement`).
`_build_info` records the build provenance.

---

## Rebuilding / refreshing (for the technical reader)

Data lives in Neon (cloud Postgres) and is folded into the DuckDB file. Typical sequence:
1. `python/commit_uploaded_marketdata.py` (or the faster batched `commit_marketdata_fast.py`) — commits staged CSVs from `source_inputs/` to Neon, fill-where-null.
2. `BD_DUCKDB=<path to the .duckdb> python/build_duckdb.py neon` — pulls the 10 market/membership/crawl tables from Neon into the DuckDB.
3. `python/build_source_workbooks.py` then `add_spine_sources.py` — regenerate the two workbooks and re-add the Spine/consolidated source columns.

`sql/01…12` are the from-scratch build of the whole-population panel; `docs/` explains each handoff.

---

## Provenance rule (how to trust a value)

Every value is either a **sourced fact** carrying a `source_url` (or a document citation where the
source is licensed and has no public URL), or it is left **blank**. Nothing is fabricated, and
fills never overwrite an existing good value. "Better blank than wrong" — especially for founding
dates, where a later holding-company date would falsely make an old firm look new (those are parked
separately in `legal_entity_founded_year`, never used as the founding date).
```
