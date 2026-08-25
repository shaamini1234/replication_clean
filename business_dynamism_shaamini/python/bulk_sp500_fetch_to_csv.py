#!/usr/bin/env python3
"""
bulk_sp500_fetch_to_csv.py — BULK-fetch S&P shares outstanding + market cap to a CSV
(no Neon). Reads the "what's missing" list from the local DuckDB, fetches SEC + stooq,
writes sp500_shares_marketcap_bulk.csv. Resumable (skips symbols already written).

  pip install duckdb requests
  python3 python/bulk_sp500_fetch_to_csv.py --limit 5 --debug   # inspect what each source returns
  python3 python/bulk_sp500_fetch_to_csv.py --limit 50          # test
  python3 python/bulk_sp500_fetch_to_csv.py                     # full
"""
import os, sys, time, io, csv, glob, requests, duckdb
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=sorted(glob.glob(os.path.join(HERE,"database","business_dynamism_v2_*.duckdb")))[-1]
OUT=os.path.join(HERE,"source_inputs","sp500_shares_marketcap_bulk.csv")
UA={"User-Agent":"BritishProgress Research contact britishprogress.org"}
LIMIT=int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else None
DEBUG="--debug" in sys.argv

def clean_cik(cik):
    s=str(cik).strip()
    if s.endswith(".0"): s=s[:-2]
    return s if s.isdigit() else None

def sec_shares(cik):
    ck=clean_cik(cik)
    if not ck: return {}, "bad_cik"
    try:
        r=requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{ck.zfill(10)}.json",headers=UA,timeout=60)
        time.sleep(0.15)
    except Exception as e:
        return {}, f"err:{str(e)[:30]}"
    if r.status_code!=200: return {}, f"http{r.status_code}"
    node=((r.json().get("facts",{}) or {}).get("dei",{})).get("EntityCommonStockSharesOutstanding",{})
    out={}
    for u in node.get("units",{}).get("shares",[]):
        fy=u.get("fy")
        if not fy: continue
        accn=u.get("accn","")
        url=f"https://www.sec.gov/Archives/edgar/data/{int(ck)}/{accn.replace('-','')}/{accn}-index.htm" if accn else None
        if u.get("form")=="10-K" or fy not in out: out[fy]=(u.get("val"),url)
    return out, ("ok" if out else "no_shares_fact")

import yfinance as yf
def stooq_daily(t):
    """month-end closes via yfinance (handles Yahoo session/backoff) -> {YYYY-MM-DD: close}."""
    sym=t.upper().replace(".","-")
    for attempt in range(3):
        try:
            h=yf.Ticker(sym).history(period="max", interval="1mo", auto_adjust=False, actions=False)
        except Exception as e:
            time.sleep(2*(attempt+1)); laststat=f"err:{str(e)[:25]}"; continue
        if h is not None and not h.empty and "Close" in h:
            d={ix.strftime("%Y-%m-%d"):float(c) for ix,c in h["Close"].items() if c==c}
            if d:
                time.sleep(0.4); return d, "ok"
        time.sleep(2*(attempt+1)); laststat="empty"
    return {}, laststat

def yearend(daily,pend,fy):
    tgt=str(pend) if pend else f"{fy}-12-31"
    days=sorted([x for x in daily if x<=tgt])
    return (daily[days[-1]],days[-1]) if days else (None,None)

def main():
    con=duckdb.connect(DB, read_only=True)
    rows=con.execute("""SELECT symbol, cik, fiscal_year, period_end, shares_outstanding, market_cap
                        FROM sp500_financials
                        WHERE cik IS NOT NULL AND (shares_outstanding IS NULL OR market_cap IS NULL)
                        ORDER BY symbol""").fetchall()
    con.close()
    from collections import defaultdict
    byco=defaultdict(list)
    for sym,cik,fy,pend,sh,mc in rows: byco[(sym,cik)].append((fy,str(pend) if pend else None,sh,mc))
    comps=list(byco.items())
    done=set()
    if os.path.exists(OUT):
        for r in csv.DictReader(open(OUT)): done.add(r["symbol"])
    todo=[(k,v) for k,v in comps if k[0] not in done]
    if LIMIT: todo=todo[:LIMIT]
    print(f"companies missing shares/mcap: {len(comps)} | to fetch this run: {len(todo)}", flush=True)
    new=not os.path.exists(OUT); f=open(OUT,"a",newline=""); w=csv.writer(f)
    if new: w.writerow(["symbol","cik","fiscal_year","shares_outstanding","shares_source_url","market_cap","marketcap_source_url"])
    nsh=nmc=0
    for i,((sym,cik),years) in enumerate(todo,1):
        shares,sstat=sec_shares(cik)
        daily,dstat=stooq_daily(sym)                    # ALWAYS fetch price (market cap needs it even if shares already known)
        if DEBUG: print(f"  {sym} cik={cik} SEC:{sstat}({len(shares)}) stooq:{dstat}({len(daily)})", flush=True)
        for fy,pend,sh_ex,mc_ex in years:
            sh_val,sh_url=shares.get(fy,(None,None))
            out_sh=int(sh_val) if (sh_ex is None and sh_val) else None
            use_sh=sh_ex if sh_ex is not None else out_sh
            out_mc=out_murl=None
            if mc_ex is None and use_sh and daily:
                close,cdate=yearend(daily,pend,fy)
                if close:
                    out_mc=round(close*use_sh); out_murl=f"https://finance.yahoo.com/quote/{sym.upper().replace('.','-')}/history (month-end close {cdate}) x shares"
            if out_sh is not None or out_mc is not None:
                w.writerow([sym,cik,fy,out_sh if out_sh is not None else "",sh_url or "",
                            out_mc if out_mc is not None else "",out_murl or ""])
                nsh+= out_sh is not None; nmc+= out_mc is not None
        f.flush()
        if i%50==0: print(f"  {i}/{len(todo)}  shares+={nsh} mcap+={nmc}", flush=True)
    f.close()
    print(f"DONE. wrote {OUT}  (new shares rows: {nsh}, new market_cap rows: {nmc})")

if __name__=="__main__":
    main()
