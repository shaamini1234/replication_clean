#!/usr/bin/env python3
"""
build_source_workbooks.py — build two Excel workbooks, one tab per parameter, each tab
just the value + a source_url column (no notes / explanation text).

  ftse_sources.xlsx   : Revenue, Net_Income, Total_Assets, Market_Cap, Shares,
                        Share_Price, Dividend, Spine, Birth
  sp500_sources.xlsx  : Revenue, Net_Income, Total_Assets, Market_Cap, Shares,
                        Employees, Spine, Founding

Reads the local DuckDB (canonical) and overlays the staged CSVs fill-where-null, so the
workbooks reflect the about-to-be-committed state. Re-runnable — run again after the
morning commit / after the bulk fetch and the sheets refresh.

  pip install duckdb pandas openpyxl
  python3 python/build_source_workbooks.py
"""
import os, glob, duckdb, pandas as pd, numpy as np
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=sorted(glob.glob(os.path.join(HERE,"database","business_dynamism_v2_*.duckdb")))[-1]
con=duckdb.connect(DB, read_only=True)
def tbl(name):
    try: return con.execute(f"SELECT * FROM {name}").fetchdf()
    except Exception: return pd.DataFrame()
def col(df,c): return df[c] if c in df.columns else pd.Series([np.nan]*len(df))
def num(x): return pd.to_numeric(x,errors="coerce")

# ---- load ----
ff=tbl("ftse100_fundamentals"); comp=tbl("ftse100_compositions"); fc=tbl("ftse100_consolidated")
ba=tbl("ftse_birth_audited"); sf=tbl("sp500_financials"); spc=tbl("sp500_consolidated"); spf=tbl("sp500_founding")
con.close()

# ---- overlay staged CSVs (fill-where-null) ----
def load(pat):
    g=glob.glob(os.path.join(HERE,"source_inputs",pat)); return pd.read_csv(g[0]) if g else pd.DataFrame()
ftse_md=load("FTSE_marketdata_handover*best_evidence.csv")
sp_md=load("SP500_marketdata_filled_pre_bulk*.csv"); sp_bulk=load("sp500_shares_marketcap_bulk.csv")

if not comp.empty and not ftse_md.empty:
    comp=comp.copy(); comp["_k"]=comp.company_number.astype(str)+"|"+comp.year.astype(str)
    m=ftse_md.copy(); m["_k"]=m.company_number.astype(str)+"|"+m.year.astype(str); m=m.set_index("_k")
    for src,dst,su in [("year_end_price_pence","year_end_price_pence","price_source_url"),
                       ("shares_outstanding","shares_outstanding","shares_source_url"),
                       ("market_cap_gbp","market_cap_gbp","marketcap_source_url"),
                       ("annual_dividend_pence","annual_dividend_pence","dividend_source_url")]:
        comp[dst]=[comp.at[i,dst] if (dst in comp and pd.notna(comp.at[i,dst])) else m[src].get(k) for i,k in zip(comp.index,comp["_k"])]
        comp[su]=[ (comp.at[i,su] if (su in comp and pd.notna(comp.at[i,su])) else m[su].get(k)) for i,k in zip(comp.index,comp["_k"])]

def overlay_sp(sf, csv, cols):
    if sf.empty or csv.empty: return sf
    sf=sf.copy(); sf["_k"]=sf.symbol.astype(str)+"|"+sf.fiscal_year.astype(str)
    c=csv.copy(); c["_k"]=c.symbol.astype(str)+"|"+c.fiscal_year.astype(str); c=c.set_index("_k")
    for v,su in cols:
        if v in c:  sf[v]=[sf.at[i,v] if (v in sf and pd.notna(sf.at[i,v])) else c[v].get(k) for i,k in zip(sf.index,sf["_k"])]
        if su in c: sf[su]=[(sf.at[i,su] if (su in sf and pd.notna(sf.at[i,su])) else c[su].get(k)) for i,k in zip(sf.index,sf["_k"])]
    return sf
sf=overlay_sp(sf, sp_md, [("market_cap","marketcap_source_url"),("shares_outstanding","shares_source_url"),("employees","employees_source_url")])
sf=overlay_sp(sf, sp_bulk,[("market_cap","marketcap_source_url"),("shares_outstanding","shares_source_url")])

def sheet(df, keycols, val, url):
    d=pd.DataFrame({c:col(df,c) for c in keycols}); d[val]=col(df,val); d["source_url"]=col(df,url)
    d=d[num(d[val]).notna() | d[val].notna()]
    return d

# ================= FTSE workbook =================
fk=["company_number","ticker","fiscal_year"]; ck=["company_number","name","year"]
with pd.ExcelWriter(os.path.join(HERE,"deliverables","ftse_sources.xlsx"), engine="openpyxl") as xl:
    sheet(ff,fk+["currency"],"revenue","source_url").to_excel(xl,sheet_name="Revenue",index=False)
    sheet(ff,fk+["currency"],"net_income","source_url").to_excel(xl,sheet_name="Net_Income",index=False)
    sheet(ff,fk+["currency"],"total_assets","source_url").to_excel(xl,sheet_name="Total_Assets",index=False)
    sheet(comp,ck,"market_cap_gbp","marketcap_source_url").to_excel(xl,sheet_name="Market_Cap",index=False)
    sheet(comp,ck,"shares_outstanding","shares_source_url").to_excel(xl,sheet_name="Shares",index=False)
    sheet(comp,ck,"year_end_price_pence","price_source_url").to_excel(xl,sheet_name="Share_Price",index=False)
    sheet(comp,ck,"annual_dividend_pence","dividend_source_url").to_excel(xl,sheet_name="Dividend",index=False)
    fc[[c for c in ["company_number","company_name","ticker","former_names","ftse_entry_date","ftse_exit_date","sic_1","region","company_status"] if c in fc.columns]].drop_duplicates("company_number").to_excel(xl,sheet_name="Spine",index=False)
    ba[[c for c in ["company_number","company_name","legal_birth_year","legal_birth_date_exact","legal_birth_source_url","operating_birth_year","operating_birth_type","operating_birth_source_url"] if c in ba.columns]].to_excel(xl,sheet_name="Birth",index=False)
print("wrote ftse_sources.xlsx")

# ================= S&P workbook =================
sk=["symbol","cik","fiscal_year"]
with pd.ExcelWriter(os.path.join(HERE,"deliverables","sp500_sources.xlsx"), engine="openpyxl") as xl:
    sheet(sf,sk,"revenue","revenue_source_url").to_excel(xl,sheet_name="Revenue",index=False)
    sheet(sf,sk,"net_income","net_income_source_url").to_excel(xl,sheet_name="Net_Income",index=False)
    sheet(sf,sk,"total_assets","total_assets_source_url").to_excel(xl,sheet_name="Total_Assets",index=False)
    sheet(sf,sk,"market_cap","marketcap_source_url").to_excel(xl,sheet_name="Market_Cap",index=False)
    sheet(sf,sk,"shares_outstanding","shares_source_url").to_excel(xl,sheet_name="Shares",index=False)
    sheet(sf,sk,"employees","employees_source_url").to_excel(xl,sheet_name="Employees",index=False)
    spc[[c for c in ["symbol","cik","company_name","sector","sub_industry","hq","sp_entry_date","sp_exit_date"] if c in spc.columns]].drop_duplicates("symbol").to_excel(xl,sheet_name="Spine",index=False)
    spf[[c for c in ["symbol","cik","company_name","founded_year","founded_month","founded_source_url","legal_entity_founded_year","confidence"] if c in spf.columns]].to_excel(xl,sheet_name="Founding",index=False)
print("wrote sp500_sources.xlsx")
