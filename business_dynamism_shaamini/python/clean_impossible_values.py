#!/usr/bin/env python3
"""clean_impossible_values.py — null values that cannot be true, keeping a record.

These are extraction defects, not filing errors: they are present in
financial_filings (the raw iXBRL parse) and flow from there into the firm-year
panel. Each rule below covers values that are impossible by definition, not
merely unusual, so nulling them removes noise without removing signal.

    employees < 0                impossible. 110,024 rows; the minimum is
                                 -813,269.
    employees > 600,000          impossible for a single UK-registered filer.
                                 The distribution runs p50=2, p99=55,
                                 p99.99=19,414, then jumps to a maximum of
                                 1,012,955,869 -- the tail is not a long tail,
                                 it is a different quantity. The ceiling sits
                                 above Compass Group (~500k worldwide), the
                                 largest UK-headquartered employer, so no real
                                 filer is excluded.
    total_assets < 0             impossible. Total assets is a balance-sheet
                                 total and cannot be negative; net assets can.
                                 38.5% of rows have total_assets == net_assets,
                                 so the extractor is falling back to net assets
                                 where total assets is untagged -- common in
                                 FRS 105 micro-entity accounts, which often
                                 present only net assets. The negative ones are
                                 that fallback showing through.

                                 The value is RECOVERED, not discarded. Of the
                                 4.57M affected rows, 1.21M have no net_assets:
                                 for those the figure is moved there first,
                                 because it IS the net assets. 2.01M already
                                 carry the identical value in net_assets, so
                                 nothing is lost. The remaining 1.34M hold a
                                 different net_assets value, so the negative
                                 total_assets is simply wrong and is dropped.
    turnover < 0                 impossible. 467 rows, down to -800,000,000;
                                 the iXBRL sign attribute misapplied.

Nothing is deleted. Every value nulled is first copied to
``data_quality_corrections`` with the company, period, field, original value
and reason, so the decision is auditable and reversible.

Usage:
    python python/clean_impossible_values.py --dry-run
    python python/clean_impossible_values.py
    python python/clean_impossible_values.py --skip-postgres
"""
from __future__ import annotations
import argparse, os, subprocess, sys
from pathlib import Path
import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
PG = os.environ.get("BD_PG_DSN", "business_dynamism")
MAX_EMPLOYEES = 600_000

RULES = [
    ("employees",    f"employees < 0",                  "negative employee count"),
    ("employees",    f"employees > {MAX_EMPLOYEES}",    f"employee count above {MAX_EMPLOYEES:,}, impossible for a UK filer"),
    ("total_assets", "total_assets < 0",                "negative total assets (net-assets fallback showing through)"),
    ("turnover",     "turnover < 0",                    "negative turnover (iXBRL sign attribute misapplied)"),
]
TABLES = ("financial_filings", "combined_firm_year")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-postgres", action="store_true")
    args = ap.parse_args()
    con = duckdb.connect(DB, read_only=args.dry_run)

    total = 0
    print("rows that would be nulled:" if args.dry_run else "nulling impossible values:")
    for table in TABLES:
        cols = {r[0] for r in con.execute(
            "select column_name from information_schema.columns where table_name = ?", [table]).fetchall()}
        for field, cond, reason in RULES:
            if field not in cols:
                continue
            n = con.execute(f"select count(*) from {table} where {cond}").fetchone()[0]
            if not n:
                continue
            total += n
            print(f"  {table:22s} {field:14s} {n:>9,}  ({reason})")
            if args.dry_run:
                continue
            con.execute("""create table if not exists data_quality_corrections(
                             source_table varchar, company_number varchar, period_end date,
                             field varchar, original_value bigint, reason varchar,
                             corrected_on date)""")
            con.execute(f"""insert into data_quality_corrections
                            select '{table}', company_number, period_end, '{field}',
                                   try_cast({field} as bigint), '{reason}', current_date
                            from {table} where {cond}""")
            if field == "total_assets" and "net_assets" in cols:
                # the figure IS the net assets where none was captured; move it
                # there before clearing, so 1.2M real values survive
                moved = con.execute(
                    f"select count(*) from {table} where {cond} and net_assets is null"
                ).fetchone()[0]
                con.execute(f"update {table} set net_assets = total_assets "
                            f"where {cond} and net_assets is null")
                if moved:
                    print(f"  {'':22s} {'':14s} {moved:>9,}  of these recovered into net_assets")
            con.execute(f"update {table} set {field} = null where {cond}")

    if args.dry_run:
        print(f"\n--dry-run: {total:,} values would be nulled, nothing written")
        con.close(); return 0

    kept = con.execute("select count(*) from data_quality_corrections").fetchone()[0]
    print(f"\n  {total:,} values nulled; {kept:,} originals preserved in data_quality_corrections")
    con.close()

    if not args.skip_postgres:
        try:
            sql = ["create table if not exists data_quality_corrections("
                   "source_table varchar, company_number varchar, period_end date, field varchar,"
                   "original_value bigint, reason varchar, corrected_on date);"]
            for field, cond, reason in RULES:
                sql.append(f"insert into data_quality_corrections select 'financial_filings', "
                           f"company_number, period_end, '{field}', {field}::bigint, "
                           f"'{reason}', current_date from financial_filings where {cond};")
                if field == "total_assets":
                    sql.append("update financial_filings set net_assets = total_assets "
                               f"where {cond} and net_assets is null;")
                sql.append(f"update financial_filings set {field} = null where {cond};")
            r = subprocess.run(["psql", PG, "-tA", "-v", "ON_ERROR_STOP=1", "-f", "-"],
                               input="\n".join(sql), capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip()[:200])
            print("  postgres financial_filings: same rules applied")
        except Exception as e:
            print(f"  WARNING: Postgres not updated ({e}). DuckDB and Postgres now differ.",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
