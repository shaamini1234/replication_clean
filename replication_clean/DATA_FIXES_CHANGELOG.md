# Data fixes & additions — changelog

Running record of every change to `timeseries.db`. The pre-cleaning original is preserved as
`old_files/timeseries_OLD.db` (checksum `64dc2158…`); the scripts also write a `timeseries.db.bak`
each run (now in `old_files/`).

**Current state:** integrity OK; **623 of 659 model series populated**; 36 empty (see end).

---

## Convention: two-column structure (units)
The `observations` table has two value columns:
- **`value_source`** — the figure exactly as the source published it (provenance; never altered).
- **`value`** — the same figure in the model's units (£bn for money; thousands/index/percent otherwise).
  **The model reads `value`**, so equations use model units with no code change. `ons_scale=1.0`
  everywhere (no read-time rescaling); `series.source_scale` documents the factor applied.

This was built from the pristine `timeseries_OLD.db` so the two columns are perfectly consistent.

---

## Unit fixes (U1–U7) — all DONE
- **U2/U3 £m→£bn:** RHHDI, IBUSX, IHPS, MGDPNSA, DEPHH, EQHH, PIHH, OLPEx, STUDENT, WFP, XNOG, XS,
  MNOG, OAHH, MS, plus the 31 "convert-on-read" series (CGG, IF, …) — all stored in £bn.
- **U1 PSAVEI:** ONS £/week rebased to the OBR index base (×0.2304, 2008Q1=100); continuous with OBR.
- **U4 ES:** ONS scale 10→1.0 (DYZN in thousands); mislabelled OBR rows parked (see below).
- **U5 double-scaling:** resolved by the Option-A convention (one conversion, stored once).
- **U6 RXD:** verified correct ($/£), no change.
- **U7 BPA:** ONS rows £m→£bn; spurious GDPM-seed row quarantined.

## Mislabelled / corrupt / placeholder — QUARANTINED or LABELLED (nothing deleted)
- **ES** OBR rows (total employees mis-mapped to ES) → parked `ES_obr_employees_MISLABELLED`.
- **GGIX** (overflowed ~1e17 + stale £m) → all rows parked `GGIX_CORRUPTED_pre-recompute`; flagged pending C13.
- **BPA** seed artifact → `BPA_gdpm_seed_artifact`.
- **MKR** (flat-100 placeholder) → parked `MKR_placeholder_PARKED`; flagged NOT AVAILABLE.
- **NAINSx/NAINS** relabelled SYNTHETIC (false ONS code removed); **CPIXBASE** marked constant;
  **CPIX** marked derived/approx; **GMF/HHRES/OAHHADJ/NAOLPEx** marked derived (regenerate in recompute).

## Missing inputs — labelled PENDING
- `CORP`, `DIPHHuf`, `PCDUR` labelled "PENDING SOURCING" (sourcing details in `EXTRACTION_GUIDE.md`).

## Data additions — ONS-coded empty variables (extraction steps 10–11) — DONE
Run from a machine with ONS access; scripts in `sources_new/extraction_pipeline/`. All loaded with
the two-column convention, source=ONS, integrity OK, magnitudes spot-checked.
- **Step 10** (`10_fetch_ons_coded_empties.py`): CDUR (164q, £bn), PCDUR (164q, index 69–103),
  CGISC, HHTA, RLCOTC (265q), VTRCS, WFTCNT, MILAPME.
- **Step 11** (`11_fetch_cpiprivrent.py`): CPIPRIVRENT (121q, index 75–139; KYHJ monthly→quarterly).
- **Step 12** (`12_fetch_r10yr.py`): R10YR (263q, 0.25–16.0%; FRED 10-yr gilt, monthly→quarterly, tagged source=FRED). 2008Q1=4.52% cross-checks the OBR's long-term rate.
- **Step 13** (`13_fetch_energy_obr.py`): GAS (93q) & PELEC (77q) from local OBR Economy tables 1.9/1.20. **UNIT UNCONFIRMED** — value = raw £ ×100 (assumed £→pence); 2022 spike cross-checks the ×100 (GAS 289 p/therm, PELEC ~29,900 p/MWh). value_source keeps raw £; flagged in labels. Set CONVERT=1.0 if model expects £.
- **Step 14** (`14_fetch_hmrc_tax.py`): SDLT (36q) & APPLEVY (35q) from local HMRC monthly tax-receipts .ods (sum 3 months/quarter, £m→£bn, from 2017Q2; source=HMRC). SDLT FY2024-25 = £13.88bn cross-checks the OBR's £13.885bn. CORP not loaded (not a receipts line) — stays PENDING.
- **Step 15** (`15_fetch_obr_trends.py`): NAIRU, TRER, TRPART16, TRAVH, TRPRODH (49q each, 2019Q1–2031Q1) from local OBR Potential-output table 1.15 (levels; value==value_source). TRHS not in 1.15 (pending); TRPRODH unit unconfirmed.
- **Result:** populated **610 / 636 officially-needed** variables (26 empty). (DB catalogue 633/659; the extra 23 populated series aren't in the official sheet and were left untouched.)

---

## 2026-06-23 — Synthetic series removed (NAINSx, NAINS, HHRES, OAHHADJ)
Per decision, the four fabricated series were **deleted** (no longer quarantined-in-place) and moved to
needs-real-data. Reversible: pre-change backup at `old_files/timeseries.db.bak_before_synthetic_removal_20260623_090954`.
- Deleted **318 observation rows** (NAINSx 90, NAINS 90, HHRES 69, OAHHADJ 69). Series rows kept, 0 obs.
- Relabelled `series.label` to **PENDING**. `NAINSx` = needs a real source (was a hard-coded recursive
  formula); `NAINS`/`HHRES`/`OAHHADJ` are **identities** that recompute once `NAINSx` is real.
- Integrity OK after change (`109,196` obs total; `634` series with data).
- Inventory refreshed: `deliverables_new/DATA_STATE_INVENTORY_refreshed.xlsx`. Synthetic count now **0**;
  needed-but-empty now **7** (CORP, PRODH, WORLD, NAINSx, NAINS, HHRES, OAHHADJ); official coverage **607/636**.

---

## 2026-06-23 — £m to £bn unit conversion (two-column structure)
Confirmed convention from `cbp_fiscal_framework/core/winsolve/variable_map.py` (lines 463-466): the model
reads `value` and expects **£bn for national accounts** (thousands for employment, etc.). Many national-
accounts series were still stored in £m. Backup: `old_files/timeseries.db.bak_before_unit_fix_20260623_094747`.
- **Converted 110 series (19,295 rows):** `value = value_source * 0.001` (now £bn), `value_source` kept as
  raw £m, `source_scale = 0.001`. Scope = series whose median scale can only be £m (CONVERT-money) plus the
  ambiguous-but-clearly-£m REVIEW bands. Spot-checks: GVA 553,374→553.37; M4 2,110,567→2,110.57; GGGD→1,621.41.
- **Held 17 mixed-unit series (NOT converted):** CGMISP, CGNB, CGNCR, CGSUBPR, CGT, CGTSUB, KPSCG, LASUBPR,
  LATSUB, LCGOS, MILAPM, NAOTLROW, NPACG, OPSKTA, PCLEND, PSCB, PSND. These hold a mix of £bn level rows and
  stray rows (e.g. PSND is already £bn with odd add-factor rows); a blanket /1000 would corrupt correct data.
  Need a per-series unit decision. See `deliverables_new/UNIT_FIX_REVIEW.xlsx`.
- Integrity OK after change. Employment/population (thousands), indices and rates were correctly excluded.

---

## 2026-06-23 — Cost block fixed (overflow corruption resolved)
The 8 cost indices (CCOST, SCOST, UTCOST, MCOST, RPCOST, ICOST, XGCOST, XSCOST) were overflowing to ~1e19.
Root cause: the input chain was missing. `GGVA` had only its 2008Q1 anchor, so `MSGVA = GVA - GGVA`, `ULCMS`
and `PMSGVA` could not be computed, and the simultaneous cost block had no real inputs. Backup:
`old_files/timeseries.db.bak_before_costblock_20260623_100712`.
- **Rebuilt the input chain (data-side, model identities):** GGVA (285q, via `GGVA/GGVA(-1)=CGG/CGG(-1)`
  anchored at the 2008Q1 OBR value), MSGVA (285q, =GVA-GGVA), PMSGVA (116q), ULCMS (116q, model line 246),
  ULCMSBASE (corrected to **75.02**; was a wrong 3034.73).
- **Recomputed the cost block (outturn, 72q each)** by solving the simultaneous system {CCOST,SCOST,UTCOST}
  jointly and the 5 downstream indices. Validation: base-year 2009 indices = ~100 (as they must be by
  definition), no negatives, max|value|<200. Inputs loaded the way the model does (OBR OUTTURN @2026-03, ONS fill).
- **IMPORTANT (runtime boundary):** the model loads only the ~60 VARIABLE_MAP core series from the DB and
  **recomputes** this derived layer at runtime. So this fixes the DATABASE SNAPSHOT (no more 1e19; inventory
  honest) but the model RUN still needs the economist's solver to (a) handle the simultaneous cost block and
  (b) seed the GGVA recursion. The values written here are the correct target to reproduce.
- Forecast period (2026Q1+) left empty for the model solver (ULCMS inputs are outturn-only to 2025Q4).

---

## 2026-06-23 — NAINSx sourced from ONS (real outturn)
NAINSx was wrongly treated as "synthetic". It has a real ONS source `NFYO+M9WF` (the big numbers in the
model equation are the OBR's estimated AR(1) coefficients, not fabrication). Fetched via
`sources_new/extraction_pipeline/16_fetch_nainsx.py` (run on the user's machine).
- Loaded **156 quarters** (1987Q1–2025Q4), value=£bn / value_source=raw £m, source=ONS. Range ~ -£5bn to
  +£10bn, median ~£2bn. This is INSURANCE only (pensions are NAPEN, separate) — small flows are correct.
- Resolves 4 of the 7 needed-empties: NAINS = NAINSx + NAINSADJ (NAINSADJ ~ 0); HHRES, OAHHADJ regenerate
  as identities in the recompute pass.
- **ECONOMIST**: the NAINSx forecast equation (line 791) constant 13293.71 and SIPT coeff 236267.3 are
  £m-calibrated; divide by 1000 for the £bn convention (C13-type fix).

---

## 2026-06-23 — PRODH computed (identity), TRPRODH rescaled
PRODH is NOT an external fetch: the model defines it as `@IDENTITY PRODH = GDPM / HWA` (line 171).
Both inputs are in the DB, so computed directly. Backup: `old_files/timeseries.db.bak_before_prodh_20260623_102530`.
- **PRODH** computed (241q, 1971Q1-2031Q1) = GDPM/HWA on the £bn basis (~0.27-0.68). source=COMPUTED.
- This exposed **TRPRODH** (trend, OBR table 1.15) being ~1000x too large (637 vs PRODH 0.63) — it had been
  flagged "UNIT unconfirmed". Rescaled `value = value_source*0.001`, source_scale=0.001; PRODH and TRPRODH
  now match (actual just below trend, ratio ~1.0). Resolves the TRPRODH unit flag.

---

## 2026-06-23 — WORLD question settled: leave empty (not referenced)
Verified against the equation file: the world-economy block is never referenced by any equation.
WORLD appears once only as a comment/section header (`' REST OF WORLD`, line 834); WTGS, EAGDP, MAJCP,
EUXT, MKTGS appear 0 times. Labels updated to "NOT referenced by any model equation; leave empty."
WORLD removed from the needed-empty list — no sourcing required. Only CORP now remains to source.

---

## 2026-06-23 — Unit conversion COMPLETED (pass 2): 89 more £m flows -> £bn
Audit (triggered by spotting NDIVHH in £m) found the first conversion pass was incomplete: ~89 genuine
£m money flows were never converted (the median-based thresholds + some keyword misses left them at
source_scale=1.0). Detected reliably via the GDP-ratio test (a quarterly money FLOW cannot be several x
GDP, so any flow at 2-73x GDP is £m). Backup: `old_files/timeseries.db.bak_before_money2_20260623_104335`.
- **Converted 89 flow series** (value=value_source*0.001 -> £bn; ~15,900 rows). Includes taxes (CT, TSD,
  TXFUEL, TXTOB, TXALC, VED, BANKROLL, CC, NNDRA, OCT), income flows (NDIVHH, DIPHH, DIRHH, PIPHH, DIPIC),
  net-lending/acquisition flows, operating surpluses (OSCO, OSGG, OSPC), govt flows (CGIPS, DEP, PSNCR,
  TDEF, LANB, accruals adjustments), etc. Spot-checks: CT 11.2; NDIVHH 8.9; TXFUEL 5.9 (£bn) - all sensible.
- **Left as already-£bn (stocks):** PSND (net debt £1,595bn), GFWPE (HH financial assets £7tn). Not flows.
- **Left flagged:** GGIX (quarantined), NAOLPEx (derived, recompute), TROD (approx), HHDI_ANN (likely £bn annual).
- Re-audit after conversion: no flow-like series remain mis-scaled. The earlier 125 conversions were also
  re-checked - all internally consistent (no half-conversions). Money units are now uniformly £bn.

---

## 2026-06-23 — Folder tidy-up (for handover)
Housekeeping only; no data changes to `timeseries.db`.
- **Backups consolidated.** Kept `archive/timeseries_OLD.db` (pristine pre-cleaning original) and the
  most recent pre-change checkpoint (`archive/timeseries.db.bak_before_money2_20260623_104335`).
  Deleted the intermediate per-step session backups (before_synthetic_removal, before_unit_fix,
  before_held17, before_costblock, before_prodh) and the older `timeseries.db.bak` — so the
  earlier entries in this changelog that name those backups now point to files that were removed on
  purpose; the pristine original is the single rollback anchor.
- **`old_files/` renamed to `archive/`** (removed a trailing space in the old name).
- **Superseded deliverables removed:** the old `DATA_STATE_INVENTORY.xlsx` (replaced by
  `_refreshed`) and `database_audit.html`/`.ipynb` (they audited the pre-cleaning DB and were
  misleading). Current deliverables: `DATA_STATE_INVENTORY_refreshed.xlsx`,
  `OBR_model_issues_REVIEW_new.xlsx`, `UNIT_FIX_REVIEW.xlsx`.
- **Junk removed:** all `__pycache__/`, `*.pyc`, `.DS_Store`, stale `timeseries.db-journal`.
- **Extraction pipeline untouched** — all scripts in `sources_new/extraction_pipeline/` (01–16) kept.
- Folder size: ~213MB → ~112MB.

---

## Still outstanding
- **16 extractable "No Codes" variables** (SDLT, APPLEVY, CORP, R5YR, R10YR, GAS, PELEC, GK, PEHS,
  POPNM, PRODH, EAGDP, MAJCP, WORLD, WTGS, EUXT, MKTGS) — named sources, see `EXTRACTION_GUIDE.md`.
- **6 add-factors** (`*_A`) — load from the OBR vintage via the C4 parser fix; do not fetch.
- **~14 computed/trend** — come from the model/OBR filtering; regenerate in the recompute pass.
- **Recompute pass** — regenerate the derived layer (MCGG, MIF, GGIX) from corrected inputs;
  needs the economist's code fixes first (C13/C2). See `deliverables_new/OBR_model_issues_REVIEW_new.xlsx`.
