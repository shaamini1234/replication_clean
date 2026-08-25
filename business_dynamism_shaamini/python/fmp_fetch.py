#!/usr/bin/env python3
"""
fmp_fetch.py — pull annual revenue / net income / total assets from Financial
Modeling Prep and upsert into Neon, with a source_url on every value.

  FTSE: uses the .L tickers already in ftse100_fundamentals (yfinance gave us
        only 2021-2026; FMP backfills the full annual history).
  S&P : optionally gap-fills sp500_financials where our value is NULL.

Provenance: every row gets source='FMP' and source_url = the exact FMP endpoint.
Nothing is estimated. Fill-where-null only for S&P (never overwrites a good value).

Run:
  pip install requests psycopg2-binary
  FMP_KEY=PASTE_KEYHERE python3 fmp_fetch.py            # FTSE only
  FMP_KEY=PASTE_KEYHERE python3 fmp_fetch.py --sp500     # also gap-fill S&P

Note: FMP's free tier is often US-only. If FTSE (.L) rows come back empty, that's
a plan limit, not a bug — the per-ticker log will show it plainly.
"""
import os, sys, time, requests, psycopg2, psycopg2.extras

KEY = os.environ.get("FMP_KEY", "PASTE_KEYHERE")
if KEY == "PASTE_KEYHERE":
    sys.exit("set FMP_KEY=your_key")
BASE = "https://financialmodelingprep.com/api/v3"
DO_SP = "--sp500" in sys.argv

PG = dict(host="ep-nameless-fire-atkh5lxj.c-9.us-east-1.aws.neon.tech", dbname="neondb",
          user="neondb_owner", password="npg_q1uDNWofte0n", sslmode="require", connect_timeout=25)

def get(path, **q):
    q["apikey"] = KEY
    url = f"{BASE}/{path}"
    r = requests.get(url, params=q, timeout=40)
    shown = url + "?" + "&".join(f"{k}={v}" for k, v in q.items() if k != "apikey")
    if r.status_code != 200:
        return [], shown
    try:
        j = r.json()
    except Exception:
        return [], shown
    if isinstance(j, dict) and j.get("Error Message"):
        return [], shown
    return (j if isinstance(j, list) else []), shown

def num(x):
    try:
        return None if x in (None, "") else float(x)
    except Exception:
        return None

def main():
    c = psycopg2.connect(**PG); c.autocommit = True; cur = c.cursor()

    # ---------- FTSE ----------
    cur.execute("SELECT ticker, max(company_number), max(currency) "
                "FROM ftse100_fundamentals GROUP BY ticker ORDER BY ticker")
    ftse = cur.fetchall()
    print(f"FTSE tickers to fetch from FMP: {len(ftse)}")
    ok = 0; rows = 0
    for ticker, cnum, cur_ccy in ftse:
        inc, inc_url = get(f"income-statement/{ticker}", period="annual", limit=40)
        time.sleep(0.3)
        bal, bal_url = get(f"balance-sheet-statement/{ticker}", period="annual", limit=40)
        time.sleep(0.3)
        assets = {str(b.get("calendarYear")): num(b.get("totalAssets")) for b in bal}
        got = 0
        for r in inc:
            fy = r.get("calendarYear")
            if not fy:
                continue
            fy = int(fy)
            rev, ni = num(r.get("revenue")), num(r.get("netIncome"))
            ta = assets.get(str(fy))
            ccy = r.get("reportedCurrency") or cur_ccy
            if rev is None and ni is None and ta is None:
                continue
            cur.execute("""
                INSERT INTO ftse100_fundamentals
                  (company_number,ticker,fiscal_year,revenue,net_income,total_assets,
                   currency,source,source_url,fetched_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'FMP',%s,now())
                ON CONFLICT (company_number,fiscal_year) DO UPDATE SET
                  revenue=coalesce(ftse100_fundamentals.revenue,EXCLUDED.revenue),
                  net_income=coalesce(ftse100_fundamentals.net_income,EXCLUDED.net_income),
                  total_assets=coalesce(ftse100_fundamentals.total_assets,EXCLUDED.total_assets),
                  currency=coalesce(ftse100_fundamentals.currency,EXCLUDED.currency),
                  source=coalesce(ftse100_fundamentals.source,'FMP'),
                  source_url=coalesce(ftse100_fundamentals.source_url,EXCLUDED.source_url),
                  fetched_at=now()
            """, (cnum, ticker, fy, rev, ni, ta, ccy, inc_url))
            got += 1; rows += 1
        if got:
            ok += 1
        print(f"  {ticker:10s} {got:3d} yrs")
    print(f"FTSE: {ok}/{len(ftse)} tickers returned data, {rows} firm-years upserted")

    # ---------- S&P gap-fill (free-tier friendly, US tickers) ----------
    if DO_SP:
        cur.execute("""SELECT DISTINCT symbol FROM sp500_financials
                       WHERE revenue IS NULL OR net_income IS NULL OR total_assets IS NULL
                       ORDER BY symbol""")
        syms = [r[0] for r in cur.fetchall()]
        print(f"S&P symbols with a NULL to fill: {len(syms)}")
        filled = 0
        for sym in syms:
            inc, inc_url = get(f"income-statement/{sym}", period="annual", limit=40)
            time.sleep(0.25)
            bal, _ = get(f"balance-sheet-statement/{sym}", period="annual", limit=40)
            time.sleep(0.25)
            assets = {str(b.get("calendarYear")): num(b.get("totalAssets")) for b in bal}
            for r in inc:
                fy = r.get("calendarYear")
                if not fy:
                    continue
                cur.execute("""UPDATE sp500_financials SET
                    revenue=coalesce(revenue,%s),
                    net_income=coalesce(net_income,%s),
                    total_assets=coalesce(total_assets,%s),
                    revenue_source_url=coalesce(revenue_source_url,%s),
                    net_income_source_url=coalesce(net_income_source_url,%s),
                    total_assets_source_url=coalesce(total_assets_source_url,%s)
                    WHERE symbol=%s AND fiscal_year=%s
                      AND (revenue IS NULL OR net_income IS NULL OR total_assets IS NULL)""",
                    (num(r.get("revenue")), num(r.get("netIncome")), assets.get(str(fy)),
                     inc_url, inc_url, inc_url, sym, int(fy)))
                filled += cur.rowcount
        print(f"S&P: {filled} rows touched by gap-fill")

    c.close()

if __name__ == "__main__":
    main()
