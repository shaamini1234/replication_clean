#!/usr/bin/env python3
"""
Build one dedicated CSV per parameter, for FTSE and S&P, each with the join key +
the value + a source_url. Plus separate spine + birth files. Easy to navigate,
publish-ready. Re-runnable — refreshes from the central DuckDB whenever new agent
data has been committed.

Output tree:  deliverables/ftse/*.csv  and  deliverables/sp500/*.csv
Each parameter file contains ONLY rows where the value is present (so it's tidy).
"""
import os, duckdb, pandas as pd
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=[f for f in os.listdir(os.path.join(HERE,"database")) if f.startswith("business_dynamism_v2_") and f.endswith(".duckdb")]
DB=os.path.join(HERE, "database", sorted(DB)[-1])   # newest central DB
OUT=os.path.join(HERE,"deliverables")
os.makedirs(os.path.join(OUT,"ftse"),exist_ok=True); os.makedirs(os.path.join(OUT,"sp500"),exist_ok=True)
con=duckdb.connect(DB, read_only=True)
print("source DB:", os.path.basename(DB))

def dump(df, sub, name, valcol):
    df=df[df[valcol].notna()].copy()
    p=os.path.join(OUT,sub,name); df.to_csv(p,index=False)
    print(f"  {sub}/{name:34s} {len(df):>6} rows")

# ---------- FTSE financials (ftse100_fundamentals) ----------
ff=con.execute("SELECT company_number,ticker,fiscal_year,revenue,net_income,total_assets,currency,source_url FROM ftse100_fundamentals").fetchdf()
for col,fn in [("revenue","ftse_revenue.csv"),("net_income","ftse_net_income.csv"),("total_assets","ftse_total_assets.csv")]:
    d=ff[["company_number","ticker","fiscal_year",col,"currency","source_url"]].rename(columns={col:"value"})
    dump(d,"ftse",fn,"value")

# ---------- FTSE market data (ftse100_compositions) ----------
comp=con.execute("""SELECT company_number, name AS company_name, year,
   year_end_price_pence, price_source_url, annual_dividend_pence, dividend_source_url,
   market_cap_gbp, marketcap_source_url, shares_outstanding, shares_source_url
   FROM ftse100_compositions WHERE company_number IS NOT NULL""").fetchdf().drop_duplicates(["company_number","year"])
for val,url,fn in [("year_end_price_pence","price_source_url","ftse_share_price.csv"),
                   ("annual_dividend_pence","dividend_source_url","ftse_dividend.csv"),
                   ("market_cap_gbp","marketcap_source_url","ftse_market_cap.csv"),
                   ("shares_outstanding","shares_source_url","ftse_shares_outstanding.csv")]:
    d=comp[["company_number","company_name","year",val,url]].rename(columns={val:"value",url:"source_url"})
    dump(d,"ftse",fn,"value")

# ---------- FTSE spine + birth ----------
sp=con.execute("""SELECT DISTINCT company_number, company_name, ticker, former_names,
   ftse_entry_date, ftse_exit_date, incorporation_date, company_status, sic_1, region
   FROM ftse100_consolidated""").fetchdf().drop_duplicates("company_number")
sp.to_csv(os.path.join(OUT,"ftse","ftse_spine.csv"),index=False); print(f"  ftse/ftse_spine.csv                  {len(sp):>6} rows")
ba=con.execute("SELECT * FROM ftse_birth_audited").fetchdf()
ba.to_csv(os.path.join(OUT,"ftse","ftse_birth.csv"),index=False); print(f"  ftse/ftse_birth.csv                  {len(ba):>6} rows")

# ---------- S&P financials (sp500_financials) ----------
sf=con.execute("""SELECT symbol,cik,fiscal_year,revenue,revenue_source_url,net_income,net_income_source_url,
   total_assets,total_assets_source_url,market_cap,shares_outstanding,shares_source_url,employees
   FROM sp500_financials""").fetchdf().drop_duplicates(["symbol","fiscal_year"])
for val,url,fn in [("revenue","revenue_source_url","sp500_revenue.csv"),
                   ("net_income","net_income_source_url","sp500_net_income.csv"),
                   ("total_assets","total_assets_source_url","sp500_total_assets.csv"),
                   ("shares_outstanding","shares_source_url","sp500_shares_outstanding.csv")]:
    d=sf[["symbol","cik","fiscal_year",val,url]].rename(columns={val:"value",url:"source_url"})
    dump(d,"sp500",fn,"value")
# market cap + employees have no dedicated source_url column
for val,fn in [("market_cap","sp500_market_cap.csv"),("employees","sp500_employees.csv")]:
    d=sf[["symbol","cik","fiscal_year",val]].rename(columns={val:"value"}); d["source_url"]=""
    dump(d,"sp500",fn,"value")

# ---------- S&P spine + founding ----------
sps=con.execute("""SELECT symbol, company_name, cik, sector, sub_industry, hq, founded,
   sp_entry_date, sp_exit_date FROM sp500_consolidated""").fetchdf().drop_duplicates("symbol")
sps.to_csv(os.path.join(OUT,"sp500","sp500_spine.csv"),index=False); print(f"  sp500/sp500_spine.csv                {len(sps):>6} rows")
try:
    fnd=pd.read_csv(os.path.join(HERE,"deliverables","consolidated","sp500_company_founding.csv"))
    fnd.to_csv(os.path.join(OUT,"sp500","sp500_founding.csv"),index=False); print(f"  sp500/sp500_founding.csv             {len(fnd):>6} rows")
except Exception as e: print("  sp500_founding: skipped",e)

con.close()
# write a small index
idx=["# Deliverables — one CSV per parameter","",
     "## FTSE (deliverables/ftse/)","- financials: ftse_revenue, ftse_net_income, ftse_total_assets (company_number,ticker,fiscal_year,value,currency,source_url)",
     "- market: ftse_share_price, ftse_dividend, ftse_market_cap, ftse_shares_outstanding (company_number,company_name,year,value,source_url)",
     "- spine: ftse_spine (identity), ftse_birth (legal + operating birth, audited)","",
     "## S&P (deliverables/sp500/)","- financials: sp500_revenue, sp500_net_income, sp500_total_assets, sp500_shares_outstanding, sp500_market_cap, sp500_employees (symbol,cik,fiscal_year,value,source_url)",
     "- spine: sp500_spine (identity), sp500_founding (founding dates)","",
     "Each parameter file contains only rows where the value exists. Every value has a source_url where one is recorded.",
     "Rebuild: python3 python/build_parameter_csvs.py (reads the newest central DuckDB)."]
open(os.path.join(OUT,"README.md"),"w").write("\n".join(idx))
print("wrote deliverables/README.md")
