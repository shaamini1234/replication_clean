#!/usr/bin/env python3
"""
Fetch the 9 ONS-coded empty model variables and load them into timeseries.db.

RUN THIS ON A MACHINE THAT CAN REACH ONS (e.g. your laptop) — not the sandbox.
It is idempotent: re-running re-fetches and overwrites the same rows.

What it does, per variable:
  1. reads the ONS formula from docs/OBR_Model_Variables_March_2025.xlsx
  2. discovers each component code's ONS dataset path if not already known
  3. fetches + computes the series via the existing ONSFetcher (handles A+B, A-B, 100*(A/B))
  4. converts to MODEL UNITS (money £m->£bn; indices left as-is)
  5. writes BOTH columns: value_source (raw) and value (model units); ons_scale=1.0
  6. prints a magnitude check for you to eyeball before trusting it

Requires: requests, openpyxl (already used by the project).

Usage:
    python fetch_ons_coded_empties.py
"""
import os, sys, re, time, shutil, sqlite3

def _find_repo():
    """Locate the repo root (works whether this script sits at root or in a subfolder)."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(d, 'timeseries.db')) and os.path.isdir(os.path.join(d, 'cbp_fiscal_framework')):
            return d
        d = os.path.dirname(d)
    raise SystemExit('Could not locate repo root (needs timeseries.db + cbp_fiscal_framework alongside it)')

REPO = _find_repo()
sys.path.insert(0, REPO)

import requests
from cbp_fiscal_framework.inputs.ons_fetcher import ONSFetcher, ONS_PATHS, ONS_BASE

DB      = os.path.join(REPO, 'timeseries.db')
VARS_XL = os.path.join(REPO, 'docs', 'OBR_Model_Variables_March_2025.xlsx')
PUB     = 'ONS'          # publication_date tag used for ONS rows
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}

# model-unit conversion factor applied to the raw ONS value:
#   money series are published in £m and the model wants £bn  -> 0.001
#   index series (deflator, CPI) are already in model units   -> 1.0
TARGETS = {
    'CDUR':        0.001,   # durable consumption (CVM), £m -> £bn
    'PCDUR':       1.0,     # consumer durables deflator = 100*(UTIB/UTID), index
    'CPIPRIVRENT': 1.0,     # CPI private rents (KYHJ), index
    'CGISC':       0.001,   # CG imputed social contributions, £m -> £bn
    'HHTA':        0.001,   # HH transfer payments abroad, £m -> £bn
    'RLCOTC':      0.001,   # reduced-liability company tax credits, £m -> £bn
    'VTRCS':       0.001,   # VTR & other reliefs, £m -> £bn
    'WFTCNT':      0.001,   # WFTC negative tax, £m -> £bn
    'MILAPME':     0.001,   # MIRAS/LAPRAS/PMI, £m -> £bn
}

# ── ONS dataset path discovery (mirrors fetch_all_ons.py) ─────────────────────
GDP='/economy/grossdomesticproductgdp'; PSF='/economy/governmentpublicsectorandtaxes/publicsectorfinance'
SPEND='/economy/governmentpublicsectorandtaxes/publicspending'; BOP='/economy/nationalaccounts/balanceofpayments'
SAT='/economy/nationalaccounts/satelliteaccounts'; USA='/economy/nationalaccounts/uksectoraccounts'
PRICES='/economy/inflationandpriceindices'; TRADE='/businessindustryandtrade/internationaltrade'
EMP_EE='/employmentandlabourmarket/peopleinwork/employmentandemployeetypes'
EMP_EW='/employmentandlabourmarket/peopleinwork/earningsandworkinghours'
ALL_PATHS=[GDP,PSF,SPEND,BOP,SAT,USA,PRICES,TRADE,EMP_EE,EMP_EW]

def discover_path(code):
    """Return the ONS dataset path for a code by probing candidates, or None."""
    if code in ONS_PATHS:
        return ONS_PATHS[code]
    for path in ALL_PATHS:
        url = f'{ONS_BASE}{path}/timeseries/{code}/data'
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200 and (r.json().get('quarters') or r.json().get('years')):
                ONS_PATHS[code] = path
                print(f'    discovered path for {code}: {path}')
                return path
        except Exception:
            pass
        time.sleep(0.3)
    print(f'    !! no path found for {code}')
    return None

def codes_in(formula):
    return [t for t in re.findall(r'[A-Z][A-Z0-9]{2,6}', formula) if not t.isdigit()]

# ── DB helpers (ensure the two-column schema exists, then write) ──────────────
def ensure_schema(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(observations)")]
    if 'value_source' not in cols:
        con.execute("ALTER TABLE observations ADD COLUMN value_source REAL")
    scols = [r[1] for r in con.execute("PRAGMA table_info(series)")]
    if 'source_scale' not in scols:
        con.execute("ALTER TABLE series ADD COLUMN source_scale REAL DEFAULT 1.0")

def write_series(con, var, raw, scale, label):
    """raw = {YYYYQN: source_value}; writes value_source=raw, value=raw*scale."""
    con.execute("""INSERT INTO series(id,label,unit,ons_code,ons_scale,source_scale)
                   VALUES(?,?,?,?,1.0,?)
                   ON CONFLICT(id) DO UPDATE SET label=excluded.label,
                       ons_scale=1.0, source_scale=excluded.source_scale""",
                (var, label, '£bn' if scale != 1.0 else 'index', '', scale))
    n = 0
    for q, sv in sorted(raw.items()):
        if sv is None:
            continue
        con.execute("""INSERT INTO observations
            (series_id,source,publication_date,quarter,value,data_type,value_source)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(series_id,source,publication_date,quarter,data_type)
            DO UPDATE SET value=excluded.value, value_source=excluded.value_source""",
            (var, 'ONS', PUB, q, sv * scale, 'OUTTURN', sv))
        n += 1
    return n

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    if not os.path.exists(DB):
        sys.exit(f'DB not found: {DB}')
    shutil.copy(DB, DB + '.bak')           # safety backup
    print(f'backup written: {DB}.bak\n')

    fetcher = ONSFetcher(VARS_XL)          # loads var->formula map from the OBR sheet
    con = sqlite3.connect(DB)
    ensure_schema(con)

    summary = []
    for var, scale in TARGETS.items():
        formula = fetcher._var_map.get(var)
        if not formula:
            print(f'{var}: no ONS formula in the OBR sheet — skipping'); continue
        print(f'{var}  ({formula})')
        for code in codes_in(formula):     # make sure every component has a path
            discover_path(code)
        raw = fetcher.fetch_variable(var)  # fetch + compute the formula
        if not raw:
            print(f'    no data returned — skipping\n'); summary.append((var,0,None,None)); continue
        n = write_series(con, var, raw, scale,
                         f'ONS-sourced ({formula}); value=model units, value_source=raw')
        vals = [v*scale for v in raw.values() if v is not None]
        lo, hi = (round(min(vals),3), round(max(vals),3)) if vals else (None,None)
        print(f'    loaded {n} quarters; model-unit range [{lo}, {hi}]\n')
        summary.append((var, n, lo, hi))

    con.commit()
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()

    print('='*64)
    print(f'{"variable":13}{"quarters":>10}   model-unit range  (CHECK THESE MAGNITUDES)')
    for var, n, lo, hi in summary:
        print(f'{var:13}{n:>10}   [{lo}, {hi}]')
    print(f'\nintegrity_check: {ic}')
    print('Backup at timeseries.db.bak. Eyeball the ranges above before trusting; '
          'money series should be plausible £bn, indices ~100-based.')

if __name__ == '__main__':
    main()
