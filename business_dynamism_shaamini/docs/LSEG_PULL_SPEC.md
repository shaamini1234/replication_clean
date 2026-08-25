# LSEG / Datastream pull spec — FTSE fundamentals 2000–2020 (the gap)

Goal: fill **revenue, net income (profit), total assets** (and, if easy, market cap +
shares) for the FTSE universe back to **2000**, annual. This is the one stretch no free
source can supply. LSEG Datastream has 100+ years of history via the Excel add-in.

## 1. Do you have access?
Check for **LSEG Workspace** (formerly Refinitiv Eikon) with the **Excel Add-in** and/or
**Datastream for Office (DFO)**. British Progress, or a partner university/library, may have
a seat. In Excel, look for an "LSEG" / "Datastream" / "Refinitiv" ribbon tab. If it's there,
you can pull everything below in one workbook.

## 2. Universe
Use `LSEG_pull_universe.csv` (in this folder) — 328 FTSE-history companies with:
`company_number` (our join key), `company_name`, `ric_ticker` (97 have one), `ftse_first`,
`ftse_last`. For the 97 with a ticker, the **RIC = ticker + ".L"** (e.g. `III` → `III.L`,
`BP` → `BP.L`). For the rest, match by company name or ISIN in Workspace's lookup.
Including the dead/former constituents matters — it avoids survivorship bias.

## 3. Data items to pull (annual, FY, 2000–2026)
Pull whichever interface you have. Both use the same underlying Worldscope fundamentals.

**Datastream (DFO) — Worldscope mnemonics:**
| Field | Mnemonic |
|---|---|
| Net sales / revenue | `WC01001` |
| Net income (bottom line) | `WC01751` (or `WC01651` net income before preferred divs) |
| Total assets | `WC02999` |
| Market capitalisation | `WC08001` (or Datastream `MV`) |
| Common shares outstanding | `WC05301` (or `NOSH`) |
| Reporting currency | `WC06026` |
Frequency: annual. Start 2000, end latest. Static request across the universe list.

**LSEG Workspace Excel Add-in — TR fields (Formula Builder):**
`TR.Revenue`, `TR.NetIncome`, `TR.TotalAssetsReported`, `TR.CompanyMarketCap`,
`TR.SharesOutstanding`, `TR.CurrencyReported` — with parameters
`SDate=2000FY EDate=2026FY Frq=FY` (i.e. every fiscal year 2000→latest).

## 4. Export format I need back
Save as **CSV** in this folder (any name starting `LSEG_`). Ideal is **long/tidy**:

```
identifier, company_number, fiscal_year, revenue, net_income, total_assets, market_cap, shares_outstanding, currency
```

If it's easier to export **wide** (one column block per year), that's fine too — just keep
the identifier column (RIC/ISIN/name) so I can map it back to `company_number`. Don't
hand-edit values. Include the currency column — many FTSE firms report in USD/EUR.

## 5. What I do with it
I parse your `LSEG_*.csv`, map identifiers → `company_number`, and merge into the database
and the consolidated CSV with `source='LSEG Datastream'` and a note of the pull date as
provenance (LSEG terms don't allow re-publishing the raw feed, but derived figures in your
own research are fine — check your licence). Estimated/derived flags stay separate from
these sourced values.

## 6. Licence note
LSEG data is licensed. Using it to populate your internal research database and publishing
*derived* analysis is standard for think tanks/universities, but confirm your seat's licence
permits the intended publication. We record it as sourced (provider + date), not scraped.
