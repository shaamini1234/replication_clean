#!/usr/bin/env python3
"""load_financial_filings.py — copy the full iXBRL parse into the DuckDB.

financial_filings is the raw iXBRL extraction (39.2M filing rows, ~45 financial
fields). It lives in local Postgres and was NOT in the DuckDB, so every analysis
run against the DuckDB was missing it — including `depreciation`, which the
firm-year panel does not carry at all and which GVA needs.

    GVA (income method) = staff_costs + operating_profit + depreciation

Run:
    python python/load_financial_filings.py            # load
    python python/load_financial_filings.py --check    # report only

Disk note: the Postgres table is ~22GB but is mostly NULL, and DuckDB stores it
columnar with compression, so the DuckDB footprint is far smaller. The loader
aborts if free disk drops below the floor below.
"""
from __future__ import annotations
import argparse, os, shutil, sys, time
from pathlib import Path
import duckdb

REPO = Path(__file__).resolve().parent.parent
DB = os.environ.get("BD_DUCKDB") or str(REPO / "database" / "business_dynamism_v2_20260824d.duckdb")
PG = os.environ.get("BD_PG", "dbname=business_dynamism")
MIN_FREE_GB = 5.0
TABLE = "financial_filings"


def free_gb(path: str) -> float:
    return shutil.disk_usage(Path(path).parent).free / 1e9


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report only, load nothing")
    args = ap.parse_args()

    print(f"duckdb : {DB}  ({os.path.getsize(DB)/1e9:.2f} GB)")
    print(f"free   : {free_gb(DB):.1f} GB  (floor {MIN_FREE_GB} GB)")
    if free_gb(DB) < MIN_FREE_GB:
        print("refusing to start: not enough free disk", file=sys.stderr)
        return 1

    con = duckdb.connect(DB)
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(f"ATTACH '{PG}' AS pg (TYPE postgres, READ_ONLY)")
    n_src = con.execute(f"select count(*) from pg.public.{TABLE}").fetchone()[0]
    print(f"source : pg.public.{TABLE}  {n_src:,} rows")

    if args.check:
        con.close(); return 0

    t0 = time.time()
    print("loading … (columnar + compressed; this takes a few minutes)")
    con.execute(f"CREATE OR REPLACE TABLE {TABLE} AS SELECT * FROM pg.public.{TABLE}")
    n_dst = con.execute(f"select count(*) from {TABLE}").fetchone()[0]
    con.execute("DETACH pg")
    con.close()

    print(f"\nloaded {n_dst:,} rows in {time.time()-t0:,.0f}s")
    print(f"duckdb now {os.path.getsize(DB)/1e9:.2f} GB, {free_gb(DB):.1f} GB free")
    if n_dst != n_src:
        print(f"ROW COUNT MISMATCH: source {n_src:,} vs loaded {n_dst:,}", file=sys.stderr)
        return 1
    print("row counts match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
