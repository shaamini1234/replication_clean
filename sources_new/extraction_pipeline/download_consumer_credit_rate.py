#!/usr/bin/env python3
"""
Download the BoE consumer-credit effective interest rate straight from the Bank of England
database (no clicking through monthly pages), and save it where 16_build_diphhuf.py expects.

The BoE interactive database serves any series as CSV via its IADB endpoint. You just need the
SERIES CODE. The likely one for the OUTSTANDING effective rate on interest-charging consumer
credit (excl. student loans) is below — CONFIRM it on the BoE site (the series description),
and change SERIES_CODE if needed.

Run on a machine that can reach the BoE:
    python sources_new/extraction_pipeline/download_consumer_credit_rate.py
Then run 16_build_diphhuf.py.
"""
import os, sys, requests

# ---- the BoE series code for the consumer-credit effective rate (CONFIRM on the BoE site) ----
SERIES_CODE = 'CFMHSCV'     # outstanding, interest-charging consumer credit excl. student loans
# alternatives you might see: CFMHSDE (new business), or the credit-card / personal-loan codes.

def _find_repo():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(d, 'timeseries.db')):
            return d
        d = os.path.dirname(d)
    raise SystemExit('Could not locate repo root (needs timeseries.db)')

REPO = _find_repo()
OUT  = os.path.join(REPO, 'sources_new', 'raw_data', 'timeseries', 'boe', 'consumer_credit_rate.csv')

URL = ('https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp'
       '?csv.x=yes&Datefrom=01/Jan/1999&Dateto=now'
       f'&SeriesCodes={SERIES_CODE}&CSVF=TT&UsingCodes=Y&VPD=Y&VFD=N')

def main():
    print(f'Fetching BoE series {SERIES_CODE} ...')
    r = requests.get(URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    r.raise_for_status()
    text = r.text
    # sanity: a CSV should have commas and date-like rows, not an HTML error page
    if '<html' in text.lower() or 'DATE' not in text.upper():
        sys.exit('Response did not look like CSV — the series code or endpoint may be wrong.\n'
                 'Check SERIES_CODE against the BoE site, or just download the April-2026 '
                 'Effective interest rates Excel manually and save it as the CSV instead.')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write(text)
    lines = [l for l in text.splitlines() if l.strip()]
    print(f'Saved {len(lines)} lines to {OUT}')
    print('First rows:')
    for l in lines[:4]:
        print('  ', l[:80])
    print('\nNow run: python sources_new/extraction_pipeline/16_build_diphhuf.py')

if __name__ == '__main__':
    main()
