#!/usr/bin/env python3
"""
Build two consolidated, publish-ready CSVs from everything we hold:

  FTSE100_consolidated.csv  — one row per (company, year):
      market cap, shares outstanding, year-end share price, dividend,
      revenue, net income (profit), total assets  + spine (CH number,
      FTSE entry/exit, former names, birth/death, SIC, status) + source URLs.

  SP500_consolidated.csv    — one row per (symbol, fiscal year):
      revenue, net income, total assets, market cap, shares, employees
      + spine (CIK, sector, HQ, founded, index entry/exit) + source URLs.

Sources: business_dynamism_v1_20260820.duckdb (DB tables) + the attached CSVs.
Provenance rule: nothing invented. Every financial column keeps its source_url
where we have one. Estimated/precision flags are carried through, not hidden.
"""
import os, glob, re, duckdb, pandas as pd, numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Canonical DB + output locations. Both used to point at files that do not exist
# (a v1 DB at the repo root, outputs written beside it), so this script could not
# run at all; the committed CSVs came from an older copy of it.
DB   = os.environ.get("BD_DUCKDB") or os.path.join(
    HERE, "database", "business_dynamism_v2_20260824d.duckdb")
OUT  = os.path.join(HERE, "deliverables", "consolidated")
SRC  = os.path.join(HERE, "source_inputs")   # hand-curated inputs live here
os.makedirs(OUT, exist_ok=True)

def src_one(pattern):
    """The single source CSV matching `pattern`, or a clear error naming it."""
    hits = sorted(glob.glob(os.path.join(SRC, pattern)))
    if not hits:
        raise SystemExit(f"no source input matching {pattern!r} under {SRC}")
    return hits[0]
# read-write: this script also refreshes the materialised consolidated tables
# the site reads, so that CSVs and tables cannot drift apart
con  = duckdb.connect(DB, read_only=False)

def norm(x):
    if pd.isna(x): return None
    s = str(x).strip().upper()
    if s in ("", "NAN", "NONE"): return None
    if s.isdigit(): return s.zfill(8)
    m = re.match(r"^([A-Z]{2})(\d+)$", s)
    if m: return m.group(1) + m.group(2).zfill(6)
    return s

def t(name):  # duckdb table -> df
    return con.execute(f"SELECT * FROM {name}").fetchdf()

# ============================== FTSE ==============================
comp = t("ftse100_compositions"); fund = t("ftse100_fundamentals")
memb = t("ftse100_membership");   mapg = t("ftse100_mapping")
canon = pd.read_csv(src_one("FTSE100_CANONICAL*.csv"), low_memory=False)

for d in (comp,fund,memb,mapg): d["cn"] = d["company_number"].map(norm)
canon["cn"] = canon["company_number"].map(norm)

# --- company-level SPINE ---
# names / former names / ticker / entry-exit from membership + canonical + mapping
epi = canon[canon["row_type"]=="MEMBERSHIP_EPISODE"].copy()
former = (epi.dropna(subset=["cn"]).groupby("cn")["former_names"]
            .apply(lambda s: "; ".join(sorted({x for x in s.dropna().astype(str) if x.strip()})) or None))
mem_first = (memb.sort_values("start_date").groupby("cn")
             .agg(company_name=("company_name","first"),
                  ftse_entry_date=("start_date","min"),
                  ftse_exit_date=("end_date","max"),
                  ftse_exit_type=("exit_type","last"),
                  ftse_exit_name=("exit_name","last"),
                  membership_source_url=("source_url","first")))
tick = mapg.dropna(subset=["cn"]).groupby("cn")["ticker"].first()

ftse_cns = sorted(set(comp["cn"].dropna())|set(fund["cn"].dropna())
                  |set(memb["cn"].dropna())|set(mapg["cn"].dropna())|set(epi["cn"].dropna()))
# pull firm_master spine only for our FTSE numbers
inlist = ",".join("'%s'"%c for c in ftse_cns)
fm = con.execute(f"""SELECT company_number, incorporation_date, birth_year, birth_precision,
        birth_is_estimated, death_date, exit_class, exit_type AS ch_exit_type, company_status,
        sic_code, sic_desc, match_status, first_filing_year, last_filing_year, size_class,
        turnover AS ch_snapshot_turnover, net_assets AS ch_snapshot_net_assets,
        total_assets AS ch_snapshot_total_assets, employees AS ch_snapshot_employees,
        snapshot_fiscal_year AS ch_snapshot_fy
      FROM firm_master WHERE company_number IN ({inlist})""").fetchdf()
fm["cn"] = fm["company_number"].map(norm)

# --- CH register enrichment (324/327 FTSE firms are in `companies`) ---
REGION = {
 'E':'London','EC':'London','N':'London','NW':'London','SE':'London','SW':'London','W':'London','WC':'London',
 'BR':'London','CR':'London','DA':'London','EN':'London','HA':'London','IG':'London','KT':'London','RM':'London','SM':'London','TW':'London','UB':'London','WD':'London',
 'BN':'South East','CT':'South East','GU':'South East','ME':'South East','MK':'South East','OX':'South East','PO':'South East','RG':'South East','RH':'South East','SL':'South East','SO':'South East','TN':'South East',
 'BA':'South West','BH':'South West','BS':'South West','DT':'South West','EX':'South West','GL':'South West','PL':'South West','TA':'South West','TQ':'South West','TR':'South West','SN':'South West','SP':'South West',
 'AL':'East of England','CB':'East of England','CM':'East of England','CO':'East of England','IP':'East of England','LU':'East of England','NR':'East of England','PE':'East of England','SG':'East of England','SS':'East of England',
 'B':'West Midlands','CV':'West Midlands','DY':'West Midlands','WS':'West Midlands','WV':'West Midlands','WR':'West Midlands','TF':'West Midlands','ST':'West Midlands',
 'DE':'East Midlands','LE':'East Midlands','LN':'East Midlands','NG':'East Midlands','NN':'East Midlands',
 'BD':'Yorkshire & Humber','DN':'Yorkshire & Humber','HD':'Yorkshire & Humber','HG':'Yorkshire & Humber','HU':'Yorkshire & Humber','HX':'Yorkshire & Humber','LS':'Yorkshire & Humber','S':'Yorkshire & Humber','WF':'Yorkshire & Humber','YO':'Yorkshire & Humber',
 'BB':'North West','BL':'North West','CA':'North West','CH':'North West','CW':'North West','FY':'North West','L':'North West','LA':'North West','M':'North West','OL':'North West','PR':'North West','SK':'North West','WA':'North West','WN':'North West',
 'DH':'North East','DL':'North East','NE':'North East','SR':'North East','TS':'North East',
 'CF':'Wales','LD':'Wales','LL':'Wales','NP':'Wales','SA':'Wales','SY':'Wales',
 'AB':'Scotland','DD':'Scotland','DG':'Scotland','EH':'Scotland','FK':'Scotland','G':'Scotland','HS':'Scotland','IV':'Scotland','KA':'Scotland','KW':'Scotland','KY':'Scotland','ML':'Scotland','PA':'Scotland','PH':'Scotland','TD':'Scotland','ZE':'Scotland',
 'BT':'Northern Ireland'}
reg = con.execute(f'''SELECT "CompanyNumber" cnr, "IncorporationDate" reg_incorporation_date,
   "DissolutionDate" reg_dissolution_date, "CompanyStatus" reg_company_status,
   "CompanyCategory" company_category, "RegAddress_PostTown" reg_posttown,
   "RegAddress_County" reg_county, "RegAddress_PostCode" reg_postcode,
   "RegAddress_Country" reg_country, "SICCode_SicText_1" sic_1, "SICCode_SicText_2" sic_2,
   "SICCode_SicText_3" sic_3, "SICCode_SicText_4" sic_4
   FROM companies WHERE "CompanyNumber" IN ({inlist})''').fetchdf()
reg["cn"] = reg["cnr"].map(norm)
def _area(pc):
    if pd.isna(pc): return None
    m = re.match(r"^[A-Z]{1,2}", str(pc).upper().strip())
    return m.group(0) if m else None
reg["region"] = reg["reg_postcode"].map(lambda p: REGION.get(_area(p)))
reg = reg.drop(columns=["cnr"])

spine = (pd.DataFrame({"cn": ftse_cns})
         .merge(mem_first, on="cn", how="left")
         .merge(tick.rename("ticker"), on="cn", how="left")
         .merge(former.rename("former_names"), on="cn", how="left")
         .merge(fm.drop(columns=["company_number"]), on="cn", how="left")
         .merge(reg, on="cn", how="left"))
# fill primary spine fields from the register where firm_master lacked them
spine["incorporation_date"] = spine["incorporation_date"].fillna(spine["reg_incorporation_date"])

# Third source: incorporation dates fetched directly from Companies House for
# constituents that appear in neither firm_master nor the bulk register --
# mostly companies dissolved long before the current snapshot. Without these
# they carry an identity but no birth date, so age at index entry is
# incomputable and they fall out of the entrant classification as unknown_age.
_inc = os.path.join(SRC, "ftse_incorporation_dates.csv")
if os.path.exists(_inc):
    _d = pd.read_csv(_inc, dtype=str)[["company_number", "incorporation_date"]]
    _d = _d.rename(columns={"company_number": "cn", "incorporation_date": "ch_incorporation_date"})
    _d["ch_incorporation_date"] = pd.to_datetime(_d["ch_incorporation_date"], errors="coerce")
    spine = spine.merge(_d.drop_duplicates("cn"), on="cn", how="left")
    _before = spine["incorporation_date"].isna().sum()
    spine["incorporation_date"] = spine["incorporation_date"].fillna(spine["ch_incorporation_date"])
    print(f"  incorporation dates filled from Companies House: "
          f"{_before - spine['incorporation_date'].isna().sum()}")
    spine = spine.drop(columns=["ch_incorporation_date"])
spine["company_status"]     = spine["company_status"].fillna(spine["reg_company_status"])
spine["death_date"]         = spine["death_date"].fillna(spine["reg_dissolution_date"])
spine["sic_desc"]           = spine["sic_desc"].fillna(spine["sic_1"])

# --- year-level FACTS ---
mkt = comp.rename(columns={"year":"year","year_end_price_pence":"year_end_price_pence",
        "annual_dividend_pence":"annual_dividend_pence","market_cap_gbp":"market_cap_gbp",
        "shares_outstanding":"shares_outstanding","market_cap_basis":"market_cap_basis",
        "shares_source_url":"shares_source_url"})[
        ["cn","year","year_end_price_pence","annual_dividend_pence","market_cap_gbp",
         "shares_outstanding","market_cap_basis","shares_source_url"]]
fn = fund.rename(columns={"fiscal_year":"year","revenue":"revenue","net_income":"net_income",
        "total_assets":"total_assets","currency":"currency",
        "source_url":"fundamentals_source_url"})[
        ["cn","year","revenue","net_income","total_assets","currency","fundamentals_source_url"]]

panel = pd.merge(mkt, fn, on=["cn","year"], how="outer")
ftse = panel.merge(spine, on="cn", how="left")

order = ["cn","company_name","former_names","ticker","ftse_entry_date","ftse_exit_date",
         "ftse_exit_type","ftse_exit_name","incorporation_date","birth_year","birth_precision",
         "birth_is_estimated","death_date","ch_exit_type","exit_class","company_status","company_category",
         "sic_code","sic_desc","sic_1","sic_2","sic_3","sic_4",
         "region","reg_posttown","reg_county","reg_postcode","reg_country",
         "reg_incorporation_date","reg_dissolution_date","reg_company_status",
         "match_status","first_filing_year","last_filing_year","size_class",
         "year","year_end_price_pence","annual_dividend_pence","market_cap_gbp","shares_outstanding",
         "market_cap_basis","revenue","net_income","total_assets","currency",
         "ch_snapshot_fy","ch_snapshot_turnover","ch_snapshot_net_assets","ch_snapshot_total_assets",
         "ch_snapshot_employees","shares_source_url","fundamentals_source_url","membership_source_url"]
ftse = ftse[[c for c in order if c in ftse.columns]].rename(columns={"cn":"company_number"})
# --- flag & neutralise wrong-namesake CH matches (incorporation AFTER first FTSE entry
#     is impossible => the matched company number is the wrong modern namesake) ---
_iy = pd.to_datetime(ftse["incorporation_date"], errors="coerce").dt.year
_ey = pd.to_datetime(ftse["ftse_entry_date"], errors="coerce").dt.year
ftse["ch_match_suspect"] = _iy.notna() & _ey.notna() & (_iy > _ey)
WRONG = ["incorporation_date","birth_year","birth_precision","birth_is_estimated","death_date",
         "ch_exit_type","exit_class","company_status","company_category","sic_code","sic_desc",
         "sic_1","sic_2","sic_3","sic_4","region","reg_posttown","reg_county","reg_postcode",
         "reg_country","reg_incorporation_date","reg_dissolution_date","reg_company_status",
         "match_status","first_filing_year","last_filing_year","size_class","ch_snapshot_fy",
         "ch_snapshot_turnover","ch_snapshot_net_assets","ch_snapshot_total_assets","ch_snapshot_employees"]
ftse.loc[ftse["ch_match_suspect"], [c for c in WRONG if c in ftse.columns]] = np.nan
ftse = ftse.sort_values(["company_number","year"]).reset_index(drop=True)
ftse.to_csv(os.path.join(OUT,"FTSE100_consolidated.csv"), index=False)
print(f"  ch_match_suspect rows flagged & entity-fields nulled: {int(ftse['ch_match_suspect'].sum())} "
      f"({ftse[ftse['ch_match_suspect']]['company_number'].nunique()} companies)")
print(f"FTSE100_consolidated.csv: {len(ftse):,} rows, {ftse['company_number'].nunique()} companies, "
      f"years {int(ftse['year'].min())}-{int(ftse['year'].max())}")

# ============================== S&P ==============================
spf = t("sp500_financials"); spc = t("sp500_companies_full"); spm = t("sp500_membership")
amend = pd.read_csv(src_one("sp500_amended*.csv"), low_memory=False)

# spine per symbol
# Identity is CIK, never ticker. Tickers are reused after a delisting, so a
# ticker merge attaches one company's membership dates or financials to another's
# — build_identity_crosswalk.py documents seven live cases (Compuware/Ocean
# Thermal, Anadarko/ARKO, ...). sp500_identity is the canonical crosswalk and
# supplies the CIK wherever a source table lacks one.
ident = t("sp500_identity")[["symbol", "cik"]].dropna(subset=["cik"]).drop_duplicates("symbol")

def with_cik(df, key="symbol"):
    """Attach the canonical CIK, using `key` ONLY to look it up — never to merge on."""
    d = df.copy()
    if key != "symbol":
        d = d.rename(columns={key: "symbol"})
    if "cik" in d.columns:
        d = d.drop(columns=["cik"])
    return d.merge(ident, on="symbol", how="left")

spc_s = spc.rename(columns={"symbol":"symbol","security":"company_name","cik":"cik","sector":"sector",
        "sub_industry":"sub_industry","hq":"hq","date_added":"index_date_added","founded":"founded",
        "sic":"sic","sic_description":"sic_description","state_of_inc":"state_of_inc"})[
        ["symbol","company_name","cik","sector","sub_industry","hq","index_date_added",
         "founded","sic","sic_description","state_of_inc"]]
# sector_basis records where each sector came from (index_list_gics vs an
# EDGAR-SIC mapping); without it the CSV cannot be told apart from observed data
try:
    _sb = t("sp500_companies_full")[["symbol","sector_basis"]].dropna(subset=["symbol"]).drop_duplicates("symbol")
    spc_s = spc_s.merge(_sb, on="symbol", how="left")
except Exception as _e:
    print(f"  note: sector_basis unavailable ({_e}); CSV will omit it)")
spc_s = with_cik(spc_s)

def one_per_cik(df, prefer=None):
    """Collapse to a single row per CIK.

    Necessary before any CIK merge: each source still holds one row per TICKER,
    and one company can hold several (GOOG/GOOGL, FB/META, share classes). Left
    un-collapsed, a CIK merge multiplies rows instead of matching them.
    Rows with no CIK are passed through untouched — they cannot collide.
    """
    d = df.copy()
    has, missing = d[d["cik"].notna()], d[d["cik"].isna()]
    if prefer:
        has = has.sort_values(prefer, na_position="last")
    has = has.drop_duplicates(subset=["cik"], keep="first")
    return pd.concat([has, missing], ignore_index=True)

# Most-complete row wins where a company appears under several tickers.
spc_s["_fill"] = spc_s.notna().sum(axis=1)
spc_s = one_per_cik(spc_s.sort_values("_fill", ascending=False)).drop(columns=["_fill"])

# Membership: aggregate episodes per COMPANY, not per ticker, so a rename
# (BSY -> SKY) is one span rather than two.
mem = spm.rename(columns={"ticker": "symbol"})
mem = with_cik(mem)
mem["_key"] = mem["cik"].fillna("TICKER:" + mem["symbol"].astype(str))
mem = (mem.sort_values("start_date")
          .groupby("_key")
          .agg(symbol=("symbol", "first"), cik=("cik", "first"),
               sp_entry_date=("start_date", "min"), sp_exit_date=("end_date", "max"))
          .reset_index(drop=True))
# entry/exit precision + source urls from amended (one per ticker)
am = (amend.dropna(subset=["ticker"]).sort_values("fiscal_year")
      .groupby("ticker").agg(
        former_company_name=("company_name","first"),
        sp_entry_precision=("sp_entry_precision","last"),
        sp_exit_precision=("sp_exit_precision","last"),
        membership_source_urls=("membership_source_urls","first")).reset_index().rename(columns={"ticker":"symbol"}))

am = one_per_cik(with_cik(am))
# Merge on CIK. Rows with no CIK cannot be safely matched and are kept, unmerged,
# rather than guessed at via ticker.
spine_sp = (spc_s.merge(mem.drop(columns=["symbol"]), on="cik", how="outer")
                 .merge(am.drop(columns=["symbol"]), on="cik", how="left"))

fin = spf.rename(columns={"symbol":"symbol","fiscal_year":"fiscal_year","period_end":"period_end",
        "revenue":"revenue","net_income":"net_income","total_assets":"total_assets",
        "market_cap":"market_cap","shares_outstanding":"shares_outstanding","employees":"employees",
        "revenue_grade":"revenue_grade","net_income_grade":"net_income_grade","total_assets_grade":"total_assets_grade",
        "revenue_source_url":"revenue_source_url","net_income_source_url":"net_income_source_url",
        "total_assets_source_url":"total_assets_source_url"})[
        ["symbol","fiscal_year","period_end","revenue","net_income","total_assets","market_cap",
         "shares_outstanding","employees","revenue_grade","net_income_grade","total_assets_grade",
         "revenue_source_url","net_income_source_url","total_assets_source_url"]]

fin = with_cik(fin)
sp = fin.merge(spine_sp.drop(columns=["symbol"], errors="ignore"), on="cik", how="left")
order_sp = ["symbol","company_name","former_company_name","cik","sector","sector_basis","sub_industry","hq",
            "founded","state_of_inc","sic","sic_description","index_date_added",
            "sp_entry_date","sp_entry_precision","sp_exit_date","sp_exit_precision",
            "fiscal_year","period_end","revenue","net_income","total_assets","market_cap",
            "shares_outstanding","employees","revenue_grade","net_income_grade","total_assets_grade",
            "revenue_source_url","net_income_source_url","total_assets_source_url","membership_source_urls"]
sp = sp[[c for c in order_sp if c in sp.columns]].sort_values(["symbol","fiscal_year"]).reset_index(drop=True)
sp.to_csv(os.path.join(OUT,"SP500_consolidated.csv"), index=False)

# ---- refresh the materialised tables the site reads ----
# These are separate copies inside the DuckDB; rebuilding only the CSVs used to
# leave ftse100_consolidated stale, so the site mixed corrected and uncorrected
# figures. Columns the table has but the CSV does not (sector_basis) are
# preserved by re-joining them after the reload.
def _refresh(table, df, keep_from_old=()):
    try:
        old_cols = {r[0] for r in con.execute(
            "select column_name from information_schema.columns where table_name = ?", [table]).fetchall()}
        carry = [c for c in keep_from_old if c in old_cols and c not in df.columns]
        if carry:
            key = "symbol" if "symbol" in df.columns else "company_number"
            # ONE row per key. A plain DISTINCT fans out whenever a carried
            # column varies within the key (shares_source_url does), which
            # multiplies the table instead of enriching it.
            agg = ", ".join(f"max({c}) as {c}" for c in carry)
            prev = con.execute(
                f"select {key}, {agg} from {table} where {key} is not null group by {key}"
            ).fetchdf()
            before = len(df)
            df = df.merge(prev, on=key, how="left")
            if len(df) != before:
                raise RuntimeError(f"{table}: carry-merge changed row count {before} -> {len(df)}")
        con.register("_refresh_df", df)
        con.execute(f"create or replace table {table} as select * from _refresh_df")
        con.unregister("_refresh_df")
        print(f"  refreshed table {table}: {len(df):,} rows")
    except Exception as e:
        print(f"  WARNING: could not refresh {table}: {e}")

_refresh("ftse100_consolidated", ftse)
_refresh("sp500_consolidated", sp, keep_from_old=("sector_basis", "shares_source_url"))
print(f"SP500_consolidated.csv: {len(sp):,} rows, {sp['symbol'].nunique()} symbols, "
      f"years {int(sp['fiscal_year'].min())}-{int(sp['fiscal_year'].max())}")
con.close()
