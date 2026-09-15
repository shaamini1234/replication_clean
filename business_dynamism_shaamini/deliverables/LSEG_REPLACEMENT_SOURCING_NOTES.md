# LSEG replacement sourcing — results

Companion to `lseg_sourced_data_for_replacement_FILLED.csv` (422 rows; the orphan
spine row was dropped as instructed). All 421 substantive rows are resolved.

## The headline

The licensed April 2026 LSEG PDF has a **public successor**: FTSE Russell publishes the
same "FTSE 100 Historic Additions and Deletions" document (August 2026 edition, covering
19 Jan 1984 → 22 Jun 2026) as an open policy document on lseg.com:

- **URL:** https://www.lseg.com/content/dam/ftse-russell/en_us/documents/policy-documents/ftse-100-constituent-history.pdf
- **Wayback backup:** http://web.archive.org/web/20260511144758/https://www.lseg.com/content/dam/ftse-russell/en_us/documents/policy-documents/ftse-100-constituent-history.pdf (May 2026 capture, covers every date cited here)
- Suggested citation: *FTSE Russell (LSEG), FTSE 100 Historic Additions and Deletions, August 2026 (public PDF)*

So the replacement source is the index provider's own record — same data lineage as the
licensed PDF, but citable with a link. Every date was verified programmatically against
the document's parsed table (549 change events), not just assumed.

## Coverage

| Outcome | Rows | Meaning |
|---|---|---|
| `agrees_with_current = yes` | 375 | PDF confirms the exact date |
| `agrees = no` — launch placeholders | 18 | Spine has 1984-01-02 placeholder; PDF gives the real first entry (`replacement_value`) |
| `agrees = partial` — founders | 3 | Allied Domecq, Lloyds, M&S: original constituents; true launch was 3 Jan 1984 (CityAM retrospective) |
| blank `agrees` — date was missing | 22 | 13 filled from the PDF (crosscheck-confirmed); 9 resolved with a note (see below) |
| `agrees = no` — real disagreements | 3 | Wolseley, Whitbread, British Land (see below) |
| low-priority LSE history page | 1 | Left untouched per brief |

## Rows needing your judgement (all flagged in `notes`)

- **Wolseley exit 2013-06-24** — no such event exists in the provider record (exits:
  1998-06-22, 2000-03-20, 2009-03-23; lineage's final exit 2022-05-12 as Ferguson).
  The internal crosscheck agrees with the PDF, not the spine.
- **British Land exit 2025-12-22** — that date is actually a *re-entry* (WPP deleted).
  True exits: 1998-12-21, 2023-06-19, 2025-03-24; still a constituent.
- **Whitbread entry 1984-01-02** — this company number (04120344) is the post-2000
  entity; first entry 2002-12-23. The 1984 founding lineage is the separate
  Whitbread & Co. 'A' row.
- **Five "no exit exists" rows** — Lloyds Banking Group, NatWest Group (11785532),
  Granada plc, Intermediate Capital Group (14840880), Barratt Developments: each is
  (or its lineage is) still a constituent, or the crosscheck date is a rename/merger,
  not an index deletion. Recommend leaving those exits blank; details per row.
- **Berkeley Group** — collapsed episodes: 2015-09-21→2016-09-19 and
  2017-09-18→2026-06-22; filled with the crosscheck-consistent first episode.

## Quality notes

- The PDF itself contains typos ("Standard & Chartered", "Carlton Communication",
  "Intermediate Capital Grup", "B8M", "Reinshaw") and name-era variants (Billiton for
  BHP, Argyll Group for Safeway, O2 for mmO2, Invesco for Amvescap, RS Group for
  Electrocomponents…). Where the PDF's spelling differs from the spine's, the row's
  `notes` says what the PDF calls the company.
- 15 randomly sampled confirmations were independently re-checked against the raw PDF
  text: 15/15 passed.
- Blast radius: the three real disagreements + 18 placeholder corrections carry
  `consolidated_rows_affected` in the CSV — re-derive membership aggregates after you
  decide on those rows.
