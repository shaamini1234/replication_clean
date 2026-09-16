#!/usr/bin/env python3
"""flag_implausible_filings.py — mark filings no UK company could have made.

Why this is narrow
------------------
The obvious screen -- revenue per employee -- does NOT work here. 551 filings
report over £20m of turnover per employee, but 325 of the 375 that can be
checked are CONSISTENT with the same company's other years. Holding companies,
LLPs and commodity-trading vehicles genuinely run enormous turnover through very
few staff, and `employees` is often the filing entity's headcount while turnover
is group-level. Screening on that ratio would delete hundreds of legitimate
filings.

The iXBRL is not at fault either. The parse was checked against the source
documents: PARAGLIDE's accounts carry

    <ix:nonFraction name="core:TurnoverRevenue" scale="3" ...>540,267,965</ix:nonFraction>

and per the Inline XBRL 1.1 specification the reported value is the displayed
figure multiplied by 10^scale, so 540,267,965,000 is what the filing says. The
extractor applied `scale` correctly; re-parsing reproduces the same number.

What is left is a small number of filings that are simply false. All three
companies below share a profile: a generic SIC code, one anomalous filing with
no other year to corroborate it, and wildly inconsistent employee counts across
years -- the signature of a bogus filing rather than a measurement error.

    08205603  PARAGLIDE LIMITED          £540.3bn   SIC 82990
    11317999  COMPANY PETROMARUZ LIMITED £191.4bn   SIC 82990
    14067976  AVANTULO S.A LIMITED        £26.0bn   SIC 70229  (dissolved)

For scale, Shell plc -- the largest UK-listed company -- reports around £250bn.

The rule
--------
A turnover figure is flagged when BOTH hold:

  1. it exceeds CEILING (£25bn), which no filer in this dataset legitimately
     reaches -- the genuine UK giants do not appear here with tagged turnover; and
  2. the same company has no other filing whose turnover is within a factor of
     TOLERANCE, so nothing in its own history supports the figure.

The flag covers the WHOLE filing, not the turnover line alone. Every monetary
figure in these returns is false on the same scale -- PARAGLIDE reports staff
costs of £239.6bn and an operating loss of £354.4bn, and all three filings are
GVA-computable, so firm_gva is contaminated unless they are excluded too.

Rows are FLAGGED, never deleted, so the decision stays visible and reversible.

The flagged monetary values are then NULLED. Flagging alone left every false
figure in place and made correctness depend on each consumer remembering to
filter -- which is how PARAGLIDE's GBP 540bn reached a GVA total in the first
place. There is nothing to correct them to: each of the three companies has
exactly one filing carrying turnover, so no other year exists to recover a true
value from, and the figure is not a scale error but a false return. Originals go
to data_quality_corrections first, so nothing is lost and the decision can be
reversed. employees is left alone -- it is flagged, and 13,060 is not itself
impossible.

Both stores are flagged. sql/12_gva.sql runs against local Postgres while the
analysis scripts read DuckDB, so a flag present in only one of them leaves the
other silently contaminated -- and, worse, makes 12_gva.sql reference a column
that does not exist there.

Usage:
    python python/flag_implausible_filings.py --dry-run
    python python/flag_implausible_filings.py
    python python/flag_implausible_filings.py --skip-postgres
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
CEILING = 2.5e10      # £25bn
TOLERANCE = 10.0      # another year within 10x counts as corroboration
TABLES = ("financial_filings", "combined_firm_year")


def suspects(con, table: str):
    return con.execute(f"""
        with big as (
          select company_number, period_end, turnover from {table}
          where turnover is not null and turnover > {CEILING}),
        corroborated as (
          select b.company_number, b.period_end
          from big b join {table} f
            on f.company_number = b.company_number
           and f.period_end is distinct from b.period_end
           and f.turnover is not null
           and f.turnover between b.turnover / {TOLERANCE} and b.turnover * {TOLERANCE})
        select b.company_number, cast(b.period_end as varchar), b.turnover
        from big b
        where not exists (select 1 from corroborated c
                          where c.company_number = b.company_number
                            and c.period_end is not distinct from b.period_end)
        order by b.turnover desc
    """).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-postgres", action="store_true",
                    help="flag DuckDB only (use when local Postgres is unavailable)")
    args = ap.parse_args()
    con = duckdb.connect(DB, read_only=args.dry_run)

    total = 0
    for t in TABLES:
        cols = {r[0] for r in con.execute(
            "select column_name from information_schema.columns where table_name = ?", [t]).fetchall()}
        if "turnover" not in cols or "period_end" not in cols:
            print(f"  {t}: no turnover/period_end column, skipped"); continue
        s = suspects(con, t)
        total += len(s)
        print(f"\n{t}: {len(s)} filing(s) flagged")
        for cn, pe, v in s:
            print(f"    {cn:12s} {pe}  £{v/1e9:,.1f}bn")
        if args.dry_run or not s:
            continue
        if "filing_suspect" not in cols:
            con.execute(f"alter table {t} add column filing_suspect BOOLEAN")
            con.execute(f"alter table {t} add column filing_suspect_reason VARCHAR")
        for cn, pe, _ in s:
            con.execute(
                f"update {t} set filing_suspect = true, filing_suspect_reason = "
                f"'turnover above £{CEILING/1e9:.0f}bn with no corroborating filing from the same company; every monetary figure in the filing is unreliable' "
                f"where company_number = ? and cast(period_end as varchar) = ?", [cn, pe])

    if not args.dry_run and not args.skip_postgres:
        _flag_postgres()

    if not args.dry_run:
        _null_flagged(duckdb.connect(DB, read_only=False))

    if args.dry_run:
        print("\n--dry-run: nothing written")
    else:
        print(f"\nflagged {total} filing(s) across {len(TABLES)} tables; no rows deleted")
        print("consumers should filter on `filing_suspect is not true`")
    con.close()
    return 0


MONEY = ("turnover", "staff_costs", "operating_profit", "depreciation", "gross_profit",
         "total_assets", "net_assets", "profit_loss")


def _null_flagged(con) -> None:
    """Null every monetary figure on a flagged filing, preserving the originals."""
    con.execute("""create table if not exists data_quality_corrections(
                     source_table varchar, company_number varchar, period_end date,
                     field varchar, original_value bigint, reason varchar, corrected_on date)""")
    total = 0
    for t in TABLES:
        cols = {r[0] for r in con.execute(
            "select column_name from information_schema.columns where table_name = ?", [t]).fetchall()}
        if "filing_suspect" not in cols:
            continue
        for f in MONEY:
            if f not in cols:
                continue
            n = con.execute(f"select count(*) from {t} where filing_suspect and {f} is not null").fetchone()[0]
            if not n:
                continue
            con.execute(f"""insert into data_quality_corrections
                            select '{t}', company_number, period_end, '{f}',
                                   try_cast({f} as bigint),
                                   'false filing: every monetary figure unreliable', current_date
                            from {t} where filing_suspect and {f} is not null""")
            con.execute(f"update {t} set {f} = null where filing_suspect")
            total += n
    print(f"  nulled {total} monetary values on flagged filings (originals preserved)")
    con.close()


def _flag_postgres() -> None:
    """Mirror the flag into local Postgres, where sql/12_gva.sql runs."""
    pg = os.environ.get("BD_PG_DSN", "dbname=business_dynamism")
    try:
        import subprocess
        def psql(sql: str) -> str:
            """Statements go in on stdin, not via -c.

            A multi-line statement passed to `psql -tAc` is mangled -- the
            UPDATE silently matched nothing and the script reported success
            while flagging zero rows. ON_ERROR_STOP makes a failure loud.
            """
            r = subprocess.run(["psql", pg.replace("dbname=", ""), "-tA",
                                "-v", "ON_ERROR_STOP=1", "-f", "-"],
                               input=sql, capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip()[:200])
            return r.stdout.strip()

        # DEFAULT false is metadata-only in Postgres 11+. A backfill UPDATE here
        # rewrites all 39M rows, holds an exclusive lock for minutes and blocks
        # every other query -- and buys nothing, because consumers read this
        # through COALESCE(filing_suspect, false).
        psql("alter table financial_filings "
             "add column if not exists filing_suspect boolean default false;")
        psql("alter table financial_filings "
             "add column if not exists filing_suspect_reason varchar;")
        # same rule, expressed once in SQL against the same data
        psql(f"""
            with big as (select company_number, period_end, turnover from financial_filings
                         where turnover is not null and turnover > {CEILING}),
                 corroborated as (
                   select b.company_number, b.period_end from big b join financial_filings f
                     on f.company_number = b.company_number
                    and f.period_end is distinct from b.period_end
                    and f.turnover is not null
                    and f.turnover between b.turnover / {TOLERANCE} and b.turnover * {TOLERANCE})
            update financial_filings t set filing_suspect = true,
                   filing_suspect_reason = 'turnover above GBP {CEILING/1e9:.0f}bn with no corroborating filing from the same company; every monetary figure in the filing is unreliable'
            from big b
            where t.company_number = b.company_number and t.period_end = b.period_end
              and not exists (select 1 from corroborated c
                              where c.company_number = b.company_number
                                and c.period_end is not distinct from b.period_end);""")
        n = psql("select count(*) from financial_filings where filing_suspect")
        print(f"\n  postgres financial_filings: {n} filing(s) flagged")
    except Exception as e:
        print(f"\n  WARNING: could not flag Postgres ({e}); sql/12_gva.sql will fail there "
              f"until this is applied. Re-run without --skip-postgres when it is reachable.",
              file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
