# OBR Model Replication — data side

**Start here.** This folder holds the time-series database that feeds the OBR macroeconomic model,
plus the provenance behind it and the open issues for the model side. The OBR publishes its
equations but no ready dataset, so the data-engineering job is to populate `timeseries.db` so the
equations can run. The model code itself (`cbp_fiscal_framework/`) is the economist's domain and is
**unchanged**.

For the live, always-current picture, open **`deliverables_new/DATA_STATE_INVENTORY_refreshed.xlsx`**
and read its **"READINESS – read first"** tab. This README is the narrative summary of the same thing.

---

## Current state (as of 2026-06-23)

- `timeseries.db`: integrity **OK**, ~110,000 quarterly observations, **663 catalogued series**.
- Of the **636 official OBR model variables, 609 are populated**.
- **Money units are now uniformly £bn** (the model convention). 271 money series carry a two-column
  structure: `value` = model units (£bn), `value_source` = the figure exactly as published (raw £m).
- Nothing fabricated is left unflagged. There is exactly **one** "not real" series remaining
  (`DIPHHuf`, a constructed FISIM proxy) and **one** empty-and-needed variable (`CORP`).

Every change made to the database is itemised in **`DATA_FIXES_CHANGELOG.md`**, each with a
timestamped backup in `archive/`. Everything is reversible.

---

## Folder map

| Item | What it is |
|---|---|
| `timeseries.db` | The database — the product. |
| `deliverables_new/` | The three things to read (see below). |
| `cbp_fiscal_framework/` | The economist's model package — **unchanged**. Cited by file+line in the issues register. |
| `Macroeconomic_model_code_March_2025.txt` | The OBR's published equations (issues register cites line numbers here). |
| `docs/OBR_Model_Variables_March_2025.xlsx` | The OBR's master list: every variable → ONS code → equation. |
| `sources_new/` | Provenance + the extraction pipeline (`extraction_pipeline/`, steps 01→16, each runnable on a machine with ONS/HMRC access). |
| `DATA_FIXES_CHANGELOG.md` | Every data change, dated, with its backup filename. The audit trail. |
| `EXTRACTION_GUIDE.md` | How to source the remaining empty variables (partly historical now — most are resolved). |
| `PROJECT_HANDOVER.md` | The original data-side handover notes. Superseded in places by the changelog; kept for context. |
| `archive/` | Pristine pre-cleaning original (`timeseries_OLD.db`), the most recent pre-change backup, and older superseded material. |
| `requirements.txt` | Python deps. |

### The three deliverables (in `deliverables_new/`)
- **`DATA_STATE_INVENTORY_refreshed.xlsx`** — the state of every series (start on the READINESS tab).
  Pink cells flag everything changed this session.
- **`OBR_model_issues_REVIEW_new.xlsx`** — the issues register for the model side (code/logic C1–C13,
  unit issues, missing inputs), each with a suggested fix.
- **`UNIT_FIX_REVIEW.xlsx`** — detail of the £m→£bn unit conversion (what was converted, what was left).

---

## What was done this session (summary; full detail in the changelog)

- **Units fixed.** Two passes converted all national-accounts money series from £m to £bn in the
  `value` column, keeping the raw £m in `value_source`. Verified via a GDP-ratio check that no
  quarterly flow remains mis-scaled. `TRPRODH` was also found 1000× too large and rescaled.
- **Cost block repaired.** The 8 cost indices (CCOST, SCOST, UTCOST, MCOST, RPCOST, ICOST, XGCOST,
  XSCOST) were overflowing to ~1e19. Root cause: the input chain (`GGVA → MSGVA → ULCMS`) was empty.
  Rebuilt those from the model's own identities and re-solved the block (base-year 2009 ≈ 100, as it
  must be). See the runtime caveat below.
- **Empties cleared.** `NAINSx` sourced from ONS (`NFYO+M9WF`); `PRODH` computed (`= GDPM/HWA`);
  the world-economy block (`WORLD`, `WTGS`, …) verified as never referenced by any equation → left
  empty by design. `NAINS`, `HHRES`, `OAHHADJ` regenerate from `NAINSx` in the recompute.
- **Fabricated data removed.** Four synthetic series were deleted and re-sourced/flagged.

---

## What the model side still needs (for the economist)

1. **Solver — the cost block.** The model loads ~60 core variables from the DB and **recomputes**
   the derived layer (including the cost block) at runtime. The DB now holds the correct values, but
   the runtime solver still needs to (a) solve the simultaneous cost block {CCOST, SCOST, UTCOST}
   jointly and (b) seed the `GGVA` recursion. Until then those equations won't reproduce at runtime.
2. **Code fixes (issues register).** C1: the driver re-reads OBR values instead of running the 33
   behavioural equations. C13: `GGIX` has a hard-coded £m constant — and so does the `NAINSx`
   forecast equation (line 791): its constant `13293.71` is £m and must be ÷1000 for the £bn
   convention. C2/C3/C4: parser bugs, including `@ADD` add-factors not loading (6 `_A` series).
3. **`CORP`** — the only empty-and-needed variable. It drives only the *forecast* of household
   dividends (`NDIVHH`); the historical outturn (`CRWF`) is already in the DB. It is an internal OBR
   series ("HMRC owner-managed corporations") not published anywhere — request it from the OBR
   directly (don't reconstruct a proxy, as the equation coefficient was fitted on their exact series).

---

## Reversibility

`archive/timeseries_OLD.db` is the pristine pre-cleaning database. `archive/timeseries.db.bak_before_money2_…`
is the most recent pre-change checkpoint. Every change is logged in `DATA_FIXES_CHANGELOG.md`. To undo
everything, restore `timeseries_OLD.db`.
# replication_clean
