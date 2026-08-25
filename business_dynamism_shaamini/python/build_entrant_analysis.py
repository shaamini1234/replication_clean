#!/usr/bin/env python3
"""
First-pass "genuinely new at index entry" classifier for FTSE 100 & S&P 500.

Index entry != company birth. This buckets each *first-time* entrant by how old the
underlying business was at entry and whether the entry vehicle looks like a wrapper /
reincorporation / re-entry, using only data we hold. It is a PROVISIONAL, rule-based
pass — ambiguous cases are flagged for source-based adjudication, never guessed.

Outputs (in combined_dataset/):
  ftse_entrants_classified.csv, sp500_entrants_classified.csv, entrant_trend_summary.csv

Definitions / flags:
  age_at_entry = entry_year - founding_year   (FTSE: CH incorporation; S&P: 'founded' business year)
  founding_member : entered at the index series start (left-censored — can't be called 'new')
  re_entry        : company has >1 membership episode (was in before)
  has_former_names/renamed : predecessor names exist -> not a fresh business
  holdco/inv_trust: SIC/category signals a holding company or investment trust vehicle
  provisional_class:
    founding_member | re_entry | very_new_or_wrapper(<=3y) |
    genuinely_new_provisional(<=NEW_MAX y, clean) | new_entity_renamed(adjudicate) |
    established(older) | unknown_age
"""
import os, re, duckdb, pandas as pd, numpy as np
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=os.path.join(HERE,"business_dynamism_v2_20260820.duckdb")
NEW_MAX=12          # business younger than this at entry = candidate "genuinely new"
VERY_NEW=3          # younger than this yet index-sized = wrapper/spin-off/hypergrowth (adjudicate)
con=duckdb.connect(DB, read_only=True)

def yr(x):
    if pd.isna(x): return np.nan
    s=str(x)
    m=re.search(r"(\d{4})", s)
    return int(m.group(1)) if m else np.nan

# ============================== FTSE ==============================
mem=con.execute("SELECT company_number,company_name,start_date FROM ftse100_membership "
                "WHERE company_number IS NOT NULL").fetchdf()
mem["entry_year"]=mem["start_date"].map(yr)
ep=mem.groupby("company_number").size().rename("episodes")
first=mem.sort_values("start_date").groupby("company_number").agg(
    company_name=("company_name","first"), entry_date=("start_date","min"),
    entry_year=("entry_year","min")).join(ep)
info=con.execute("""SELECT DISTINCT company_number, incorporation_date, company_category, sic_1, former_names
    FROM ftse100_consolidated""").fetchdf().drop_duplicates("company_number").set_index("company_number")
f=first.join(info)
f["incorp_year"]=f["incorporation_date"].map(yr)
f["age_at_entry"]=f["entry_year"]-f["incorp_year"]
INDEX_START=1984
def sic_flag(row):
    s=str(row.get("sic_1") or "").lower(); c=str(row.get("company_category") or "").lower()
    holdco = ("holding" in s) or ("holding" in c) or bool(re.match(r"^\s*(64209|70100)", s))
    inv_trust = ("investment trust" in s) or bool(re.match(r"^\s*(643|649)", s)) or ("investment trust" in str(row.get("company_name") or "").lower())
    return pd.Series({"holdco":holdco,"inv_trust":inv_trust})
f=f.join(f.apply(sic_flag, axis=1))
f["re_entry"]=f["episodes"]>1
f["has_former_names"]=f["former_names"].notna()
def classify_ftse(r):
    if pd.notna(r["entry_year"]) and r["entry_year"]<=INDEX_START:
        return "founding_member"          # left-censored
    if pd.isna(r["age_at_entry"]): return "unknown_age"
    a=r["age_at_entry"]
    # entered BEFORE the matched entity was incorporated => wrong/reused company-number
    # match, not a real firm. A data-quality flag, NOT a wrapper.
    if a < 0: return "historical_unmatched"
    if r["re_entry"]: return "re_entry"
    if a<=VERY_NEW:                          # index-sized within <=3y of incorporation
        return "wrapper_reincorp" if (r["has_former_names"] or r["holdco"]) else "very_new_adjudicate"
    if a<=NEW_MAX:  return "new_entity_renamed" if r["has_former_names"] else "genuinely_new_provisional"
    return "established"
f["provisional_class"]=f.apply(classify_ftse, axis=1)
# null the bogus incorporation/age for wrong-namesake matches; flag so it's filterable
bad=f["provisional_class"]=="historical_unmatched"
f.loc[bad,["incorp_year","age_at_entry"]]=np.nan
f["ch_match_status"]=np.where(bad,"historical_no_reliable_ch_number","ok")
f["wrapper_suspect"]=(f["age_at_entry"]<=5)&(f["has_former_names"]|f["holdco"])
f["index"]="FTSE100"
f=f.reset_index().rename(columns={"company_number":"id"})
fcols=["index","id","company_name","entry_date","entry_year","incorp_year","age_at_entry",
       "episodes","re_entry","has_former_names","holdco","inv_trust","wrapper_suspect",
       "ch_match_status","company_category","sic_1","former_names","provisional_class"]
f[fcols].to_csv(os.path.join(HERE,"ftse_entrants_classified.csv"), index=False)

# ============================== S&P ==============================
spm=con.execute("SELECT ticker,start_date FROM sp500_membership").fetchdf()
spm["entry_year"]=spm["start_date"].map(yr)
spep=spm.groupby("ticker").size().rename("episodes")
spf=spm.sort_values("start_date").groupby("ticker").agg(
    entry_date=("start_date","min"), entry_year=("entry_year","min")).join(spep)
comp=con.execute("SELECT symbol,security,founded,date_added,sic,sub_industry FROM sp500_companies_full").fetchdf().drop_duplicates("symbol").set_index("symbol")
s=spf.join(comp)
s["founded_year"]=s["founded"].map(yr)
s["age_at_entry"]=s["entry_year"]-s["founded_year"]
SP_START=int(np.nanmin(s["entry_year"])) if s["entry_year"].notna().any() else 1957
s["re_entry"]=s["episodes"]>1
s["spac_shell"]=s["sic"].astype(str).str.match(r"^677")
def classify_sp(r):
    if pd.notna(r["entry_year"]) and r["entry_year"]<=SP_START:
        return "founding_member"
    if r["spac_shell"]: return "spac_shell"
    if pd.isna(r["age_at_entry"]): return "unknown_age"
    a=r["age_at_entry"]
    if a < 0: return "historical_unmatched"
    if r["re_entry"]: return "re_entry"
    if a<=VERY_NEW: return "very_new_adjudicate"
    if a<=NEW_MAX:  return "genuinely_new_provisional"
    return "established"
s["provisional_class"]=s.apply(classify_sp, axis=1)
s["index"]="S&P500"
s=s.reset_index().rename(columns={"ticker":"id","security":"company_name"})
scols=["index","id","company_name","entry_date","entry_year","founded_year","age_at_entry",
       "episodes","re_entry","spac_shell","sic","sub_industry","provisional_class"]
s[scols].to_csv(os.path.join(HERE,"sp500_entrants_classified.csv"), index=False)

# ============================== trend summary ==============================
def trend(df, idx):
    d=df[(df["provisional_class"]!="founding_member")&(df["provisional_class"]!="unknown_age")].copy()
    d=d[d["entry_year"].notna()]
    d["window"]=(d["entry_year"]//5*5).astype(int)
    d["is_new"]=d["provisional_class"].isin(["genuinely_new_provisional"])
    g=d.groupby("window").agg(classifiable_entrants=("id","size"),
                              genuinely_new=("is_new","sum"))
    g["pct_genuinely_new"]=(100*g["genuinely_new"]/g["classifiable_entrants"]).round(0)
    g["index"]=idx
    return g.reset_index()
tr=pd.concat([trend(f,"FTSE100"), trend(s,"S&P500")], ignore_index=True)
tr.to_csv(os.path.join(HERE,"entrant_trend_summary.csv"), index=False)

# ============================== report ==============================
print("FTSE entrants:", len(f), "| S&P entrants:", len(s))
print("\nFTSE provisional_class:\n", f["provisional_class"].value_counts().to_string())
print("\nS&P provisional_class:\n", s["provisional_class"].value_counts().to_string())
print("\nTrend (share genuinely-new among classifiable entrants, 5-yr windows):")
print(tr.pivot(index="window",columns="index",values="pct_genuinely_new").to_string())
con.close()
