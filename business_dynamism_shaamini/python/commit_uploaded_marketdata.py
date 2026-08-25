#!/usr/bin/env python3
"""
commit_uploaded_marketdata.py — commit the two verified market-data files to Neon,
fill-where-null (never overwrite a good value), keeping every source URL.

Run by an agent WITH a working shell:
  pip install pandas psycopg2-binary
  # place the two CSVs in this folder first:
  #   FTSE_marketdata_handover_2026-08-24_completed_best_evidence.csv
  #   SP500_marketdata_filled_pre_bulk.csv
  python3 python/commit_uploaded_marketdata.py

Verified 2026-08-24:
  * FTSE file  -> ftse100_compositions   (few sourced cells; fill-where-null; the file's
                 "audit-correction" blanks are legal-entity pedantry and are IGNORED —
                 blank cells never overwrite existing values under COALESCE anyway).
  * S&P file   -> sp500_financials        (HIGH VALUE: pre-2009 market cap + shares from
                 SEC 10-Ks and a market-cap history source; employees from 10-Ks).
  * Founding   -> already committed as Neon table `sp500_founding`; DO NOT push holdco
                 dates as founding. Nothing to do here for founding.
"""
import glob, os, sys, pandas as pd, numpy as np, psycopg2, psycopg2.extras
NEON="postgresql://neondb_owner:npg_q1uDNWofte0n@ep-nameless-fire-atkh5lxj.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require"
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def num(x):
    v=pd.to_numeric(x,errors="coerce"); return None if pd.isna(v) else (int(v) if float(v).is_integer() else float(v))
def s(x): return None if (x is None or (isinstance(x,float) and pd.isna(x)) or str(x).strip()=="") else str(x)
c=psycopg2.connect(NEON); c.autocommit=True; cur=c.cursor()

# ---------- FTSE -> ftse100_compositions ----------
fp=glob.glob(os.path.join(HERE,"source_inputs","FTSE_marketdata_handover*best_evidence.csv"))
if fp:
    d=pd.read_csv(fp[0])
    for col in ["price_source_url","marketcap_source_url","dividend_source_url","shares_source_url"]:
        cur.execute(f"ALTER TABLE ftse100_compositions ADD COLUMN IF NOT EXISTS {col} text")
    n=0
    for _,r in d.iterrows():
        if pd.isna(r.get("company_number")) or pd.isna(r.get("year")): continue
        vals=[num(r.get("year_end_price_pence")),num(r.get("shares_outstanding")),num(r.get("market_cap_gbp")),num(r.get("annual_dividend_pence"))]
        if all(v is None for v in vals): continue          # skip fully-blank rows
        cur.execute("""UPDATE ftse100_compositions SET
            year_end_price_pence=COALESCE(year_end_price_pence,%s),
            shares_outstanding=COALESCE(shares_outstanding,%s),
            market_cap_gbp=COALESCE(market_cap_gbp,%s),
            annual_dividend_pence=COALESCE(annual_dividend_pence,%s),
            price_source_url=COALESCE(price_source_url,%s),
            shares_source_url=COALESCE(shares_source_url,%s),
            marketcap_source_url=COALESCE(marketcap_source_url,%s),
            dividend_source_url=COALESCE(dividend_source_url,%s)
          WHERE company_number=%s AND year=%s""",
          (vals[0],vals[1],vals[2],vals[3],s(r.get("price_source_url")),s(r.get("shares_source_url")),
           s(r.get("marketcap_source_url")),s(r.get("dividend_source_url")),str(r["company_number"]).strip(),int(r["year"])))
        n+=cur.rowcount
    print(f"FTSE ftse100_compositions rows touched: {n}")
else:
    print("FTSE file not found — skipped")

# ---------- S&P -> sp500_financials ----------
sp=glob.glob(os.path.join(HERE,"source_inputs","SP500_marketdata_filled_pre_bulk*.csv"))
if sp:
    d=pd.read_csv(sp[0])
    for col in ["marketcap_source_url","employees_source_url","shares_source_url"]:
        cur.execute(f"ALTER TABLE sp500_financials ADD COLUMN IF NOT EXISTS {col} text")
    n=0
    for _,r in d.iterrows():
        if pd.isna(r.get("symbol")) or pd.isna(r.get("fiscal_year")): continue
        mc=num(r.get("market_cap")); sh=num(r.get("shares_outstanding")); em=num(r.get("employees"))
        if mc is None and sh is None and em is None: continue
        cur.execute("""UPDATE sp500_financials SET
            market_cap=COALESCE(market_cap,%s),
            shares_outstanding=COALESCE(shares_outstanding,%s),
            employees=COALESCE(employees,%s),
            marketcap_source_url=COALESCE(marketcap_source_url,%s),
            shares_source_url=COALESCE(shares_source_url,%s),
            employees_source_url=COALESCE(employees_source_url,%s)
          WHERE symbol=%s AND fiscal_year=%s""",
          (mc,sh,em,s(r.get("marketcap_source_url")),s(r.get("shares_source_url")),s(r.get("employees_source_url")),
           str(r["symbol"]).strip(),int(r["fiscal_year"])))
        n+=cur.rowcount
    print(f"S&P sp500_financials rows touched: {n}")
else:
    print("S&P file not found — skipped")

# ---------- S&P bulk (SEC shares + stooq market cap) -> sp500_financials ----------
bk=glob.glob(os.path.join(HERE,"source_inputs","sp500_shares_marketcap_bulk.csv"))
if bk:
    d=pd.read_csv(bk[0])
    for col in ["shares_source_url","marketcap_source_url"]:
        cur.execute(f"ALTER TABLE sp500_financials ADD COLUMN IF NOT EXISTS {col} text")
    n=0
    for _,r in d.iterrows():
        if pd.isna(r.get("symbol")) or pd.isna(r.get("fiscal_year")): continue
        sh=num(r.get("shares_outstanding")); mc=num(r.get("market_cap"))
        if sh is None and mc is None: continue
        cur.execute("""UPDATE sp500_financials SET
            shares_outstanding=COALESCE(shares_outstanding,%s),
            market_cap=COALESCE(market_cap,%s),
            shares_source_url=COALESCE(shares_source_url,%s),
            marketcap_source_url=COALESCE(marketcap_source_url,%s)
          WHERE symbol=%s AND fiscal_year=%s""",
          (sh,mc,s(r.get("shares_source_url")),s(r.get("marketcap_source_url")),
           str(r["symbol"]).strip(),int(r["fiscal_year"])))
        n+=cur.rowcount
    print(f"S&P bulk sp500_financials rows touched: {n}")
else:
    print("S&P bulk CSV not found — run bulk_sp500_fetch_to_csv.py first (or skip)")

# ---------- coverage after ----------
cur.execute("""SELECT
  round(100.0*count(market_cap)/count(*)) mcap, round(100.0*count(shares_outstanding)/count(*)) shares,
  round(100.0*count(employees)/count(*)) emp, count(*) FROM sp500_financials""")
print("S&P sp500_financials coverage now (market_cap%, shares%, employees%, rows):", cur.fetchone())
c.close()
print("\nDONE. These are in Neon. Fold into the DuckDB with build_duckdb.py / the sync step when ready.")
