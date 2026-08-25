#!/usr/bin/env python3
"""
ftse_fundamentals_fetch.py — fetch revenue / net income / total assets for FTSE
100 firms from Yahoo Finance (the gap the CH bulk accounts can't fill for large
listed companies).

Run locally (needs internet):
    pip install yfinance
    python3 ftse_fundamentals_fetch.py

Writes ftse100_fundamentals into local business_dynamism. Provenance per row:
source = 'yahoo_finance', source_url = the Yahoo financials page. Captures the
REPORTED CURRENCY per firm (some FTSE giants — BP, Shell, GSK — report in USD),
so values are never silently mixed. Yahoo gives ~4 recent years only; older
history would need another source (documented limit).
"""
import time
import psycopg2
import yfinance as yf

PG = dict(dbname="business_dynamism", host="/tmp")   # local Postgres.app socket

conn = psycopg2.connect(**PG)
conn.autocommit = True
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS ftse100_fundamentals(
    company_number text, ticker text, fiscal_year int,
    revenue numeric, net_income numeric, total_assets numeric,
    currency text, source text, source_url text,
    fetched_at timestamptz default now(),
    PRIMARY KEY (ticker, fiscal_year))""")

cur.execute("SELECT ticker, company_number FROM ftse100_mapping WHERE ticker IS NOT NULL")
targets = cur.fetchall()
print(f"fetching fundamentals for {len(targets)} FTSE tickers...")

def val(df, *names):
    if df is None or df.empty:
        return {}
    for n in names:
        if n in df.index:
            return {c.year: df.loc[n, c] for c in df.columns}
    return {}

ok = 0
for tic, cn in targets:
    ysym = tic if tic.endswith(".L") else tic + ".L"
    try:
        t = yf.Ticker(ysym)
        inc = t.income_stmt
        bs  = t.balance_sheet
        ccy = (t.info or {}).get("financialCurrency")
        rev = val(inc, "Total Revenue", "TotalRevenue")
        ni  = val(inc, "Net Income", "NetIncome")
        ta  = val(bs,  "Total Assets", "TotalAssets")
        years = set(rev) | set(ni) | set(ta)
        url = f"https://finance.yahoo.com/quote/{ysym}/financials"
        for y in sorted(years):
            def g(d):
                v = d.get(y)
                return float(v) if v is not None and v == v else None
            cur.execute("""INSERT INTO ftse100_fundamentals
                (company_number,ticker,fiscal_year,revenue,net_income,total_assets,currency,source,source_url)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'yahoo_finance',%s)
                ON CONFLICT (ticker,fiscal_year) DO UPDATE SET
                  revenue=EXCLUDED.revenue, net_income=EXCLUDED.net_income,
                  total_assets=EXCLUDED.total_assets, currency=EXCLUDED.currency,
                  source_url=EXCLUDED.source_url, fetched_at=now()""",
                (cn, ysym, y, g(rev), g(ni), g(ta), ccy, url))
        ok += 1
        if ok % 20 == 0:
            print(f"  {ok}/{len(targets)} done")
        time.sleep(0.5)   # be gentle
    except Exception as e:
        print(f"  {ysym}: skip ({str(e)[:60]})")

cur.execute("SELECT count(*), count(distinct ticker), min(fiscal_year), max(fiscal_year) FROM ftse100_fundamentals")
print("ftse100_fundamentals rows / firms / yr range:", cur.fetchone())
cur.execute("SELECT currency, count(*) FROM ftse100_fundamentals GROUP BY 1 ORDER BY 2 DESC")
print("currencies:", cur.fetchall())
conn.close()
