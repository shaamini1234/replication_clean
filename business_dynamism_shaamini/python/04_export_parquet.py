#!/usr/bin/env python3
"""
04_export_parquet.py — export the whole business_dynamism database to Parquet.
The portable, versioned analysis copy + backup (safe against Neon/credit loss).

Run locally (Postgres.app running):
    pip install duckdb        # one-time
    python3 04_export_parquet.py

Writes ../output/<version>/*.parquet. Bump VERSION for a new dated snapshot.
DuckDB reads Postgres and streams each table to Parquet — no giant in-memory load.
"""
import os
import datetime
import duckdb

PG_CONN = "dbname=business_dynamism host=/tmp"
VERSION = "v1_" + datetime.date.today().strftime("%Y%m%d")
# honor PARQUET_OUT from sync_and_rebuild.sh; else default to ../output/<version>
OUT = os.environ.get("PARQUET_OUT") or os.path.join(os.path.dirname(__file__), "..", "output", VERSION)

# core analysis tables + the reference/overlay tables
TABLES = [
    "firm_master",           # the spine: birth, death, financials, provenance
    "combined_firm_year",    # the cohesive firm-year panel
    "exit_events",           # insolvency/solvent exits collapsed per company
    "firm_year_panel",       # cleaned CH accounts panel (big)
    "companies",             # CH register snapshot (SIC, incorporation)
    "gazette_events",        # raw insolvency notices
    "ftse100_compositions",  # FTSE constituents + corrected market cap
    "ftse100_fundamentals",  # FTSE revenue/profit/assets (Yahoo, with currency)
    "ftse100_membership", "ftse100_mapping", "ftse100_changes",
    "sp500_financials",      # cleaned S&P financials
    "sp500_companies_full", "sp500_membership",
]

os.makedirs(OUT, exist_ok=True)
con = duckdb.connect()
con.execute("INSTALL postgres; LOAD postgres;")
con.execute(f"ATTACH '{PG_CONN}' AS pg (TYPE postgres, READ_ONLY);")

for t in TABLES:
    try:
        path = os.path.abspath(os.path.join(OUT, f"{t}.parquet"))
        con.execute(f"COPY (SELECT * FROM pg.public.{t}) TO '{path}' (FORMAT parquet);")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
        print(f"  {t}: {n:,} rows")
    except Exception as e:
        print(f"  {t}: SKIPPED ({str(e)[:70]})")

print(f"\ndone -> {os.path.abspath(OUT)}")
print("This folder is your portable dataset + backup. Copy it to Google Drive to be safe.")
