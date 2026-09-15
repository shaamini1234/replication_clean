# LSEG-sourced data — replacement source brief

Companion to `lseg_sourced_data_for_replacement.csv` (423 rows).

## What the LSEG dependency actually is

One thing only: **FTSE 100 index membership dates** (entry and exit), cited as
`LSEG, FTSE 100 Historic Additions and Deletions, April 2026`. The copy we worked from is a
licensed PDF held locally at
`../business_dynamism-master/business_shaamini/lseg_ftse100_additions_deletions_apr2026.pdf`.

**RESOLVED (Sept 2026): the same document is published openly by FTSE Russell.** The
August 2026 edition (19 Jan 1984 - 22 Jun 2026, 549 change events) is a public policy
document on lseg.com, so the citation can now carry a link:

- <https://www.lseg.com/content/dam/ftse-russell/en_us/documents/policy-documents/ftse-100-constituent-history.pdf>
- Wayback backup (11 May 2026 capture):
  <http://web.archive.org/web/20260511144758/https://www.lseg.com/content/dam/ftse-russell/en_us/documents/policy-documents/ftse-100-constituent-history.pdf>
- Citation: *FTSE Russell (LSEG), FTSE 100 Historic Additions and Deletions, August 2026 (public PDF)*

Every row in `lseg_sourced_data_for_replacement_FILLED.csv` is sourced against it; see
`LSEG_REPLACEMENT_SOURCING_NOTES.md` for coverage and the rows needing judgement.

**No financial data is LSEG-sourced.** The Datastream pull described in
`docs/LSEG_PULL_SPEC.md` was specified but never executed — there is no `LSEG_*.csv`
result file, only the `LSEG_pull_universe.csv` target list. Revenue, net income,
total assets, market cap, share price, dividends and shares outstanding all come from
Yahoo Finance, Companies House, SEC EDGAR or annual reports.

Two matches are **false positives, already excluded**: `finance.yahoo.com/quote/LSEG.L/financials`
(Yahoo data *about* LSEG plc, ticker in the URL) and `LONDON STOCK EXCHANGE GROUP PLC`
appearing as a company name — LSEG is itself a FTSE constituent.

## What needs replacing

| Status | Rows | Meaning |
|---|---|---|
| `needs_replacement_source` | 399 | Date is present; find a public source that confirms it |
| `value_missing_source_cited` | 22 | LSEG cited but the date is blank — find the date itself |
| `low_priority_public_page` | 1 | `londonstockexchange.com` history page, public web content, not licensed data. Optional |
| `orphan_row_no_identity` | 1 | Empty row in `ftse_spine.csv` line 76 — data artifact, delete it, no source needed |

262 distinct companies. 212 entry dates, 210 exit dates.

## How to fill the CSV

Leave all existing columns untouched. Fill these four per row:

- `replacement_source_url` — public, citable, durable URL
- `replacement_value` — the date that source gives, `YYYY-MM-DD`
- `agrees_with_current` — `yes` / `no` / `partial`
- `replacement_source_type` — e.g. `exchange_notice`, `press_release`, `regulatory_filing`, `news_archive`

Put anything unresolved or ambiguous in `notes`. Do not edit `current_value`; a
disagreement is recorded via `agrees_with_current=no`, not by overwriting.

## The internal cross-check column

`internal_crosscheck_value` carries membership-episode dates from
`source_inputs/FTSE100_CANONICAL_DATABASE(...).csv` — an independent internal record,
present for 311 rows. Where both exist, 266 agree with the current value and 25 differ.

**It is not a publishable source** — its own provenance is a local archive path, not a
public URL. Treat it as a hypothesis to verify, and as the best lead for the 22 rows
where the date is missing entirely. Companies with several episodes list all of them,
semicolon-separated, because the spine collapses re-entries into a single row.

## Identity

`company_number` is the join key throughout. `companies_house_url` resolves each
company's registered name and history. 30 spine rows had no `company_name`; all but
one were backfilled from the canonical database.

## Blast radius if a date changes

`consolidated_rows_affected` gives the number of year-rows in
`FTSE100_consolidated.csv` carrying that company. Changing an entry or exit date
changes which years that company counts as a constituent, so it propagates into every
membership-derived aggregate — turnover, entrant classification, age-at-entry.
