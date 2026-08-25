#!/usr/bin/env python3
"""
bulk_sp500_shares_marketcap.py — BULK-fill S&P shares outstanding + market cap, fast,
no per-company agents. Fill-where-null into Neon sp500_financials, with source URLs.

Two bulk sources (one request each, covering all years):
  * SHARES  : SEC company-facts  dei:EntityCommonStockSharesOutstanding  (XBRL, ~2009+)
              https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
  * PRICE   : stooq full daily history per US ticker  ->  year-end close
              https://stooq.com/q/d/l/?s=<ticker>.us&i=d
  * MARKET CAP = year-end close x shares_outstanding (USD)

Run by an agent WITH a working shell (this is the user's own machine, normal scraping):
  pip install requests psycopg2-binary
  python3 python/bulk_sp500_shares_marketcap.py                 # all
  python3 python/bulk_sp500_shares_marketcap.py --limit 50      # test first
Resumable & idempotent (fill-where-null). Re-run any time.

Coverage reality: SEC XBRL shares exist ~2009+, so this fills 2009+ strongly. Pre-2009
shares/market cap come from the separately-committed audited file (SP500_marketdata_filled*).
"""
import os, sys, time, io, csv, requests, psycopg2, psycopg2.extras
NEON="postgresql://neondb_owner:npg_q1uDNWofte0n@ep-nameless-fire-atkh5lxj.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require"
UA={"User-Agent":"BritishProgress-Research research@britishprogress.org"}
LIMIT=int(sys.argv[sys.argv.index("--limit")+1]) if "--limit" in sys.argv else None

def sec_shares(cik):
    """fiscal_year -> (shares, filing_url) from dei:EntityCommonStockSharesOutstanding, prefer 10-K."""
    cik10=str(int(cik)).zfill(10)
    try:
        r=requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json",headers=UA,timeout=60); time.sleep(0.12)
    except Exception: return {}
    if r.status_code!=200: return {}
    dei=(r.json().get("facts",{}) or {}).get("dei",{})
    node=dei.get("EntityCommonStockSharesOutstanding",{})
    out={}
    for u in node.get("units",{}).get("shares",[]):
        fy=u.get("fy");
        if not fy: continue
        accn=u.get("accn","")
        url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-','')}/{accn}-index.htm" if accn else None
        if u.get("form")=="10-K" or fy not in out:
            out[fy]=(u.get("val"), url)
    return out

def stooq_daily(ticker):
    """date(str YYYY-MM-DD) -> close, from stooq full daily history."""
    for suf in (".us",".us"):  # US listing
        try:
            r=requests.get(f"https://stooq.com/q/d/l/?s={ticker.lower()}{suf}&i=d",timeout=40); time.sleep(0.25)
        except Exception: return {}
        if r.status_code==200 and r.text.startswith("Date"):
            d={}
            for row in csv.DictReader(io.StringIO(r.text)):
                try: d[row["Date"]]=float(row["Close"])
                except: pass
            return d
    return {}

def yearend_close(daily, period_end, fy):
    """close on the last trading day <= period_end (or Dec 31 of fy)."""
    target=period_end if period_end else f"{fy}-12-31"
    days=sorted([x for x in daily if x<=str(target)])
    return daily[days[-1]] if days else None, (days[-1] if days else None)

def main():
    c=psycopg2.connect(NEON); c.autocommit=True; cur=c.cursor()
    for col in ["shares_source_url","marketcap_source_url"]:
        cur.execute(f"ALTER TABLE sp500_financials ADD COLUMN IF NOT EXISTS {col} text")
    cur.execute("""SELECT DISTINCT symbol, cik FROM sp500_financials
                   WHERE cik IS NOT NULL AND (shares_outstanding IS NULL OR market_cap IS NULL)
                   ORDER BY symbol""")
    comps=cur.fetchall()
    if LIMIT: comps=comps[:LIMIT]
    print(f"companies to bulk-fill: {len(comps)}", flush=True)
    tot_sh=tot_mc=0
    for i,(sym,cik) in enumerate(comps,1):
        shares=sec_shares(cik)
        daily=stooq_daily(sym) if shares else {}
        cur.execute("SELECT fiscal_year, period_end, shares_outstanding, market_cap FROM sp500_financials WHERE symbol=%s AND cik=%s",(sym,str(cik)))
        for fy,pend,sh_ex,mc_ex in cur.fetchall():
            sh_val,sh_url=shares.get(fy,(None,None))
            # fill shares
            if sh_ex is None and sh_val:
                cur.execute("UPDATE sp500_financials SET shares_outstanding=%s, shares_source_url=COALESCE(shares_source_url,%s) WHERE symbol=%s AND cik=%s AND fiscal_year=%s",
                            (int(sh_val),sh_url,sym,str(cik),fy)); tot_sh+=cur.rowcount
            # market cap = yearend close x shares (existing or just-filled)
            use_sh = sh_ex if sh_ex is not None else (int(sh_val) if sh_val else None)
            if mc_ex is None and use_sh and daily:
                close,cdate=yearend_close(daily,pend,fy)
                if close:
                    mc=close*use_sh
                    murl=f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d (close {cdate}) x shares"
                    cur.execute("UPDATE sp500_financials SET market_cap=%s, marketcap_source_url=COALESCE(marketcap_source_url,%s) WHERE symbol=%s AND cik=%s AND fiscal_year=%s",
                                (mc,murl,sym,str(cik),fy)); tot_mc+=cur.rowcount
        if i%50==0: print(f"  {i}/{len(comps)}  filled shares={tot_sh} mcap={tot_mc}", flush=True)
    cur.execute("SELECT round(100.0*count(shares_outstanding)/count(*)), round(100.0*count(market_cap)/count(*)), count(*) FROM sp500_financials")
    print("DONE. shares filled:",tot_sh,"| market_cap filled:",tot_mc)
    print("sp500_financials coverage now (shares%, market_cap%, rows):",cur.fetchone())
    c.close()

if __name__=="__main__":
    main()
