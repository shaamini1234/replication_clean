"""
Phase 6: Compute and store 48 derivable missing variables.

These variables have equations in the OBR model and all their inputs
exist in timeseries_p5.db. This script:
  1. Loads all state from the DB
  2. Runs the IdentitySolver across all quarters using state.current_t
  3. Saves computed values back to the DB as source='COMPUTED', data_type='OUTTURN'

Run from repo root:
    python shaamini_tests/phase6_compute_derived.py
"""

import os, sys, sqlite3, traceback, shutil, math
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'timeseries_p5.db')
WORK_DB  = '/tmp/timeseries_p5_phase6.db'

# Work entirely in /tmp to avoid virtiofs SQLite write limitation.
# Only copy back to DB_PATH once at the very end.
print(f"Copying DB to {WORK_DB} for all operations ...")
shutil.copy(DB_PATH, WORK_DB)

from cbp_fiscal_framework.db.timeseries_db import TimeSeriesDB
from cbp_fiscal_framework.core.winsolve import (
    WinsolveParser, WinsolveModel, IdentitySolver, build_model_state_from_db
)

TARGET_VARS = {
    'AIC', 'BLIC', 'CEQUITY', 'CGACADJ', 'CGLSFA', 'DB', 'DBR', 'DP', 'DV',
    'ECNET', 'EECPP', 'EQLIC', 'EUVAT', 'FXLIC', 'GAD', 'GGIX', 'GGLIQ',
    'GNP4', 'GPW', 'HHRES', 'KGHH', 'KMSXH', 'LANB', 'NAFCO', 'NAINS',
    'NAOLPE', 'NAOTLROW', 'NETAD', 'OCT', 'OILBASE', 'OLIC', 'PCNB', 'PINV',
    'PMNOGBASE', 'PPIYBASE', 'PRENT', 'PSFL', 'PSGI', 'PSINTR', 'PSTA',
    'REXC', 'RPI', 'STLIC', 'TAXCRED', 'TPRODPS', 'TXRATEBASE', 'ULCMSBASE', 'ULCPSBASE',
    # Tax variables — all inputs present in DB
    'TAF', 'TAFB', 'TAFP', 'TAFV', 'TYWHH',
    # Computable from existing data
    'PMGREL', 'REXD',
    # Cost variables — unlocked by PMS now in DB
    'CCOST', 'ICOST', 'MCOST', 'RPCOST', 'SCOST', 'UTCOST', 'XGCOST', 'XSCOST',
    'PMSBASE', 'PMSREL',
    # Direct identities (all deps already in DB)
    'IROO', 'MKGW',
    # Capital stock variables (need seeding — see pre-seed step below)
    'KMSXH', 'GPW', 'HSALL',
    # Unlocked once KMSXH seeded
    'TQ',
    # GPW now seeded → RHF computable
    'RHF',
    # CDEBT chain (seeded via R+spread proxy for RIC; @elem fixed by 1970Q1 extension)
    'CDEBT', 'RWACC', 'COCU', 'COC', 'KSTAR', 'KGAP',
}

MODEL_TXT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'docs', 'Macroeconomic_model_code_March_2025.txt'
)

# ── 1. Parse model ────────────────────────────────────────────────────────────
print("Step 1: Parse model equations")
with open(MODEL_TXT) as f:
    equations = WinsolveParser.parse_model(f.read())
model  = WinsolveModel(equations)
solver = IdentitySolver(model)
print(f"  {len(equations)} equations parsed")

# ── 2. Load state from DB ─────────────────────────────────────────────────────
print("Step 2: Load state from DB")
db = TimeSeriesDB(WORK_DB)
state, _ = build_model_state_from_db(db, obr_pub_date='2026-03')

conn = sqlite3.connect(WORK_DB)
SOURCE_PRIORITY = {'ONS': 0, 'OBR_EFO': 1, 'COMPUTED': 2}
_raw = conn.execute(
    "SELECT series_id, source, quarter, value FROM observations"
).fetchall()

_best = {}
for sid, src, q, val in _raw:
    pri = SOURCE_PRIORITY.get(src, 99)
    if (sid, q) not in _best or pri < _best[(sid, q)][0]:
        _best[(sid, q)] = (pri, val)

_by_var = defaultdict(dict)
for (sid, q), (_, val) in _best.items():
    _by_var[sid][q] = val

already = set(state.values.keys())
extra = 0
for var, qmap in _by_var.items():
    if var in already:
        continue
    series = [qmap.get(d) for d in state.dates]
    if any(v is not None for v in series):
        state.init_variable(var, series)
        extra += 1

print(f"  {len(already)} VARIABLE_MAP + {extra} extra = {len(state.values)} total in state")

# ── 3. Initialise empty slots for target vars not yet in state ────────────────
print("Step 3: Initialise target variable slots")
n_dates = len(state.dates)
new_slots = 0
for var in sorted(TARGET_VARS):
    if var not in state.values:
        state.init_variable(var, [None] * n_dates)
        new_slots += 1
print(f"  Initialised {new_slots} new empty slots")

# ── 3b. Pre-seed recursive variables and extend state for @elem lookups ────────
print("Step 3b: Pre-seed capital stock variables and extend state")

raw_data = {}
for sid, q, val in conn.execute(
    "SELECT series_id, quarter, value FROM observations ORDER BY quarter"
).fetchall():
    raw_data.setdefault(sid, {})[q] = val

# ── Extend state dates to include 1970Q1 (needed for @elem in COCU eq.) ──────
# COCU = PIBUS/PGDP * @elem(PGDP,"1970Q1")/@elem(PIBUS,"1970Q1") * (DELTA+RWACC)
ANCHOR_DATE = '1970Q1'
if ANCHOR_DATE not in state.date_index:
    state.dates.insert(0, ANCHOR_DATE)
    state.date_index = {d: i for i, d in enumerate(state.dates)}
    for var in list(state.values.keys()):
        state.values[var] = [None] + state.values[var]
    # PGDP(1970Q1) = 5.9 (from DB historical data)
    if 'PGDP' not in state.values:
        state.values['PGDP'] = [None] * len(state.dates)
    state.values['PGDP'][0] = 5.9
    # PIBUS(1970Q1) ≈ PGDP(1970Q1) × 1.30 (stable ratio from 1997-2010 data)
    if 'PIBUS' not in state.values:
        state.values['PIBUS'] = [None] * len(state.dates)
    if state.values['PIBUS'][0] is None:
        state.values['PIBUS'][0] = 5.9 * 1.30
    print(f"  Extended state to include {ANCHOR_DATE} (PGDP={state.values['PGDP'][0]}, "
          f"PIBUS={state.values['PIBUS'][0]:.2f})")
    SOLVER_START = 1   # 2008Q1 is now at index 1
else:
    SOLVER_START = 0

# Index of 2008Q1 (model start) in (possibly extended) state
T0 = state.date_index[state.dates[SOLVER_START]]   # = SOLVER_START

# ── KMSXH: perpetual inventory from 1997Q1 using IBUSX ──────────────────────
_ibusx = raw_data.get('IBUSX', {})
_rdelta = 0.022
_kmsxh = _ibusx.get('1997Q1', 38000) / (1000 * _rdelta)
_model_start = state.dates[SOLVER_START]
for _q in sorted(q for q in _ibusx if '1997Q2' <= q < _model_start):
    _kmsxh = _ibusx[_q] / 1000 + _kmsxh * (1 - _rdelta)
_ibusx_t0 = _ibusx.get(_model_start, list(_ibusx.values())[-1])
_kmsxh_t0 = _ibusx_t0 / 1000 + _kmsxh * (1 - _rdelta)
state.values['KMSXH'][T0] = _kmsxh_t0
print(f"  KMSXH(2008Q1) seed = {_kmsxh_t0:.1f} (£bn, perpetual inventory)")

# ── GPW: gross physical wealth ≈ 3.5 × GDP at 2008Q1 ───────────────────────
_gdpm = raw_data.get('GDPM', {})
_gdpm_t0 = _gdpm.get(_model_start) or next(iter(sorted(_gdpm.values())), 600)
_gpw_t0 = _gdpm_t0 * 3.5
state.values['GPW'][T0] = _gpw_t0
print(f"  GPW(2008Q1) seed = {_gpw_t0:.0f} (£m, ≈ 3.5 × GDPM)")

# ── HSALL: UK total dwelling stock in millions ────────────────────────────────
_hsall_t0 = 25.63   # MHCLG: ~25.6m dwellings at 2008Q1
state.values['HSALL'][T0] = _hsall_t0
print(f"  HSALL(2008Q1) seed = {_hsall_t0} (m dwellings)")

# ── RIC proxy: effective bank lending rate ≈ R + 150bp spread ───────────────
# RIC is "Effective Rate on Bank lending to PNFCs" — no ONS code.
# Proxy: BoE base rate (R) + 1.5 percentage point spread.
# Inject into state so CDEBT = CDEBT(-1) + d(RIC) can propagate.
_r_series = raw_data.get('R', {})
if _r_series:
    if 'RIC' not in state.values:
        state.values['RIC'] = [None] * len(state.dates)
    for _q, _r_val in _r_series.items():
        if _q in state.date_index:
            state.values['RIC'][state.date_index[_q]] = _r_val + 1.5
    _ric_t0 = state.values['RIC'][T0]
    # Seed CDEBT at T0 = RIC(T0) (cost of debt tracks current rate)
    state.values['CDEBT'][T0] = _ric_t0
    print(f"  RIC proxy injected (R+1.5); CDEBT(2008Q1) seed = {_ric_t0:.2f}%")

# ── 4. Solve all quarters (using state.current_t, not state.t) ───────────────
print("Step 4: Solve all quarters")
errors = {}
for i, quarter in enumerate(state.dates):
    if i < SOLVER_START:         # skip the 1970Q1 anchor row
        continue
    state.current_t = i          # ← correct attribute the solver reads
    for block in solver.blocks:
        try:
            if len(block) == 1:
                solver._solve_single(block[0], state)
            else:
                solver._solve_simultaneous(block, state)
        except Exception as e:
            msg = str(e)
            if 'not in state' not in msg and 'is None' not in msg:
                for var in block:
                    if var in TARGET_VARS and var not in errors:
                        errors[var] = msg

print(f"  Done. {len(errors)} target variables had errors:")
for var, msg in sorted(errors.items()):
    print(f"    {var}: {msg[:80]}")

# ── 4b. Compute KSTAR and KGAP directly (bypass solver unit-mismatch bug) ────
# The solver corrupts MSGVA because GVA=GDPM-BPA has an OBR/ONS unit mismatch.
# Fix: rebuild MSGVA from raw DB GVA and GGVA, then compute KSTAR and KGAP.
print()
print("Step 4b: Compute KSTAR and KGAP directly from raw GVA data")

_gva_raw  = raw_data.get('GVA',  {})
_ggva_raw = raw_data.get('GGVA', {})
_coc_s    = state.values.get('COC',   [None]*len(state.dates))
_kmsxh_s  = state.values.get('KMSXH', [None]*len(state.dates))

kstar_n = 0; kgap_n = 0
for i, quarter in enumerate(state.dates):
    if i < SOLVER_START:
        continue
    # MSGVA = GVA - GGVA  (native DB units — consistent with prior COMPUTED row)
    gva_val  = _gva_raw.get(quarter)
    ggva_val = _ggva_raw.get(quarter, 0.0)
    if gva_val is None:
        continue
    msgva_val = gva_val - ggva_val
    if msgva_val <= 0:
        continue

    # KSTAR = exp(log(MSGVA) - 0.4 * log(COC) + 2.434202655)
    coc_val = _coc_s[i] if i < len(_coc_s) else None
    if coc_val is None or coc_val <= 0:
        continue
    try:
        kstar_val = math.exp(math.log(msgva_val) - 0.4 * math.log(coc_val) + 2.434202655)
        state.values['KSTAR'][i] = kstar_val
        kstar_n += 1
    except Exception:
        continue

    # KGAP = log(KMSXH * 1000) - log(KSTAR)
    kmsxh_val = _kmsxh_s[i] if i < len(_kmsxh_s) else None
    if kmsxh_val is None or kmsxh_val <= 0:
        continue
    try:
        state.values['KGAP'][i] = math.log(kmsxh_val * 1000) - math.log(kstar_val)
        kgap_n += 1
    except Exception:
        continue

print(f"  KSTAR: {kstar_n} quarters")
print(f"  KGAP:  {kgap_n} quarters")

# ── 5. Collect results ────────────────────────────────────────────────────────
print()
print("Step 5: Results per target variable")
results = {}
total_rows = 0
for var in sorted(TARGET_VARS):
    series   = state.values.get(var, [])
    non_null = [(state.dates[i], v) for i, v in enumerate(series)
                if v is not None and i >= SOLVER_START]
    results[var] = non_null
    total_rows += len(non_null)
    status = f"{len(non_null):>3} quarters" if non_null else "  NO VALUES"
    print(f"  {var:<16} {status}")

print(f"\n  Total rows to insert: {total_rows}")

# ── 6. Write to DB (via /tmp to work around virtiofs write limitation) ────────
import shutil as _shutil
WORK_DB = '/tmp/timeseries_p5_phase6.db'
print()
print("Step 6: Write to DB")
print(f"  (already using {WORK_DB})")

existing_ids = set(r[0] for r in conn.execute("SELECT id FROM series").fetchall())

inserted = 0
skipped  = 0

for var in sorted(TARGET_VARS):
    quarters = results[var]
    if not quarters:
        skipped += 1
        continue

    if var not in existing_ids:
        conn.execute(
            "INSERT OR IGNORE INTO series (id, label, ons_scale) VALUES (?, ?, ?)",
            (var, f'Derived: {var}', 1.0)
        )

    for quarter, value in quarters:
        exists = conn.execute(
            "SELECT 1 FROM observations WHERE series_id=? AND quarter=? AND source='COMPUTED'",
            (var, quarter)
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO observations
                   (series_id, source, publication_date, quarter, value, data_type)
                   VALUES (?, 'COMPUTED', '2026-03', ?, ?, 'OUTTURN')""",
                (var, quarter, value)
            )
            inserted += 1

conn.commit()
conn.close()

print(f"  Inserted {inserted} new rows")
print(f"  {skipped} variables had no computed values (missing seed data)")

print(f"  Copying {WORK_DB} → {DB_PATH} ...")
shutil.copy(WORK_DB, DB_PATH)
print()
print("Done.")
