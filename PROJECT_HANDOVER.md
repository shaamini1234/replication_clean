# Project handover — OBR model replication (data side)

_Read this first in a new chat. It captures the full state so work can continue without re-deriving context._

## 1. What this project is
We are replicating the **OBR macroeconomic model**. The OBR publishes its equations but not a ready
database, so **my job (data engineer) is to populate the time-series database** so the equations have
data to run on. The **equations/solver are my colleague's (economist's) domain** — I do **not** edit
his model code (`cbp_fiscal_framework/`). I am *building* the dataset (no one hands me ready series).

## 2. Folder map (`~/Documents/CBP/replication_clean`)
- `timeseries.db` — the database (the product).
- `cbp_fiscal_framework/` — colleague's model package. **Untouched. Do not edit.**
- `Macroeconomic_model_code_March_2025.txt` — the OBR's published equations.
- `docs/OBR_Model_Variables_March_2025.xlsx` — OBR's master list of model variables (the "what's needed").
- `deliverables_new/` — the outputs (see §6).
- `sources_new/` — provenance: OBR/HMRC source files (`raw_data/`), the extraction scripts
  (`extraction_pipeline/`, steps 01–16, each with a README), and provenance docs.
- `DATA_FIXES_CHANGELOG.md` — itemised log of every data change.
- `EXTRACTION_GUIDE.md` — how to source the remaining empty variables.
- `requirements.txt` — python deps (requests, openpyxl, pandas, numpy, matplotlib, odfpy).
- `old_files/` — backups + superseded files (incl. `timeseries_OLD.db` = pristine pre-cleaning original,
  and per-run `timeseries.db.bak`). Nothing deleted; reversible.

## 3. Key conventions (IMPORTANT)
- **Two-column structure in `observations`:** `value_source` = the figure exactly as published (raw);
  `value` = the same in **model units** (£bn for money, etc.). **The model reads `value`.** Every series
  has `ons_scale = 1.0`; `series.source_scale` documents the conversion applied. No code change was
  needed for this.
- **Honesty rule:** nothing fabricated may sit unflagged. Constructed/synthetic/placeholder values are
  labelled in `series.label` and tagged in `source`.
- **Extraction runs on the user's machine** (ONS/BoE/HMRC are reachable there; they are blocked in the
  assistant sandbox, so the assistant writes scripts and the user runs them).
- The model/data were verified byte-for-byte unchanged where claimed (hashing); backups exist.

## 4. Current state of the database (source of truth: `deliverables_new/DATA_STATE_INVENTORY.xlsx`)
663 catalogued series (659 model + 4 parked). Of the official **636** OBR variables, **~610 populated**.
Provenance breakdown:
- **Genuine:** 467 real (ONS/OBR/FRED/HMRC), 108 computed via the model's own identities, 47 constants.
- **Flagged (amber — real but check):** 3 unit-unconfirmed (`GAS`, `PELEC`, `TRPRODH` — a ×100 £→pence
  assumption), 3 derived residuals, 3 empty-but-needed.
- **Flagged (red — NOT real, all labelled):** `DIPHHuf` (constructed today via an invented FISIM-analogy
  formula — see §5), 4 synthetic (`NAINSx`, `NAINS`, …), 5 quarantined parked series, placeholders.
- **Empty for legitimate reasons:** 6 add-factors (`*_A`, fill via code fix C4), 2 computed-in-recompute,
  13 not used by any equation (incl. all 6 world-economy vars — the model never references them).

## 5. Open items / decisions pending
- **`DIPHHuf` — DECISION NEEDED.** It currently holds a *constructed* value from an **invented formula**
  (`OLPEx(-1)·((1+(Runsec−R)/100)^0.25−1)`, mirroring the real `DIPHHmf` equation) AND the value is
  currently *wrong* (negative — built with the wrong rate). The OBR lists DIPHHuf as **exogenous (no
  equation)** → it should be *sourced*, not derived. Recommended: **delete the DIPHHuf rows** and park it
  with CORP as "needs real exogenous data" (ONS unsecured-FISIM). Alternative: re-run step 16 with BoE rate
  `IUMBX67` as a clearly-labelled proxy.
- **`CORP` — needs sourcing.** Confirmed definition: "HMRC owner-managed corporations" (drives household
  dividends `NDIVHH`). It is **not in any project file** (checked). Source from HMRC owner-manager/close-
  company income, on the user's machine. Coefficients were estimated on the OBR's exact series, so a proxy
  biases the equation — flag if proxied.
- **World economy (`WORLD`,`WTGS`,`EAGDP`,`MAJCP`,`EUXT`,`MKTGS`):** the equation file **never references
  them** → not worth extracting for this model. Leave empty.
- **Recompute pass (data-side, after code fixes):** re-run the identity solver once to regenerate the
  derived layer (`MCGG`,`MIF`,`GGIX`,`DIPHHmf`,…). Needs the economist's C13/C2 fixes first or it
  reproduces garbage (e.g. GGIX's hard-coded £m constant).
- **Refresh the audit notebook + inventory** after any further changes.

## 6. Deliverables (in `deliverables_new/`)
- `DATA_STATE_INVENTORY.xlsx` — **the provenance map** (every series: status, source, span). Start here.
- `OBR_model_issues_REVIEW_new.xlsx` — issues register: Code & Logic (C1–C13, the economist's), Unit
  (U1–U7, resolved), Missing inputs, Data integrity (Phase-8 synthetic/placeholder).
- `database_audit.ipynb` / `.html` — proves the DB is full and traceable.

## 7. Code issues for the ECONOMIST (in the issues spreadsheet, with file/line refs)
- **C1 (biggest):** the main driver never runs the 33 behavioural/forecasting equations — it re-reads OBR
  values. The model adds up but doesn't yet forecast.
- **C2/C3/C4:** parser bugs (date dummies silently off; two `d(X)/X(-1)` equations dropped; `@ADD`
  add-factors discarded — needed to load the OBR's published add-factors for the `*_A` series).
- **C12:** `variable_map.py` maps `ES` to OBR *total employees* (should not).
- **C13:** the `GGIX` equation has a hard-coded **£m** constant (`17394`) — must be scaled now inputs are £bn;
  plus a forecast overflow. GGIX can't be recomputed correctly until fixed.

## 8. One-line status
Data task is largely done and honest: the database is full where it can be (610/636), units fixed via a
two-column structure, every non-genuine value flagged, and the remaining gaps are documented and assigned
(CORP + DIPHHuf to source; the rest to the recompute or the economist's code fixes).
