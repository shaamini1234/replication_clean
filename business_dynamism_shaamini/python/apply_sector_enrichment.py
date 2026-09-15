#!/usr/bin/env python3
"""apply_sector_enrichment.py — land the recovered EDGAR sectors in the database.

Reads ``source_inputs/sp500_edgar_sector_enrichment.csv`` (written by
``sp500_edgar_sector_fetch.py``), maps each SIC to the project's GICS sector
vocabulary via ``sic_gics_map``, and fills the gaps in DuckDB.

What it touches
---------------
``sp500_sector_enriched``   created/replaced — the durable record of what was
                            recovered, one row per symbol, with source URL.
``sp500_companies_full``    sector / sic / sic_description repaired.
``sp500_consolidated``      same, for the materialised panel the site reads.

A sector is repaired when it is NULL, or when it holds a value outside the
11-sector GICS vocabulary — the column carries a SIC description for ~143
symbols ("Crude Petroleum & Natural Gas" and the like), which every downstream
query silently drops because it filters on the vocabulary. A genuine GICS sector
is never overwritten.

Both tables gain a ``sector_basis`` column recording where each sector came
from: ``index_list_gics`` (the live constituent list — authoritative, never
overwritten), or one of the ``sic4`` / ``sic3`` / ``sic2`` / ``company_override``
bases from the mapping.

Values already holding a genuine GICS sector are NEVER overwritten, so the
script is idempotent and a second run is a no-op.

Join key
--------
CIK, never ticker. Tickers are reused after a delisting, so a ticker join
attaches one company's facts to another's — ``build_identity_crosswalk.py``
documents seven live cases in this data. That script must run first: it
normalises CIK to a single type across the tables and builds
``sp500_identity``, without which CIK joins silently match nothing.

Run order
---------
``build_duckdb.py neon`` re-imports ``sp500_companies_full`` from Neon and drops
the enrichment with it, so this script must run AFTER any such rebuild:

    python python/build_duckdb.py neon
    python python/build_identity_crosswalk.py     # <- CIK becomes joinable
    python python/sp500_edgar_sector_fetch.py
    python python/apply_sector_enrichment.py      # <- restores the enrichment
    python python/build_consolidated_csvs.py
    python python/build_site_data.py --verify

Usage:
    python python/apply_sector_enrichment.py           # apply
    python python/apply_sector_enrichment.py --dry-run # report, change nothing
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sic_gics_map import SECTORS, sic_to_gics  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
SRC = REPO / "source_inputs" / "sp500_edgar_sector_enrichment.csv"

TARGETS = ["sp500_companies_full", "sp500_consolidated"]


def ensure_column(con, table: str, col: str, decl: str) -> None:
    cols = {r[0] for r in con.execute(
        "select column_name from information_schema.columns where table_name = ?", [table]
    ).fetchall()}
    if col not in cols:
        con.execute(f"alter table {table} add column {col} {decl}")


def coverage(con, table: str) -> tuple[int, int]:
    """(symbols with a USABLE sector, symbols total).

    Usable means the value is one of the 11 GICS sectors — a SIC description
    sitting in the column counts as missing, because that is how every
    downstream query treats it.
    """
    vocab = "','".join(sorted(SECTORS))
    r = con.execute(
        f"select count(*), count(case when sector in ('{vocab}') then 1 end) from "
        f"(select symbol, max(sector) sector from {table} group by 1)"
    ).fetchone()
    return int(r[1]), int(r[0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    if not SRC.exists():
        print(f"missing {SRC} — run sp500_edgar_sector_fetch.py first", file=sys.stderr)
        return 1

    con = duckdb.connect(DB, read_only=args.dry_run)

    # ---- build the enrichment relation in memory, mapping SIC -> GICS --------
    raw = con.execute(
        f"select * from read_csv_auto('{SRC}', header=true, all_varchar=true)"
    ).fetchdf()
    print(f"enrichment source: {len(raw)} rows from {SRC.name}")

    resolved, bases = [], {}
    for _, r in raw.iterrows():
        sec, basis = sic_to_gics(r.get("sic"), r.get("symbol"))
        resolved.append(sec)
        bases[basis] = bases.get(basis, 0) + 1
    raw["sector_resolved"] = resolved
    raw["sector_basis"] = [sic_to_gics(r.get("sic"), r.get("symbol"))[1] for _, r in raw.iterrows()]

    got = sum(1 for s in resolved if s)
    print(f"  mapped to a GICS sector: {got}/{len(raw)}")
    for b, n in sorted(bases.items(), key=lambda x: -x[1]):
        print(f"    {b:20s} {n}")

    before = {t: coverage(con, t) for t in TARGETS}
    for t, (has, tot) in before.items():
        print(f"  before — {t}: {has}/{tot} symbols have a sector")

    if args.dry_run:
        print("\n--dry-run: no changes written")
        con.close()
        return 0

    # ---- durable record -----------------------------------------------------
    con.register("enrich_df", raw)
    con.execute("create or replace table sp500_sector_enriched as select * from enrich_df")
    con.unregister("enrich_df")
    n = con.execute("select count(*) from sp500_sector_enriched").fetchone()[0]
    print(f"\n  sp500_sector_enriched: {n} rows")

    # ---- fill the gaps ------------------------------------------------------
    for t in TARGETS:
        vocab = "','".join(sorted(SECTORS))
        ensure_column(con, t, "sector_basis", "VARCHAR")
        # Anything already holding a genuine GICS sector came from the index list.
        con.execute(
            f"update {t} set sector_basis = 'index_list_gics' "
            f"where sector in ('{vocab}') and sector_basis is null"
        )
        con.execute(f"""
            update {t} as tgt
            set sector = e.sector_resolved,
                sector_basis = e.sector_basis
            from sp500_sector_enriched as e
            where tgt.cik = e.cik
              and (tgt.sector is null or tgt.sector not in ('{vocab}'))
              and e.sector_resolved is not null
        """)
        # SIC travels with it where the table carries those columns and they're empty.
        cols = {r[0] for r in con.execute(
            "select column_name from information_schema.columns where table_name = ?", [t]
        ).fetchall()}
        if "sic" in cols:
            con.execute(f"""
                update {t} as tgt set sic = try_cast(e.sic as {'VARCHAR' if con.execute(
                    "select data_type from information_schema.columns "
                    "where table_name = ? and column_name = 'sic'", [t]
                ).fetchone()[0].upper().startswith('VARCHAR') else 'BIGINT'})
                from sp500_sector_enriched as e
                where tgt.cik = e.cik and tgt.sic is null and e.sic is not null and e.sic <> ''
            """)
        if "sic_description" in cols:
            con.execute(f"""
                update {t} as tgt set sic_description = e.sic_description
                from sp500_sector_enriched as e
                where tgt.cik = e.cik and tgt.sic_description is null
                  and e.sic_description is not null and e.sic_description <> ''
            """)

    print()
    for t in TARGETS:
        has, tot = coverage(con, t)
        was = before[t][0]
        print(f"  after  — {t}: {has}/{tot} symbols have a sector  (+{has - was})")

    print("\n  provenance breakdown (sp500_consolidated, per symbol):")
    for basis, cnt in con.execute(
        "select coalesce(sector_basis,'(none)'), count(*) from "
        "(select symbol, max(sector_basis) sector_basis from sp500_consolidated group by 1) "
        "group by 1 order by 2 desc"
    ).fetchall():
        print(f"    {basis:20s} {cnt}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
