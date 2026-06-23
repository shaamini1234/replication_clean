# Extraction guide — the 25 sourceable empty variables

**Run these on your own machine** (the pipeline reaches ONS there; this sandbox is blocked, HTTP 403).
For every variable: store the raw figure in `value_source`, the model-units figure in `value`
(£bn for money), set `ons_scale=1.0`, and **confirm the unit against the model before trusting it**.

---

## Group A — ONS-coded (9): use your existing pipeline (cleanest)

These have an ONS code in the OBR master sheet, so `cbp_fiscal_framework/inputs/ons_fetcher.py`
can fetch them. Method per variable: add the code(s) + ONS category path to `ONS_PATHS`, call
`fetch_variable`, then scale to model units. The fetcher already does the compound arithmetic.

| Variable | ONS code | Model unit | Note |
|---|---|---|---|
| `CDUR` | `UTID` | £bn (CVM) | durable consumption; also the input for PCDUR |
| `PCDUR` | `100*(UTIB/UTID)` | index (deflator) | derived — fetch `UTIB` & `UTID`, then compute |
| `CPIPRIVRENT` | `KYHJ` | index | CPI private rents |
| `CGISC` | `M9WU+RUDY` | £bn | sum of two codes |
| `HHTA` | `CGDS-FLVY-FHLS-FLVE` | £bn | 4-code formula (note: full code, not the truncated `CGDS-FLVY`) |
| `RLCOTC` | `JPPT-MDXH` | £bn | |
| `VTRCS` | `BKSG+BKSH` | £bn | |
| `WFTCNT` | `-MDYL+LIBJ` | £bn | |
| `MILAPME` | `DCHG+DCHF+GCJJ` | £bn | |

**Steps:** for each, find the ONS dataset/category for the code (ONS site search by code), add it to
`ONS_PATHS`, fetch, convert £m→£bn (×0.001) where it's a money series, store `value_source` (raw £m)
and `value` (£bn). Validate the magnitude before accepting.

---

## Group B — "No Codes", named external source (16)

No ONS code; each needs the right table from a named publisher. Several are *already in the OBR
files you migrated* (`sources_new/raw_data/...`), so you may not need the web — **but confirm units
against the model**, because the OBR table labels can mislead (see the energy note below).

### Tax receipts → HMRC (or the OBR Receipts detailed tables you have locally)
| Variable | Source | Where |
|---|---|---|
| `APPLEVY` | Apprentice levy receipts | HMRC tax receipts & NICs stats; or OBR Receipts table |
| `CORP` | HMRC owner-managed companies / dividend income | HMRC stats; or OBR economy/receipts assumption |
| `SDLT` | Stamp duty land tax receipts | HMRC SDLT stats; or OBR Receipts table |

### Interest rates → BoE / DMO
| Variable | Source | Where |
|---|---|---|
| `R10YR` | 10-year gilt yield | BoE/DMO gilt curve. (Local `timeseries/fred/gilt_yields.csv` is the FRED 10-yr — monthly, convert to quarterly average; **provenance is FRED, not ONS**) |
| `R5YR` | 5-year gilt yield | BoE/DMO gilt curve (no clean local source — the local BoE file is 20-yr) |

### Energy → OBR market assumptions (local) — UNIT CHECK REQUIRED
| Variable | Local source | Caution |
|---|---|---|
| `GAS` | OBR Economy Table 1.9, "Gas prices (£)" | model wants **pence/therm**; table is in £ → likely ×100. CONFIRM. |
| `PELEC` | OBR Economy Table 1.20, "Pence per MWh" | values ≈45 look like **£/MWh**, not pence/MWh → likely ×100. CONFIRM against the model. |

### UK macro → ONS / DLUHC
| Variable | Source |
|---|---|
| `GK` | ONS gross capital stock (capital stocks dataset) |
| `PEHS` | DLUHC/MHCLG private-enterprise housing starts |
| `POPNM` | ONS net migration (long-term international migration) |
| `PRODH` | ONS output per hour (productivity) |

### World economy → IMF WEO / OECD / OBR world tables
| Variable | Source |
|---|---|
| `WORLD` | World GDP — IMF WEO / OECD |
| `WTGS` | World trade in goods & services — IMF WEO / OECD |
| `EAGDP` | Euro-area GDP — Eurostat / IMF |
| `MAJCP` | Consumer prices, US/Canada/Japan/euro area — OECD |
| `EUXT` | EU trade with the rest of the world — Eurostat |
| `MKTGS` | UK export markets for goods & services — OBR world-economy assumption (derived from trade partners) |

---

## NOT in this list (for completeness)
- **6 add-factors** (`EESC_A`, `MGDPNSA_A`, `PRMIP_A`, `PSNBCY_A`, `SBHH_A`, `TYWHH_A`) — not data;
  load from the OBR's published add-factors once the `@ADD` parser fix (C4) is in. Do **not** fetch or invent.
- **~14 computed/trend** (`GGIX`, `MKR`, `DIPHHmf`, `DIPHHuf`, `KAL`, `KL`, `NAIRU`, `TFP`, `TR*`) —
  come out of the model or the OBR's supplementary "potential output" tables, not a data download.

## Golden rules (so you don't re-introduce today's bugs)
1. Always populate **both** columns: `value_source` (as published) and `value` (model units).
2. **Confirm the unit** against the model for every series (especially energy, money £m→£bn).
3. Tag the true provenance in `source`; keep `ons_scale=1.0`.
4. Validate the magnitude (a quick plausibility check) before accepting any new series.
