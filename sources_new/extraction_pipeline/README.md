# Extraction pipeline — how the database was populated

Shaamini's data-population work, in running order. These scripts populate / extend
`timeseries.db`. They do **not** modify `cbp_fiscal_framework` (the model package).

## Original build (steps 01–09)
| Step | File | What it does |
|---|---|---|
| 01 | `01_initial_pipeline_build_db.ipynb` | Creates the DB, discovers ONS paths, loads the first batch from OBR Economy tables. |
| 02 | `02_fiscal_data_loader.ipynb` | Adds fiscal series (receipts, spending, public-finance aggregates) from OBR databanks. |
| (3) | `ons_probe_progress.json` | Artifact of the ONS path-discovery step. |
| 04 | `04_computed_variables.ipynb` | Computes variables with no direct source from the model identities. |
| 05 | `05_missing_exogenous.py` | ONS compound-formula vars, statutory constants, calibration defaults, population. |
| 06 | `06_compute_derived.py` + `06_derived_inserts.sql` | Runs the identity solver across all quarters to derive ~48 more variables. |
| 07 | `07_ons_stocks.py` | Downloads ONS stock series for the recursive equations' seed values. |
| 08 | `08_unblock_variables.py` | Sources the previously "blocked" variables. |
| 09 | `09_compute_addfactors.py` | Computes add-factors (residuals) for the behavioural equations. |

`tracking_missing_variables.xlsx` tracks which model variables still had no data.

## Later additions — filling remaining empty series (steps 10–11)
**Run from a machine that can reach ONS** (not the cleaning sandbox). Both auto-locate the
repo root, back up `timeseries.db.bak` first, write the two-column structure
(`value_source` = raw, `value` = model units), and print magnitudes to eyeball.

| Step | File | What it does |
|---|---|---|
| 10 | `10_fetch_ons_coded_empties.py` | Fetches the ONS-coded empty variables (CDUR, PCDUR, CGISC, HHTA, RLCOTC, VTRCS, WFTCNT, MILAPME): discovers each code's ONS dataset path, fetches/computes via the existing `ONSFetcher`, converts to model units, loads. |
| 11 | `11_fetch_cpiprivrent.py` | Fetches CPIPRIVRENT (`KYHJ`) — a *monthly* series — and averages it to quarterly (the main fetcher only reads quarterly/annual). |
| 12 | `12_fetch_r10yr.py` | Loads R10YR (10-yr gilt yield) from the local FRED CSV (`raw_data/timeseries/fred/gilt_yields.csv`), monthly→quarterly. Fully local, no web. Tagged `source='FRED'`. |
| 13 | `13_fetch_energy_obr.py` | Loads GAS & PELEC from the local OBR Economy tables (1.9, 1.20). Fully local. **UNIT UNCONFIRMED** — applies ×100 (£→pence) to `value`; `value_source` keeps raw £. 2022 spike cross-checks the ×100. Set `CONVERT=1.0` if the model expects £. |
| 14 | `14_fetch_hmrc_tax.py` | Loads SDLT & APPLEVY from the local HMRC monthly tax-receipts `.ods` (sum 3 months/quarter, £m→£bn). Fully local; needs `odfpy`. History from 2017Q2. `CORP` not loaded (not a receipts line). Cross-checks the OBR annual SDLT (~£14bn/yr). |
| 15 | `15_fetch_obr_trends.py` | Loads NAIRU, TRER, TRPART16, TRAVH, TRPRODH from the local OBR Potential-output table 1.15 (levels). Fully local. value==value_source (rates/hours/levels). History from 2019Q1. TRHS not present in 1.15 → still pending. TRPRODH unit unconfirmed. |
| 16 | `16_build_diphhuf.py` | **Builds** DIPHHuf (FISIM proxy) = OLPEx(-1)·((1+(Runsec−R)/100)^0.25−1), mirroring DIPHHmf. Needs a BoE consumer-credit rate CSV at `raw_data/timeseries/boe/consumer_credit_rate.csv`. Labelled CONSTRUCTED (not the OBR series). Confirm method/rate + the DIPHHx units with the economist. |

Run example (from the repo root, in your venv):
`python sources_new/extraction_pipeline/11_fetch_cpiprivrent.py`

## Two honest caveats
1. **Paths in 01–09 are hard-coded to the original `budget-master` repo** — they are the
   *record* of how the DB was built, not plug-and-run from here. Steps 10–11 are repo-relative
   and runnable.
2. **Notebook outputs are from the original runs** — the authoritative current figures are in
   `../../deliverables_new/database_audit.ipynb`.
