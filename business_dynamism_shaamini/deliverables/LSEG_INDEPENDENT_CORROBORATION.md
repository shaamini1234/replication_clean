# Independent corroboration of FTSE-sourced index dates

Companion to `lseg_independent_corroboration.csv`.

## Why this exists

Every index membership date in the dataset is sourced to FTSE Russell. The
replacement-sourcing pass found a public URL for that document, which makes the
data verifiable, but not an independent source — 418 of 421 rows still point at
one FTSE Russell PDF whose copyright page reserves all rights.

This file is the part of the dataset that can be evidenced without FTSE Russell
at all.

## What can and cannot be corroborated

Of 421 dated rows, 66 fall on a date the FTSE record annotates as a corporate
event. Those split in two:

- **30 exits** where the event names *this* company as acquired or merged. The
  acquisition is a matter of public record — SEC filings, RNS announcements, the
  acquirer's own press release — so the exit can be evidenced independently.
- **36 entries** where the corporate event belongs to a *different* company.
  Abbey National entered on 1989-07-17 because Gateway Corporation was acquired;
  the Gateway deal evidences a vacancy arising, not Abbey National filling it.
  These are **not** independently citable and are excluded.

The remaining 355 rows are ordinary quarterly-review changes with no external
event to point at. For those, FTSE Russell is the only source.

## The finding: corroboration bounds the date, it does not reproduce it

12 of the 30 are sourced here. Every one lands within 7 days of the FTSE date,
5 of them exactly — but the two dates are measuring different things:

| | |
|---|---|
| Exact match | 5 of 12 |
| Within 1 day | 7 of 12 |
| Within 7 days | 12 of 12 (max 6 days) |

FTSE removes a constituent on its own schedule around the corporate event, not
on the event date. Rexam left the index on 2016-06-27, three days *before* Ball
completed on 30 June. GKN left on 2018-04-24, five days *after* Melrose's offer
went unconditional on 19 April. Corus left on 2007-03-30, the date the court
confirmed the capital reduction, while the scheme was declared effective on
2 April.

So an independent source establishes that the company left the index, why, and
approximately when. The exact removal date remains FTSE Russell's determination
and cannot be derived from anything else.

## Method

For each of the 30, the FTSE record's own note names the counterparty
("Acquisition of Rexam by Ball Corp (USA)"). That was used to locate a primary
source for the event — in preference order: SEC filing, acquirer or target press
release, RNS announcement, contemporaneous news report. Each was read and its
date recorded, along with the offset from the FTSE date and what the difference
represents.

Companies House was checked for all 30 and is **not** usable as a source for the
exit date: after an acquisition the registered entity usually survives as a
subsidiary, so 27 of the 30 still show `active`. It does confirm identity — all
30 company numbers resolve to the expected registrant, including renames
(BAA → Heathrow Airport Holdings, Abbey National → Santander UK), which is a
useful independent check on the spine's company-number matching.

## Status

12 of 30 sourced. The remaining 18 are mechanical — the counterparty is named in
the FTSE note, and the pattern above holds — but each needs its source read and
its offset recorded rather than assumed.

## What this does and does not achieve

It does not solve the licensing question. 12 rows of 421 is a provenance
improvement, not independence: the dataset still rests on FTSE Russell, and for
the 355 quarterly-review rows and everything before 2000 there is no alternative.

It does mean the most consequential exits carry evidence a reader can check
without a licence, and it demonstrates the dataset's dates are consistent with
the independent public record.
