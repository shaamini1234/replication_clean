#!/usr/bin/env python3
"""build_identity_crosswalk.py — make CIK the join key across the S&P tables.

The problem
-----------
Nothing in this project could join on CIK, because CIK was stored in four
different types across five tables:

    sp500_companies_full   VARCHAR  '0000315213'
    sp500_founding         BIGINT    1090872
    sp500_financials       VARCHAR  '0000004977'
    sp500_consolidated     DOUBLE    1090872.0
    sp500_sec_supplement   VARCHAR  '0000001800'

``'0000875570'``, ``875570`` and ``875570.0`` are the same company and none of
them join, so every merge in the pipeline fell back to the ticker. Tickers are
reused when a company delists and another takes the symbol, so ticker joins
silently attach one company's data to another's.

That is not hypothetical here. Seven symbols resolve to a different company in
``sp500_companies_full`` than in ``sp500_financials``:

    symbol   sp500_financials (correct)    sp500_companies_full (wrong)
    APC      Anadarko Petroleum            ARKO Petroleum
    CPWR     Compuware  (SIC 7372)         Ocean Thermal Energy (SIC 4931)
    EP       El Paso Corp                  Empire Petroleum
    MI       Marshall & Ilsley             NFT Ltd
    POM      Pepco Holdings                POMDOCTOR Ltd
    SE       Spectra Energy                Sea Ltd
    SII      Smith International           Sprott Inc.

``sp500_companies_full`` resolved each ticker against a PRESENT-DAY lookup, so
it returned whoever holds the symbol now rather than the historical constituent.
Compuware shows the cost: classified from the wrong CIK it becomes Utilities
instead of Information Technology.

What this script does
---------------------
1. Normalises ``cik`` to the SEC canonical form — 10-digit zero-padded VARCHAR —
   in every table that carries one, so CIK joins actually work.
2. Builds ``sp500_identity``: one row per symbol with the resolved CIK, the
   source it came from, and a flag where sources disagreed.
3. Adds ``cik`` to ``sp500_membership``, which had ticker as its only key.

Source precedence for symbol -> CIK
-----------------------------------
``sp500_manual_cik_resolution.csv`` > ``sp500_financials`` > ``sp500_founding``
> ``sp500_companies_full``.
Financials wins because its CIK was used to pull actual SEC filings, so it is
tied to the company whose numbers are in the panel. It is correct on all seven
conflicts above.

Usage:
    python python/build_identity_crosswalk.py            # apply
    python python/build_identity_crosswalk.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
# Hand-resolved symbol -> CIK for companies no project table carries, each row
# citing the EDGAR record it came from. Highest precedence: a human checked it.
MANUAL = REPO / "source_inputs" / "sp500_manual_cik_resolution.csv"

# Every table carrying a CIK, and whether it also carries a symbol.
CIK_TABLES = {
    "sp500_companies_full": "symbol",
    "sp500_founding": "symbol",
    "sp500_financials": "symbol",
    "sp500_consolidated": "symbol",
    "sp500_sec_supplement": None,
}

# Canonicalise whatever type CIK is currently stored as to '##########'.
# try_cast via DOUBLE first so '875570.0' and 875570.0 both survive.
NORM = "lpad(cast(try_cast(try_cast({c} as double) as bigint) as varchar), 10, '0')"


def columns(con, table: str) -> set[str]:
    return {r[0] for r in con.execute(
        "select column_name from information_schema.columns where table_name = ?", [table]
    ).fetchall()}


def normalise_cik(con, table: str) -> str:
    """Rewrite table.cik to 10-digit zero-padded VARCHAR. Returns the old type."""
    old = con.execute(
        "select data_type from information_schema.columns "
        "where table_name = ? and column_name = 'cik'", [table]
    ).fetchone()[0]
    con.execute(
        f"alter table {table} alter column cik set data type varchar "
        f"using case when cik is null then null else {NORM.format(c='cik')} end"
    )
    return old


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    con = duckdb.connect(DB, read_only=args.dry_run)

    print("== CIK types before ==")
    for t in CIK_TABLES:
        dt = con.execute(
            "select data_type from information_schema.columns "
            "where table_name = ? and column_name = 'cik'", [t]
        ).fetchone()
        print(f"  {t:24s} {dt[0] if dt else '(no cik column)'}")

    # ---- conflicts, reported whether or not we write -------------------------
    conflicts = con.execute(f"""
        with fin as (select symbol, max({NORM.format(c='cik')}) cik from sp500_financials
                     where cik is not null group by 1),
             fo  as (select symbol, max({NORM.format(c='cik')}) cik from sp500_founding
                     where cik is not null group by 1),
             cf  as (select symbol, max({NORM.format(c='cik')}) cik from sp500_companies_full
                     where cik is not null group by 1)
        select coalesce(fin.symbol, fo.symbol, cf.symbol) symbol,
               fin.cik, fo.cik, cf.cik
        from fin full join fo using(symbol) full join cf using(symbol)
        where (fin.cik is not null and fo.cik is not null and fin.cik <> fo.cik)
           or (fin.cik is not null and cf.cik is not null and fin.cik <> cf.cik)
        order by 1
    """).fetchall()
    print(f"\n== symbol -> CIK conflicts between sources: {len(conflicts)} ==")
    for sym, a, b, c_ in conflicts:
        print(f"  {sym:6s} financials={a}  founding={b}  companies_full={c_}  -> taking financials")

    if args.dry_run:
        print("\n--dry-run: no changes written")
        con.close()
        return 0

    # ---- 1. normalise every cik column --------------------------------------
    print("\n== normalising CIK to 10-digit zero-padded VARCHAR ==")
    for t in CIK_TABLES:
        if "cik" in columns(con, t):
            old = normalise_cik(con, t)
            print(f"  {t:24s} {old} -> VARCHAR(10)")

    # ---- 2. canonical crosswalk ---------------------------------------------
    con.execute(f"""
        create or replace table sp500_identity as
        with fin as (select symbol, max(cik) cik from sp500_financials where cik is not null group by 1),
             fo  as (select symbol, max(cik) cik from sp500_founding   where cik is not null group by 1),
             cf  as (select symbol, max(cik) cik from sp500_companies_full where cik is not null group by 1),
             nm  as (select symbol, max(company_name) nm from sp500_founding where company_name is not null group by 1),
             nm2 as (select symbol, max(security) nm from sp500_companies_full where security is not null group by 1),
             mn  as (select symbol, lpad(cast(try_cast(cik as bigint) as varchar), 10, '0') cik,
                            company_name nm
                     from read_csv_auto('{MANUAL}', header=true, all_varchar=true)),
             syms as (select distinct ticker symbol from sp500_membership
                      union select distinct symbol from sp500_companies_full where symbol is not null
                      union select distinct symbol from sp500_financials where symbol is not null)
        select s.symbol,
               coalesce(mn.cik, fin.cik, fo.cik, cf.cik)               as cik,
               case when mn.cik  is not null then 'manual_verified'
                    when fin.cik is not null then 'sp500_financials'
                    when fo.cik  is not null then 'sp500_founding'
                    when cf.cik  is not null then 'sp500_companies_full'
                    else null end                                      as cik_source,
               (fin.cik is not null and (
                    (fo.cik is not null and fo.cik <> fin.cik) or
                    (cf.cik is not null and cf.cik <> fin.cik)))        as had_conflict,
               coalesce(mn.nm, nm.nm, nm2.nm)                          as company_name
        from syms s
        left join mn  on mn.symbol  = s.symbol
        left join fin on fin.symbol = s.symbol
        left join fo  on fo.symbol  = s.symbol
        left join cf  on cf.symbol  = s.symbol
        left join nm  on nm.symbol  = s.symbol
        left join nm2 on nm2.symbol = s.symbol
    """)
    tot, res, conf = con.execute(
        "select count(*), count(cik), count(case when had_conflict then 1 end) from sp500_identity"
    ).fetchone()
    print(f"\n== sp500_identity: {tot} symbols, {res} resolved to a CIK, "
          f"{tot - res} unresolved, {conf} where sources disagreed ==")
    for src, n in con.execute(
        "select coalesce(cik_source,'(unresolved)'), count(*) from sp500_identity group by 1 order by 2 desc"
    ).fetchall():
        print(f"    {src:24s} {n}")

    # ---- 3. give sp500_membership a stable key ------------------------------
    if "cik" not in columns(con, "sp500_membership"):
        con.execute("alter table sp500_membership add column cik VARCHAR")
    con.execute("""
        update sp500_membership as m set cik = i.cik
        from sp500_identity as i where i.symbol = m.ticker and i.cik is not null
    """)
    n, k = con.execute(
        "select count(*), count(cik) from sp500_membership"
    ).fetchone()
    print(f"\n== sp500_membership: {k}/{n} rows now carry a CIK ==")

    # ---- 4. repair conflicted CIKs, then backfill the missing ones ----------
    # Repair first: where sources disagreed, sp500_identity holds the filing-derived
    # CIK and the table may hold the ticker-lookup one.
    for t in ("sp500_companies_full", "sp500_consolidated", "sp500_founding"):
        con.execute(f"""
            update {t} as tgt set cik = i.cik
            from sp500_identity as i
            where i.symbol = tgt.symbol and i.had_conflict and i.cik is not null
              and tgt.cik is distinct from i.cik
        """)
    print("\n== conflicted CIKs repaired in companies_full / consolidated / founding ==")

    # Backfill: a CIK join only works if the CIK is actually present. Symbol is
    # used HERE, once, to populate the stable key — after this every downstream
    # join uses CIK.
    print("== backfilling missing CIKs from sp500_identity ==")
    for t in ("sp500_companies_full", "sp500_consolidated", "sp500_founding", "sp500_financials"):
        before = con.execute(
            f"select count(cik) from (select symbol, max(cik) cik from {t} group by 1)"
        ).fetchone()[0]
        con.execute(f"""
            update {t} as tgt set cik = i.cik
            from sp500_identity as i
            where i.symbol = tgt.symbol and tgt.cik is null and i.cik is not null
        """)
        after, tot = con.execute(
            f"select count(cik), count(*) from (select symbol, max(cik) cik from {t} group by 1)"
        ).fetchone()
        print(f"    {t:24s} {before} -> {after} / {tot} symbols carry a CIK")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
