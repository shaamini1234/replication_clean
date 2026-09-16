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
REPO=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Canonical DB + output locations — both previously pointed at paths that do not
# exist, so this script could not run; the committed CSVs came from an older copy.
DB=os.environ.get("BD_DUCKDB") or os.path.join(
    REPO,"database","business_dynamism_v2_20260824d.duckdb")
HERE=os.path.join(REPO,"deliverables","consolidated")
os.makedirs(HERE, exist_ok=True)
NEW_MAX=12          # business younger than this at entry = candidate "genuinely new"
VERY_NEW=3          # younger than this yet index-sized = wrapper/spin-off/hypergrowth (adjudicate)
con=duckdb.connect(DB, read_only=True)

def yr(x):
    if pd.isna(x): return np.nan
    s=str(x)
    m=re.search(r"(\d{4})", s)
    return int(m.group(1)) if m else np.nan

# ============================== FTSE ==============================
# Hand-verified identity / birth corrections, applied before classification.
# Two classes: a company_number that matched the WRONG company (the FTSE record
# spells Renishaw "Reinshaw", which matched a cake-icing manufacturer), and an
# operating birth year where the registered entity is an IPO holding company
# younger than the business it holds (Darktrace incorporated its listco in 2021;
# the business dates from 2013, so age at entry is 8, not 0).
FTSE_FIX=os.path.join(REPO,"source_inputs","ftse_manual_identity_corrections.csv")
fix=pd.read_csv(FTSE_FIX, dtype=str) if os.path.exists(FTSE_FIX) else pd.DataFrame(
    columns=["company_number","correct_company_number","operating_birth_year"])
remap={r["company_number"]: r["correct_company_number"]
       for _,r in fix.iterrows() if isinstance(r.get("correct_company_number"),str) and r["correct_company_number"].strip()}
opbirth={(remap.get(r["company_number"], r["company_number"])): int(float(r["operating_birth_year"]))
         for _,r in fix.iterrows()
         if pd.notna(r.get("operating_birth_year")) and str(r["operating_birth_year"]).strip()}
if remap: print(f"  FTSE identity remaps applied: {remap}")
if opbirth: print(f"  FTSE operating-birth overrides: {opbirth}")

mem=con.execute("SELECT company_number,company_name,start_date FROM ftse100_membership "
                "WHERE company_number IS NOT NULL").fetchdf()
mem["company_number"]=mem["company_number"].replace(remap)
mem["entry_year"]=mem["start_date"].map(yr)
ep=mem.groupby("company_number").size().rename("episodes")
first=mem.sort_values("start_date").groupby("company_number").agg(
    company_name=("company_name","first"), entry_date=("start_date","min"),
    entry_year=("entry_year","min")).join(ep)
info=con.execute("""SELECT DISTINCT company_number, incorporation_date, company_category, sic_1, former_names
    FROM ftse100_consolidated""").fetchdf()
info["company_number"]=info["company_number"].replace(remap)
info=info.drop_duplicates("company_number").set_index("company_number")
f=first.join(info)
# ftse100_consolidated covers 316 companies; ftse100_membership has 372, so 78
# constituents can never receive an incorporation date from that join and fall
# out as unknown_age. Those dates were fetched directly from Companies House
# (fetch_ftse_incorporation_dates.py) and are read here as well.
_INC=os.path.join(REPO,"source_inputs","ftse_incorporation_dates.csv")
if os.path.exists(_INC):
    _d=pd.read_csv(_INC, dtype=str).drop_duplicates("company_number").set_index("company_number")
    _fill=_d["incorporation_date"].to_dict()
    f["incorporation_date"]=[cur if pd.notna(cur) else _fill.get(cn)
                             for cn, cur in zip(f.index, f["incorporation_date"])]
f["incorp_year"]=f["incorporation_date"].map(yr)
# An operating-birth override wins over the registered incorporation date: the
# question is how old the BUSINESS was at index entry, not its current holdco.
if opbirth:
    f["incorp_year"]=[opbirth.get(cn, v) for cn, v in zip(f.index, f["incorp_year"])]
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
# FTSE sector, joined on company_number (the sector file is ticker-keyed, so it
# is resolved to company_number first — see build_ftse_sector_crosswalk.py).
try:
    fsec=con.execute(f"""
        SELECT company_number, max(sector) AS sector
        FROM read_csv_auto('{os.path.join(REPO,"source_inputs","ftse100_sector_classification_keyed.csv")}',
                           header=true, all_varchar=true)
        WHERE company_number IS NOT NULL AND company_number <> '' GROUP BY company_number
    """).fetchdf().set_index("company_number")
    f=f.join(fsec)
except Exception as exc:
    print(f"  note: FTSE sector crosswalk unavailable ({exc}); sector column left empty")
    f["sector"]=np.nan

f=f.reset_index().rename(columns={"company_number":"id"})
fcols=["index","id","company_name","entry_date","entry_year","incorp_year","age_at_entry",
       "episodes","re_entry","has_former_names","holdco","inv_trust","wrapper_suspect","sector",
       "ch_match_status","company_category","sic_1","former_names","provisional_class"]
f[fcols].to_csv(os.path.join(HERE,"ftse_entrants_classified.csv"), index=False)

# ============================== S&P ==============================
# Identity is CIK, never ticker: London and US tickers are both reused after a
# delisting, so grouping membership episodes by ticker merges two different
# companies into one "re-entry". sp500_membership now carries a CIK from
# sp500_identity; rows it could not resolve keep a TICKER: key, are flagged, and
# are never silently merged with a resolved company.
spm=con.execute("SELECT ticker,cik,start_date FROM sp500_membership").fetchdf()
spm["entry_year"]=spm["start_date"].map(yr)
spm["key"]=np.where(spm["cik"].notna(), spm["cik"], "TICKER:"+spm["ticker"].astype(str))
spep=spm.groupby("key").size().rename("episodes")
spf=spm.sort_values("start_date").groupby("key").agg(
    ticker=("ticker","first"), cik=("cik","first"),
    entry_date=("start_date","min"), entry_year=("entry_year","min")).join(spep)
n_unres=int(spf["cik"].isna().sum())
if n_unres:
    print(f"  note: {n_unres} S&P entrants have no CIK; kept under a TICKER: key, not merged")

# Company attributes joined ON CIK. sector comes from sp500_consolidated, which
# carries the EDGAR-recovered sector for companies that have left the index —
# sp500_companies_full only ever had it for current members.
comp=con.execute("""
    SELECT cik,
           max(security)      AS security,
           max(founded)       AS founded,
           max(date_added)    AS date_added,
           max(sic)           AS sic,
           max(sub_industry)  AS sub_industry
    FROM sp500_companies_full WHERE cik IS NOT NULL GROUP BY cik
""").fetchdf().set_index("cik")
secs=con.execute("""
    SELECT cik, max(sector) AS sector, max(sector_basis) AS sector_basis
    FROM sp500_consolidated WHERE cik IS NOT NULL GROUP BY cik
""").fetchdf().set_index("cik")

# Founding year from sp500_founding, NOT sp500_companies_full.founded: the latter
# is populated only for CURRENT index members (503 of 1202), the same
# survivorship bias that afflicted sector, and using it puts every delisted
# company into unknown_age. sp500_founding covers 1,147.
fnd=con.execute("""
    SELECT cik, max(try_cast(founded_year AS INTEGER)) AS founded_year_src
    FROM sp500_founding WHERE cik IS NOT NULL GROUP BY cik
""").fetchdf().set_index("cik")

# Company name for delisted constituents: sp500_companies_full.security only
# covers current members, so recovered entrants would show blank on a public
# page. sp500_sector_enriched carries the registrant name EDGAR still holds.
try:
    enm=con.execute("""
        SELECT cik, max(edgar_name) AS edgar_name
        FROM sp500_sector_enriched WHERE cik IS NOT NULL GROUP BY cik
    """).fetchdf().set_index("cik")
except Exception:
    enm=pd.DataFrame(columns=["edgar_name"]).rename_axis("cik")

s=spf.join(comp, on="cik").join(secs, on="cik").join(fnd, on="cik").join(enm, on="cik")
s["security"]=s["security"].fillna(s["edgar_name"])
# prefer the dedicated founding research; fall back to the index-list value
s["founded_year"]=s["founded_year_src"].fillna(s["founded"].map(yr))
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
s=s.reset_index(drop=True).rename(columns={"ticker":"id","security":"company_name"})
# keep CIK a zero-padded 10-character string on the way out; a bare integer
# would lose the leading zeros and stop joining against the database
s["cik"]=s["cik"].apply(lambda v: f"{int(v):010d}" if pd.notna(v) and str(v).strip() not in ("","nan") else "")
scols=["index","id","cik","company_name","entry_date","entry_year","founded_year","age_at_entry",
       "episodes","re_entry","spac_shell","sic","sector","sector_basis","sub_industry",
       "provisional_class"]
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
