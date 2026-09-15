#!/usr/bin/env python3
"""build_ftse_sector_crosswalk.py — key the FTSE sector classification on
company_number instead of ticker.

The problem
-----------
``source_inputs/ftse100_sector_classification.csv`` is keyed on ``code`` (the
ticker). Every sector query in ``build_site_data.py`` joins it to
``ftse100_compositions`` on that ticker. London tickers are reused, so the join
attaches one company's sector to another's index membership:

    RSA   -> 02339826, 00100097, AC000969   (three different companies)
    GAA   -> 00290076, 03106798, 03962410
    WPP   -> 02670617, 00899099
    FRAS  -> 06035106, 11775757

and the reverse — one company under several tickers — hides membership:

    02247735 -> BSY, SKY      00077536 -> REL, RELX
    04190816 -> BT.A, BT-A    15998687 -> BDEV, BTRW

Resolution
----------
The sector CSV carries ``first_year`` / ``last_year``, and
``ftse100_compositions`` carries ``code``, ``company_number`` and ``year``. A
ticker identifies a company unambiguously ONCE THE YEAR IS KNOWN, so the join is
``code`` AND year-overlap. Where a ticker covers one company only, the year adds
nothing and the match is unchanged; where it was reused, the year separates the
claimants.

Output
------
``source_inputs/ftse100_sector_classification_keyed.csv`` — the original columns
plus ``company_number``, ``match_basis`` and ``match_years``. Rows that cannot be
resolved keep a null company_number and are reported, never guessed.

Usage:
    python python/build_ftse_sector_crosswalk.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
SRC = REPO / "source_inputs" / "ftse100_sector_classification.csv"
OUT = REPO / "source_inputs" / "ftse100_sector_classification_keyed.csv"


def main() -> int:
    con = duckdb.connect(DB, read_only=True)

    rows = con.execute(f"""
        with sec as (
            select code, company_name, sector, basis,
                   try_cast(first_year as integer) fy,
                   try_cast(last_year  as integer) ly
            from read_csv_auto('{SRC}', header=true)
        ),
        -- every (code, company_number) pair the composition record supports,
        -- with the span of years it was observed over
        comp as (
            select code, company_number,
                   min(try_cast(year as integer)) y0,
                   max(try_cast(year as integer)) y1,
                   count(*) n_obs
            from ftse100_compositions
            where company_number is not null and code is not null
            group by 1, 2
        ),
        -- overlap between the sector row's span and the pairing's span
        j as (
            select sec.*, comp.company_number, comp.y0, comp.y1, comp.n_obs,
                   greatest(0, least(coalesce(sec.ly, comp.y1), comp.y1)
                             - greatest(coalesce(sec.fy, comp.y0), comp.y0) + 1) as overlap
            from sec left join comp on comp.code = sec.code
        ),
        -- best pairing per sector row: most year-overlap, then most observations
        ranked as (
            select *, row_number() over (
                       partition by code, coalesce(fy, -1)
                       order by overlap desc, n_obs desc, company_number
                     ) rn,
                   count(*) filter (where company_number is not null)
                       over (partition by code) as n_candidates
            from j
        )
        select code, company_name, sector, basis, fy, ly,
               company_number, overlap, n_candidates, y0, y1
        from ranked where rn = 1 order by code
    """).fetchall()
    con.close()

    out, unresolved, disambiguated = [], 0, 0
    for (code, name, sector, basis, fy, ly, cn, overlap, ncand, y0, y1) in rows:
        if cn is None:
            unresolved += 1
            mbasis = "unresolved_no_composition_record"
        elif (ncand or 0) > 1:
            disambiguated += 1
            mbasis = "code_plus_year_overlap" if overlap else "code_only_no_year_overlap"
        else:
            mbasis = "code_unique"
        out.append({
            "code": code, "company_name": name, "sector": sector, "basis": basis,
            "first_year": fy, "last_year": ly,
            "company_number": cn or "",
            "match_basis": mbasis,
            "match_years": f"{y0}-{y1}" if y0 is not None else "",
        })

    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    print(f"wrote {OUT.relative_to(REPO)}: {len(out)} rows")
    print(f"  resolved to a company_number : {len(out) - unresolved}")
    print(f"  of which needed the year to disambiguate a reused ticker: {disambiguated}")
    print(f"  unresolved (no composition record for the ticker): {unresolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
