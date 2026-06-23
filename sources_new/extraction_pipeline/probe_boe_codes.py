#!/usr/bin/env python3
"""
Probe a handful of candidate BoE series codes for the HOUSEHOLD consumer-credit interest rate.
For each code it prints the official description and the value range, so we can pick the right
one (consumer credit / credit cards, OUTSTANDING, values ~6-22%) instead of hunting the website.

Run:  python sources_new/extraction_pipeline/probe_boe_codes.py
Then paste the output back.
"""
import requests

# candidate codes (mix of 'quoted household rates' IUM* and 'effective rates' CFM*).
# We verify by the DESCRIPTION the BoE returns, not by guessing blindly.
CANDIDATES = {
    'IUMCCTL': 'guess: credit card quoted rate',
    'IUMHPTL': 'guess: personal loan quoted rate',
    'IUMODTL': 'guess: overdraft quoted rate',
    'IUMBX67': 'guess: consumer credit (other) rate',
    'CFMHSDE': 'guess: household consumer credit effective rate',
    'CFMZJ3B': 'guess: consumer credit effective rate (alt)',
    'CFMHSCV': 'control: known to be sight DEPOSITS (should look low)',
}

def url(code):
    return ('https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp'
            f'?csv.x=yes&Datefrom=01/Jan/1999&Dateto=now&SeriesCodes={code}'
            '&CSVF=TT&UsingCodes=Y&VPD=Y&VFD=N')

def main():
    for code, note in CANDIDATES.items():
        try:
            t = requests.get(url(code), headers={'User-Agent': 'Mozilla/5.0'}, timeout=30).text
        except Exception as e:
            print(f'{code}: request failed ({e})'); continue
        if '<html' in t.lower() or 'DATE' not in t.upper():
            print(f'{code}: no data / invalid code   [{note}]'); continue
        lines = [l for l in t.splitlines() if l.strip()]
        desc = ''
        vals = []
        for l in lines:
            parts = l.split(',')
            if len(parts) >= 2 and parts[0].strip().upper() == code:
                desc = parts[1].strip().strip('"')[:90]
            try:
                vals.append(float(parts[-1]))
            except (ValueError, IndexError):
                pass
        rng = f'[{min(vals):.2f}, {max(vals):.2f}]%' if vals else '(no values)'
        print(f'{code}: {rng}\n     desc: {desc}\n     ({note})')

if __name__ == '__main__':
    main()
