#!/usr/bin/env python3
"""Incremental builder for the single-file DB business_dynamism.duckdb.
Runs one chunk per invocation so no single step exceeds the sandbox timeout.
Usage: build_duckdb.py <stage>   where stage in:
   start | combined_firm_year | firm_year_panel | neon
"""
import os, sys, duckdb, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARQUET = os.path.join(BASE, "output", "v1_20260819")
DBFILE  = os.environ.get("BD_DUCKDB") or os.path.join(BASE, "database", "business_dynamism.duckdb")
NEON = "postgresql://neondb_owner:npg_q1uDNWofte0n@ep-nameless-fire-atkh5lxj.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require"
stage = sys.argv[1]

def pq(con, t):
    p = os.path.join(PARQUET, f"{t}.parquet")
    con.execute(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM read_parquet('{p}')")
    print(f"  {t:22s} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>12,}")

con = duckdb.connect(DBFILE)
if stage == "start":
    for t in ["firm_master","companies","exit_events"]:
        pq(con, t)
elif stage in ("combined_firm_year","firm_year_panel"):
    pq(con, stage)
elif stage == "neon":
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(f"ATTACH '{NEON}' AS neon (TYPE postgres, READ_ONLY);")
    for t in ["gazette_events","ch_company_profile","ftse100_membership","ftse100_fundamentals",
              "ftse100_compositions","ftse100_changes","ftse100_mapping",
              "sp500_financials","sp500_membership","sp500_companies_full"]:
        try:
            con.execute(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM neon.public.{t}")
            print(f"  {t:22s} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>12,}")
        except Exception as e:
            print(f"  {t}: SKIPPED ({str(e)[:60]})")
    con.execute("CREATE OR REPLACE TABLE _build_info(built_at TIMESTAMP, note VARCHAR)")
    con.execute("INSERT INTO _build_info VALUES (?, ?)",
        [datetime.datetime.now(), "spine from Parquet v1_20260819; market+crawl from Neon live"])
con.close()
print(f"stage '{stage}' done; file {round(os.path.getsize(DBFILE)/1e9,2)} GB")
