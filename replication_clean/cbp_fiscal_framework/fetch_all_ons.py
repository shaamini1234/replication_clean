"""
Discover ONS category paths for all remaining OBR model variables,
add confirmed paths to ONS_PATHS, then fetch and store in the DB.

Run with: .venv/bin/python cbp_fiscal_framework/fetch_all_ons.py
"""

import os, sys, re, time, requests, openpyxl
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

BASE = 'https://www.ons.gov.uk'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
DELAY = 0.35

# ── Load existing paths ───────────────────────────────────────────────────────
from cbp_fiscal_framework.inputs.ons_fetcher import ONS_PATHS as EXISTING_PATHS

# ── Load all ONS codes from OBR spreadsheet ───────────────────────────────────
base_dir = os.path.dirname(os.path.abspath(__file__))
xlsx = os.path.join(base_dir, '..', 'docs', 'OBR_Model_Variables_March_2025.xlsx')
wb = openpyxl.load_workbook(xlsx, read_only=True)
ws = wb.active

# Collect simple single-code variables not already in EXISTING_PATHS
to_probe = {}  # code -> model_var
for row in ws.iter_rows(values_only=True):
    if not row or not row[2] or not row[3]:
        continue
    model_var = str(row[2]).strip()
    ons_code  = str(row[3]).strip()
    if ons_code in ('No Codes', 'Codes', 'ONS identifier code', ''):
        continue
    # Only simple single codes (not compound formulas)
    if re.fullmatch(r'[A-Z][A-Z0-9]{2,6}', ons_code) and ons_code not in EXISTING_PATHS:
        to_probe[ons_code] = model_var
wb.close()

print(f"Codes to probe: {len(to_probe)}")
print(f"Already in ONS_PATHS: {len(EXISTING_PATHS)}")

# ── Path candidates ordered by likelihood per code prefix ────────────────────
GDP      = '/economy/grossdomesticproductgdp'
PSF      = '/governmentpublicsectorandtaxes/publicsectorfinance'
BOP      = '/economy/nationalaccounts/balanceofpayments'
SAT      = '/economy/nationalaccounts/satelliteaccounts'
PRICES   = '/economy/inflationandpriceindices'
TRADE    = '/businessindustryandtrade/internationaltrade'
EMPL_EE  = '/employmentandlabourmarket/peopleinwork/employmentandemployeetypes'
EMPL_EW  = '/employmentandlabourmarket/peopleinwork/earningsandworkinghours'
EMPL_PS  = '/employmentandlabourmarket/peopleinwork/publicsectorpersonnel'
INVEST   = '/economy/investmentspensionsandtrusts'

ALL_PATHS = [GDP, PSF, BOP, SAT, PRICES, TRADE, EMPL_EE, EMPL_EW, EMPL_PS, INVEST]

def path_priority(code):
    """Return ordered list of paths to try based on code prefix."""
    c = code[:2]
    if c in ('NM','AN','CA','AB','FL','GI','NP','DT','DW','YB'):
        return [GDP, PSF] + [p for p in ALL_PATHS if p not in (GDP, PSF)]
    if c in ('JW','NK','GZ','GC','CG','LI','LS','AD','AB') or code.startswith('JX'):
        return [PSF, GDP] + [p for p in ALL_PATHS if p not in (PSF, GDP)]
    if c in ('HL','HB','IK','HE','XB','N2','NY'):
        return [BOP, GDP] + [p for p in ALL_PATHS if p not in (BOP, GDP)]
    if c in ('RP','NN','NF','NZ','SS'):
        return [SAT, GDP] + [p for p in ALL_PATHS if p not in (SAT, GDP)]
    if c in ('QW','G6','L8','M9','CX'):
        return [EMPL_PS, EMPL_EW, EMPL_EE] + [p for p in ALL_PATHS if p not in (EMPL_PS, EMPL_EW, EMPL_EE)]
    if c in ('AC','CU','EY','DB','ZA','RU','KI','KW','JT','LI','EP','CC','DH','E8','GR','FC'):
        return [GDP, PSF] + [p for p in ALL_PATHS if p not in (GDP, PSF)]
    if c in ('IK','BQ','BO','BK','EL'):
        return [BOP, TRADE] + [p for p in ALL_PATHS if p not in (BOP, TRADE)]
    return ALL_PATHS

# ── Probe ────────────────────────────────────────────────────────────────────
found = {}   # code -> path
failed = []

for i, (code, model_var) in enumerate(to_probe.items()):
    paths = path_priority(code)
    success = False
    for path in paths:
        url = f'{BASE}{path}/timeseries/{code}/data'
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code == 200:
                qtrs = r.json().get('quarters', [])
                found[code] = path
                print(f"[{i+1}/{len(to_probe)}] ✓ {code:<8} ({model_var:<12}) {len(qtrs)} qtrs  {path[-40:]}")
                success = True
                break
            elif r.status_code == 502:
                time.sleep(0.5)
                r2 = requests.get(url, headers=HEADERS, timeout=12)
                if r2.status_code == 200:
                    qtrs = r2.json().get('quarters', [])
                    found[code] = path
                    print(f"[{i+1}/{len(to_probe)}] ✓ {code:<8} ({model_var:<12}) {len(qtrs)} qtrs  (retry) {path[-35:]}")
                    success = True
                    break
        except Exception:
            pass
        time.sleep(DELAY)

    if not success:
        failed.append((code, model_var))
        print(f"[{i+1}/{len(to_probe)}] ✗ {code:<8} ({model_var})")

print(f"\n{'='*60}")
print(f"Found: {len(found)}  Failed: {len(failed)}")

# ── Update ONS_PATHS in ons_fetcher.py ───────────────────────────────────────
fetcher_path = os.path.join(base_dir, 'inputs', 'ons_fetcher.py')
with open(fetcher_path) as f:
    content = f.read()

# Find the closing brace of ONS_PATHS dict and insert new entries before it
new_entries = "\n    # --- Auto-discovered paths ---\n"
for code, path in sorted(found.items()):
    new_entries += f"    '{code}': '{path}',\n"

# Insert before the last closing brace of ONS_PATHS
insert_marker = "    'BQKO': '/economy/nationalaccounts/balanceofpayments',\n}"
if insert_marker in content:
    # BQKO is last entry, insert after it
    new_content = content.replace(
        insert_marker,
        insert_marker.rstrip('\n}') + "\n" + new_entries + "}"
    )
else:
    # Find closing brace of ONS_PATHS
    new_content = content.replace(
        "\n    'BQKO': '/economy/nationalaccounts/balanceofpayments',\n}",
        "\n    'BQKO': '/economy/nationalaccounts/balanceofpayments',\n" + new_entries + "}"
    )

with open(fetcher_path, 'w') as f:
    f.write(new_content)
print(f"Updated ONS_PATHS in {fetcher_path}")

# ── Fetch and store in DB ────────────────────────────────────────────────────
from cbp_fiscal_framework.db.timeseries_db import TimeSeriesDB

db = TimeSeriesDB(os.path.join(base_dir, '..', 'cbp_fiscal_framework', 'db', 'timeseries.db'))
result = db.build_ons_mirrors()
db.close()

cov_rows = []
import sqlite3
conn = sqlite3.connect(os.path.join(base_dir, '..', 'cbp_fiscal_framework', 'db', 'timeseries.db'))
row = conn.execute("SELECT COUNT(DISTINCT series_id) n_series, COUNT(*) n_obs FROM observations WHERE source='ONS'").fetchone()
conn.close()

print(f"\nDatabase after fetch:")
print(f"  ONS series:       {row[0]}")
print(f"  ONS observations: {row[1]}")
print(f"\nFailed codes (not found on ONS website):")
for code, var in failed:
    print(f"  {code:<8} ({var})")
print("\nDone.")
