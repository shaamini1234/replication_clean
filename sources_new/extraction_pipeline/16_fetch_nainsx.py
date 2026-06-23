#!/usr/bin/env python3
"""
Step 16 — Fetch the REAL outturn for NAINSx from ONS (NFYO + M9WF).

RUN THIS ON A MACHINE THAT CAN REACH ONS (your laptop) — not the assistant sandbox.
Idempotent: re-running re-fetches and overwrites the same rows.

WHY THIS EXISTS
---------------
NAINSx = "Net acquisition of insurance/pension assets (unadjusted): households".
The OBR master sheet gives it an ONS source: NFYO + M9WF. Earlier, step 08 generated
NAINSx instead by running the OBR's AR(1) forecast equation
    NAINSx = 13293.71 + 0.627*NAINSx(-1) - 236267.3*(SIPT(-3)/100)
with a steady-state seed for ALL quarters. That is why it ended up flagged "synthetic"
and was removed on 2026-06-23. This step replaces that proxy with the real ONS outturn.

WHAT IT DOES
------------
  1. fetches NFYO and M9WF from ONS, sums them (NAINSx = NFYO + M9WF)
  2. converts to model units: money £m -> £bn (x0.001)
  3. writes BOTH columns: value_source (raw £m) and value (£bn); source='ONS', ons_scale=1.0
  4. prints a magnitude check (expect ~£20-30bn / quarter, i.e. raw ~20,000-30,000)

AFTER RUNNING
-------------
  - NAINS = NAINSx + NAINSADJ  (NAINSADJ is already in the DB) — recompute or compute directly.
  - HHRES, OAHHADJ are identities (model lines 822, 824); they regenerate in the recompute pass.
  - FORECAST period: the model's AR(1) equation (line 791) produces the forward path.
    *** ECONOMIST NOTE: that equation's constant (13293.71) and SIPT coefficient (236267.3) are
        calibrated in £m. With NAINSx stored in £bn they must be divided by 1000
        (-> 13.29371 and 236.2673), otherwise the forecast will be ~1000x the outturn.
        This is a C13-type unit fix in the model code. ***

Requires: requests, openpyxl (already used by the project).
Usage:    python 16_fetch_nainsx.py
"""
import os, sys, re, time, shutil, sqlite3


def _find_repo():
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
PUB     = 'ONS'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}

VAR     = 'NAINSx'
FORMULA = 'NFYO+M9WF'      # OBR master-sheet source for NAINSx
SCALE   = 0.001            # £m -> £bn (household financial-account flow)
LABEL   = ('Net acquisition of insurance/pension assets (unadjusted): HH (NSA); '
           'ONS NFYO+M9WF; value=£bn, value_source=raw £m. Forecast via AR(1) eq (line 791).')

# ONS dataset-path discovery (mirrors step 10 / fetch_all_ons.py)
GDP='/economy/grossdomesticproductgdp'; PSF='/economy/governmentpublicsectorandtaxes/publicsectorfinance'
SPEND='/economy/governmentpublicsectorandtaxes/publicspending'; BOP='/economy/nationalaccounts/balanceofpayments'
SAT='/economy/nationalaccounts/satelliteaccounts'; USA='/economy/nationalaccounts/uksectoraccounts'
PRICES='/economy/inflationandpriceindices'; TRADE='/businessindustryandtrade/internationaltrade'
ALL_PATHS=[USA, BOP, GDP, PSF, SPEND, SAT, PRICES, TRADE]   # NFYO/M9WF live under UK sector accounts


def discover_path(code):
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
    print(f'    !! no path found for {code} — add it to ONS_PATHS manually')
    return None


def ensure_schema(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(observations)")]
    if 'value_source' not in cols:
        con.execute("ALTER TABLE observations ADD COLUMN value_source REAL")
    scols = [r[1] for r in con.execute("PRAGMA table_info(series)")]
    if 'source_scale' not in scols:
        con.execute("ALTER TABLE series ADD COLUMN source_scale REAL DEFAULT 1.0")


def write_series(con, raw):
    con.execute("""INSERT INTO series(id,label,unit,ons_code,ons_scale,source_scale)
                   VALUES(?,?,?,?,1.0,?)
                   ON CONFLICT(id) DO UPDATE SET label=excluded.label,
                       ons_code=excluded.ons_code, ons_scale=1.0, source_scale=excluded.source_scale""",
                (VAR, LABEL, '£bn', FORMULA, SCALE))
    n = 0
    for q, sv in sorted(raw.items()):
        if sv is None:
            continue
        con.execute("""INSERT INTO observations
            (series_id,source,publication_date,quarter,value,data_type,value_source)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(series_id,source,publication_date,quarter,data_type)
            DO UPDATE SET value=excluded.value, value_source=excluded.value_source""",
            (VAR, 'ONS', PUB, q, sv * SCALE, 'OUTTURN', sv))
        n += 1
    return n


def main():
    if not os.path.exists(DB):
        sys.exit(f'DB not found: {DB}')
    shutil.copy(DB, DB + '.bak')
    print(f'backup written: {DB}.bak\n')

    fetcher = ONSFetcher(VARS_XL)
    # ensure the fetcher knows the formula even if the sheet row is read differently
    try:
        fetcher._var_map[VAR] = fetcher._var_map.get(VAR) or FORMULA
    except Exception:
        pass

    for code in re.findall(r'[A-Z][A-Z0-9]{2,6}', FORMULA):
        discover_path(code)

    print(f'{VAR}  ({FORMULA})')
    raw = fetcher.fetch_variable(VAR)
    if not raw:
        sys.exit(f'    no data returned for {VAR} — check NFYO/M9WF paths on ONS and retry')

    con = sqlite3.connect(DB)
    ensure_schema(con)
    n = write_series(con, raw)
    con.commit()
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]

    vals = sorted((q, v) for q, v in raw.items() if v is not None)
    model_vals = [v * SCALE for _, v in vals]
    lo, hi = (round(min(model_vals), 2), round(max(model_vals), 2)) if model_vals else (None, None)
    con.close()

    print(f'    loaded {n} quarters; £bn range [{lo}, {hi}]')
    if vals:
        print(f'    first {vals[0][0]}={vals[0][1]:.0f} (£m) -> {vals[0][1]*SCALE:.2f} (£bn)')
        print(f'    last  {vals[-1][0]}={vals[-1][1]:.0f} (£m) -> {vals[-1][1]*SCALE:.2f} (£bn)')
    print(f'\nintegrity_check: {ic}')
    print('MAGNITUDE CHECK: NAINSx is INSURANCE only (pensions are NAPEN, separate), so expect a small')
    print('flow ~ -£5bn to +£10bn per quarter (raw ~ -5,000 to +10,000 £m). Negatives are normal.')
    print('Backup at timeseries.db.bak.')
    print('Next: NAINS = NAINSx + NAINSADJ; HHRES/OAHHADJ regenerate in the recompute pass.')


if __name__ == '__main__':
    main()
