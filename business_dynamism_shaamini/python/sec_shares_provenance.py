#!/usr/bin/env python3
"""
sec_shares_provenance.py — from SEC EDGAR company-facts, fill S&P:
  * shares_outstanding  (dei:EntityCommonStockSharesOutstanding, per fiscal year)
  * source URLs for revenue / net income / total assets (official filing index URL)

Resumable: appends to sec_supplement.csv, skips CIKs already recorded. Runs in
time-bounded batches so it fits the sandbox timeout — just re-run until DONE.

Output: sec_supplement.csv with
  cik, fiscal_year, shares_sec, shares_url, revenue_url, net_income_url, total_assets_url
Then merge_sec_supplement.py folds it into SP500_consolidated.csv (fill-where-null).
"""
import os, csv, time, sys, requests, duckdb
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=os.path.join(HERE,"business_dynamism_v1_20260820.duckdb")
OUT=os.path.join(HERE,"sec_supplement.csv")
UA={"User-Agent":"BritishProgress-Research research@britishprogress.org"}
BUDGET=int(sys.argv[sys.argv.index("--seconds")+1]) if "--seconds" in sys.argv else 95

REV=["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax","SalesRevenueNet",
     "RevenueFromContractWithCustomerIncludingAssessedTax"]
def filing_url(cik, accn):
    if not accn: return None
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-','')}/{accn}-index.htm"

def concept_url_by_fy(usg, names):
    """fiscal_year -> filing index url, preferring 10-K annual USD facts."""
    out={}
    for nm in names:
        node=usg.get(nm)
        if not node: continue
        for u in node.get("units",{}).get("USD",[]):
            if u.get("form")!="10-K" or u.get("fp")!="FY": continue
            fy=u.get("fy")
            if fy and fy not in out:
                out[fy]=filing_url(cikG, u.get("accn"))
    return out

def main():
    con=duckdb.connect(DB, read_only=True)
    ciks=[r[0] for r in con.execute(
        "SELECT DISTINCT cik FROM sp500_financials WHERE cik IS NOT NULL ORDER BY cik").fetchall()]
    con.close()
    done=set()
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT)): done.add(str(r["cik"]))
    todo=[c for c in ciks if str(c) not in done]
    print(f"total CIKs {len(ciks)} | done {len(done)} | this run: up to {len(todo)} (budget {BUDGET}s)", flush=True)

    new=not os.path.exists(OUT)
    f=open(OUT,"a",newline=""); w=csv.writer(f)
    if new: w.writerow(["cik","fiscal_year","shares_sec","shares_url","revenue_url","net_income_url","total_assets_url"])

    global cikG
    t0=time.time(); n=0
    for cik in todo:
        if time.time()-t0>BUDGET: break
        cikG=cik
        cik10=str(int(cik)).zfill(10)
        try:
            r=requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json",headers=UA,timeout=60)
            time.sleep(0.18)
        except Exception:
            continue
        if r.status_code!=200:
            w.writerow([cik,"","","","","",""]); f.flush(); continue   # mark done (no data)
        j=r.json(); facts=j.get("facts",{}); usg=facts.get("us-gaap",{}); dei=facts.get("dei",{})
        # shares per fiscal year (prefer 10-K/FY cover-page fact)
        shares={}
        for u in dei.get("EntityCommonStockSharesOutstanding",{}).get("units",{}).get("shares",[]):
            fy=u.get("fy")
            if not fy: continue
            if u.get("form")=="10-K" or fy not in shares:
                shares[fy]=(u.get("val"), filing_url(cik,u.get("accn")))
        rev_u=concept_url_by_fy(usg,REV)
        ni_u =concept_url_by_fy(usg,["NetIncomeLoss"])
        ta_u =concept_url_by_fy(usg,["Assets"])
        fys=set(shares)|set(rev_u)|set(ni_u)|set(ta_u)
        if not fys:
            w.writerow([cik,"","","","","",""]); f.flush()
        for fy in sorted(fys):
            sv,su=shares.get(fy,(None,None))
            w.writerow([cik,fy,sv,su,rev_u.get(fy),ni_u.get(fy),ta_u.get(fy)])
        f.flush(); n+=1
        if n%25==0: print(f"  processed {n} companies...", flush=True)
    f.close()
    remaining=len([c for c in ciks if str(c) not in done])-n
    print(f"batch done: +{n} companies. remaining ~{remaining}. {'ALL DONE' if remaining<=0 else 'RE-RUN to continue'}")

if __name__=="__main__":
    main()
