"""
Phase 7: Download ONS stock data for Group 1 lag-chain variables.

These 9 variables have ONS series codes. Downloading historical data gives
the 2007Q4 seed values needed for the recursive equations to run in phase6.

Variables:
  AIC    = NKWX        (Stock of financial assets: PNFCs)
  BLIC   = NKZA        (Stock of bonds/MMI issued by PNFCs)
  EQLIC  = NLBU        (Stock of shares issued by PNFCs)
  PRENT  = DOBP        (Housing: Rent RPI)
  PSTA   = NG4K        (Public Sector Tangible Assets)
  STLIC  = NLBE-NLBG   (FINCO sterling bank lending to PNFCs)
  FXLIC  = NLBG+NLBI   (FX bank lending to PNFCs)
  OLIC   = NLCO+(NLBC-NLBE-NLBI)+MMX4+M9VL (Other financial liabilities)
  ECNET  = -(FKKL+FKIJ) (Net EC contributions, BoP basis)

Run from repo root:
    python shaamini_tests/phase7_ons_stocks.py
"""

import os, sys, sqlite3, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'timeseries_p5.db')
VARS_XLSX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'docs', 'OBR_Model_Variables_March_2025.xlsx'
)

from cbp_fiscal_framework.inputs.ons_fetcher import ONSFetcher, ONS_PATHS

# ── Extend ONS_PATHS with codes not yet mapped ───────────────────────────────
EXTRA_PATHS = {
    # PRENT
    'DOBP': '/economy/inflationandpriceindices',
    # STLIC, FXLIC, OLIC components — NL** series live under GDP national accounts
    'NLBE': '/economy/grossdomesticproductgdp',
    'NLBG': '/economy/grossdomesticproductgdp',
    'NLBI': '/economy/grossdomesticproductgdp',
    # OLIC additional components
    'NLCO': '/economy/nationalaccounts/uksectoraccounts',
    'NLBC': '/economy/nationalaccounts/uksectoraccounts',
    'MMX4': '/economy/nationalaccounts/uksectoraccounts',
    'M9VL': '/economy/grossdomesticproductgdp',  # annual only; fetcher spreads to quarters
    # ECNET components (Balance of Payments)
    'FKKL': '/economy/nationalaccounts/balanceofpayments',
    'FKIJ': '/economy/nationalaccounts/balanceofpayments',
    # TYWHH components
    'RPHS': '/economy/grossdomesticproductgdp',
    'RPHT': '/economy/grossdomesticproductgdp',
    # SAVCO components
    'RPKZ': '/economy/grossdomesticproductgdp',
    'RPPS': '/economy/grossdomesticproductgdp',
    # SA components
    'DLRA': '/economy/grossdomesticproductgdp',
    'EQCB': '/economy/grossdomesticproductgdp',
    # PMS components (import price index — unlocks 10 cost vars)
    'IKBC': '/economy/nationalaccounts/balanceofpayments',
    # IKBF already in ONS_PATHS at /economy/grossdomesticproductgdp
    # CGNB, PCNBCY components
    'NMFJ': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'RQBN': '/economy/grossdomesticproductgdp',
    # PSLSFA, PSACADJ components (public sector balance sheet)
    'JW33': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW34': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW35': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW36': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    'JW37': '/economy/governmentpublicsectorandtaxes/publicsectorfinance',
    # NMTRHH components
    'RPHO': '/economy/grossdomesticproductgdp',
    'RPID': '/economy/grossdomesticproductgdp',
    # ALROW, NABLROW, NAEQLROW, NADLROW components (rest-of-world financial accounts)
    'HBNR': '/economy/nationalaccounts/balanceofpayments',
    'XBMW': '/economy/nationalaccounts/balanceofpayments',
    'HBVI': '/economy/nationalaccounts/balanceofpayments',
    'N2SV': '/economy/nationalaccounts/balanceofpayments',
    # NGAS (needed for DEBTU)
    'NGAS': '/economy/grossdomesticproductgdp',
    # Consumer durables (CDURPS, CDUR)
    'UTIB': '/economy/nationalaccounts/satelliteaccounts',
    'UTID': '/economy/nationalaccounts/satelliteaccounts',
}
ONS_PATHS.update(EXTRA_PATHS)

# ── Target variables and their ONS formulae ───────────────────────────────────
# (taken from OBR_Model_Variables_March_2025.xlsx ONS identifier column)
TARGETS = {
    'AIC':     'NKWX',
    'BLIC':    'NKZA',
    'EQLIC':   'NLBU',
    'PRENT':   'DOBP',
    'PSTA':    'NG4K',
    'STLIC':   'NLBE-NLBG',
    'FXLIC':   'NLBG+NLBI',
    'OLIC':    'NLCO+(NLBC-NLBE-NLBI)+MMX4+M9VL',
    'ECNET':   '-FKKL-FKIJ',
    # Tax variables with ONS codes
    'NATAXES': 'GCSU',
    'FYCPR':   'CAED+CAGD+RITQ',
    'TYWHH':   'RPHS+RPHT',
    # Import price index — unlocks CCOST/ICOST/MCOST/RPCOST/SCOST/UTCOST/XGCOST/XSCOST/PMSBASE/PMSREL
    'PMS':     '100*(IKBC/IKBF)',
    # Household/corporate savings and assets
    'SAVCO':   'RPKZ+RPPS',
    'SA':      'DLRA+EQCB',
    # Public sector balance sheet
    'PSNW':    'CGTY',
    'PSLSFA':  'JW33+JW34',
    'PSACADJ': 'JW35+JW36+JW37',
    # PNFC financial stocks (already mapped)
    'LIC':     'NLBB',
    'NWIC':    'NYOT',
    # Cyclically-adjusted / fiscal
    'CGNB':    '-NMFJ',
    'PCNBCY':  '-RQBN',
    # Household mortgage repayments
    'NMTRHH':  'RPHO-RPID',
    # Rest-of-world financial accounts
    'ALROW':   '-HBNR',
    'NABLROW':  '-XBMW',
    'NAEQLROW': '-HBVI',
    'NADLROW':  '-N2SV',
    # Consumer durables: direct ONS series
    'CDURPS':  'UTIB',   # HH final consumption: durable goods (CP)
}

# ── Fetch ─────────────────────────────────────────────────────────────────────
print("Phase 7: Fetching ONS stock series")
print(f"  {len(TARGETS)} variables to fetch")
print()

fetcher = ONSFetcher()

results = {}
for var, formula in TARGETS.items():
    print(f"  Fetching {var} ({formula}) ...", end=' ', flush=True)
    # Extract raw codes and fetch each
    codes = fetcher._extract_codes(formula)
    all_dates = set()
    ok = True
    for code in codes:
        series = fetcher.fetch(code)
        if not series:
            print(f"FAILED (no data for {code})")
            ok = False
            break
        all_dates |= set(series.keys())
        time.sleep(0.3)

    if not ok:
        results[var] = {}
        continue

    # Compute formula for all dates
    computed = {}
    for d in sorted(all_dates):
        v = fetcher.compute_formula(formula, d)
        if v is not None:
            computed[d] = v

    n = len(computed)
    if n > 0:
        dates_sorted = sorted(computed.keys())
        print(f"OK — {n} quarters ({dates_sorted[0]} → {dates_sorted[-1]})")
    else:
        print("FAILED — formula evaluated to no values")
    results[var] = computed

print()

# ── Write to DB (via /tmp to work around virtiofs write limitation) ───────────
import shutil, tempfile

WORK_DB = '/tmp/timeseries_p5_phase7.db'
print(f"Copying DB to {WORK_DB} for writing ...")
shutil.copy(DB_PATH, WORK_DB)

conn = sqlite3.connect(WORK_DB)
existing_series = {r[0] for r in conn.execute("SELECT id FROM series").fetchall()}

inserted = 0
skipped  = 0

for var, qmap in results.items():
    if not qmap:
        skipped += 1
        continue

    if var not in existing_series:
        conn.execute(
            "INSERT OR IGNORE INTO series (id, label, ons_scale) VALUES (?, ?, ?)",
            (var, f'ONS: {var} ({TARGETS[var]})', 1.0)
        )

    for quarter, value in sorted(qmap.items()):
        exists = conn.execute(
            "SELECT 1 FROM observations WHERE series_id=? AND quarter=? AND source='ONS'",
            (var, quarter)
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO observations
                   (series_id, source, publication_date, quarter, value, data_type)
                   VALUES (?, 'ONS', '2026-03', ?, ?, 'OUTTURN')""",
                (var, quarter, value)
            )
            inserted += 1

conn.commit()
conn.close()

print(f"  Inserted {inserted} new rows across {len([v for v in results.values() if v])} variables")
print(f"  {skipped} variables had no data")

# Copy working DB back to mounted path
print(f"Copying {WORK_DB} → {DB_PATH} ...")
shutil.copy(WORK_DB, DB_PATH)
print("  Done.")
print()

# ── Summary ───────────────────────────────────────────────────────────────────
print("Coverage summary:")
for var, qmap in sorted(results.items()):
    if qmap:
        dates = sorted(qmap.keys())
        # Check if 2007Q4 is covered (needed to seed 2008Q1)
        has_seed = '2007Q4' in qmap
        seed_note = "✓ 2007Q4 seed" if has_seed else "✗ no 2007Q4 seed"
        print(f"  {var:<8} {len(qmap):>4} quarters ({dates[0]}–{dates[-1]})  {seed_note}")
    else:
        print(f"  {var:<8}   NO DATA")
print()
print("Done. Re-run phase6_compute_derived.py to propagate into forecast period.")
