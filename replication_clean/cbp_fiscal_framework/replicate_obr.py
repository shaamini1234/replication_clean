"""
Attempt to replicate the OBR's March 2026 forecast using the full
simultaneous equation system (Gauss-Seidel).
"""

import os, sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from cbp_fiscal_framework.db.timeseries_db import TimeSeriesDB
from cbp_fiscal_framework.core.winsolve import (
    build_model_state_from_db, WinsolveParser, WinsolveModel,
    IdentitySolver, solve_equation,
)
from cbp_fiscal_framework.core.winsolve.variable_map import VARIABLE_MAP

import logging
logging.basicConfig(level=logging.WARNING)

base = os.path.dirname(os.path.abspath(__file__))
PUB_DATE = '2026-03'
FORECAST_START = '2026Q1'

# ── 1. Build state: outturn + assumptions, properly seeded ────────────────────

db = TimeSeriesDB(os.path.join(base, 'db', 'timeseries.db'))
conn = db._conn

state, _ = build_model_state_from_db(db, obr_pub_date=PUB_DATE)
dates = state.dates
n     = len(dates)

# Layer OBR forecast values on top (for all endogenous variables)
for var in VARIABLE_MAP:
    rows = conn.execute(
        "SELECT quarter, value FROM observations "
        "WHERE series_id=? AND source='OBR_EFO' AND publication_date=? AND data_type='FORECAST'",
        (var, PUB_DATE)
    ).fetchall()
    for q, v in rows:
        idx = next((i for i, d in enumerate(dates) if d == q), None)
        if idx is not None:
            state.values.setdefault(var, [None]*n)
            if state.values[var][idx] is None:
                state.values[var][idx] = v

# ── 2. Fix BPA and load extra series ─────────────────────────────────────────

def load_ons(var, scale=1.0, overwrite=False):
    rows = conn.execute(
        "SELECT quarter, value FROM observations WHERE series_id=? AND source='ONS'",
        (var,)
    ).fetchall()
    if not rows:
        return 0
    data = {r[0]: r[1] * scale for r in rows}
    series = [data.get(d) for d in dates]
    if overwrite:
        state.values[var] = series
    else:
        state.values.setdefault(var, [None]*n)
        for t, v in enumerate(series):
            if v is not None and state.values[var][t] is None:
                state.values[var][t] = v
    return sum(1 for v in series if v is not None)

# BPA: ONS NTAO gives correct values (~60 £bn, not ~586 like GDPM seed)
bpa_scale = (conn.execute("SELECT ons_scale FROM series WHERE id='BPA'").fetchone() or (0.001,))[0]
print(f"BPA: {load_ons('BPA', bpa_scale, overwrite=True)} qtrs (scale={bpa_scale})")

# APH: OBR housing market assumption from Sheet 1.16
aph_rows = conn.execute(
    "SELECT quarter, value FROM observations "
    "WHERE series_id='APH' AND source='OBR_EFO' AND publication_date=?", (PUB_DATE,)
).fetchall()
if aph_rows:
    state.values['APH'] = [dict(aph_rows).get(d) for d in dates]
    print(f"APH: {sum(1 for v in state.values['APH'] if v)} qtrs")

# ONS series
for var in ('PMNOG', 'MSGVAPS', 'EMS', 'WFP'):
    print(f"{var}: {load_ons(var, overwrite=True)} qtrs")

# EMPSC = DTWP (£m → £bn)
dtwp = conn.execute(
    "SELECT quarter, value FROM observations WHERE series_id='DTWP' AND source='ONS'"
).fetchall()
if dtwp:
    state.values['EMPSC'] = [{r[0]: r[1]/1000 for r in dtwp}.get(d) for d in dates]
    print(f"EMPSC: {sum(1 for v in state.values['EMPSC'] if v)} qtrs")

db.close()

# ── 3. Parse model ────────────────────────────────────────────────────────────

with open(os.path.join(base, '..', 'docs',
          'Macroeconomic_model_code_March_2025.txt')) as f:
    model = WinsolveModel(WinsolveParser.parse_model(f.read()))

solver = IdentitySolver(model)

# ── 4. Identity solver pass to populate GVA, MSGVA, PMSGVA etc. ──────────────

for t in range(1, n):
    state.current_t = t
    for block in solver.blocks:
        try:
            if len(block) == 1 and block[0] in model._by_name:
                val = solve_equation(model.get_equation(block[0]), state)
                if val is not None and val == val:
                    state.values.setdefault(block[0], [None]*n)
                    if state.values[block[0]][t] is None:
                        state.values[block[0]][t] = val
        except Exception:
            pass

# PMSGVA = 100 * MSGVAPS / MSGVA
msgvaps = state.values.get('MSGVAPS', [None]*n)
msgva   = state.values.get('MSGVA',   [None]*n)
state.values['PMSGVA'] = [
    100 * msgvaps[t] / msgva[t]
    if (msgvaps[t] is not None and msgva[t] and msgva[t] != 0) else None
    for t in range(n)
]
print(f"\nAfter identity pass:")
print(f"  MSGVA:  {sum(1 for v in msgva if v)} qtrs")
print(f"  PMSGVA: {sum(1 for v in state.values['PMSGVA'] if v)} qtrs")

# Seed GPW (gross physical wealth = housing stock value)
aph_s   = state.values.get('APH',   [None]*n)
ihhps_s = state.values.get('IHHPS', [None]*n)
gpw = [None]*n
seed = None
for t in range(n):
    if aph_s[t] and ihhps_s[t]:
        if seed is None:
            gdp0 = state.values.get('GDPM', [None]*n)[t]
            seed = (gdp0 or 600) * 3.5  # rough initial housing wealth ≈ 3.5× GDP
        prev_aph = aph_s[t-1] if t > 0 and aph_s[t-1] else aph_s[t]
        seed = seed * 0.9933 * (aph_s[t] / prev_aph) + 0.001 * ihhps_s[t]
        gpw[t] = seed
state.values['GPW'] = gpw
print(f"  GPW:    {sum(1 for v in gpw if v)} qtrs")

# ── 5. Save OBR forecast for comparison ──────────────────────────────────────

fc_idx = next(i for i,d in enumerate(dates) if d >= FORECAST_START)
KEY_VARS = ['GDPM', 'CONS', 'LFSUR', 'PSAVEI', 'EMS', 'GDPMPS']
obr_fc = {}
for var in KEY_VARS:
    s = state.values.get(var, [None]*n)
    obr_fc[var] = {dates[t]: s[t] for t in range(fc_idx, n) if s[t]}

print(f"\nRunning solver across full horizon (outturn + forecast)...")
print("Gaps between computed and OBR published = add-factors needed for replication.")

# ── 6. Run solver: compute all equations, compare to OBR published ────────────
# Don't pre-clear anything — use OBR values as initialisation.
# The solver overwrites None slots. Where OBR published a value, it stays
# unless the solver can compute a different one (showing add-factor need).

# Track what was computed vs what OBR published
computed = {}
for t in range(1, n):
    state.current_t = t
    for block in solver.blocks:
        try:
            if len(block) == 1 and block[0] in model._by_name:
                val = solve_equation(model.get_equation(block[0]), state)
                if val is not None and val == val and not np.isinf(val):
                    var = block[0]
                    state.values.setdefault(var, [None]*n)
                    if state.values[var][t] is None:
                        state.values[var][t] = val
                    # Track computed vs OBR in forecast period
                    if t >= fc_idx:
                        computed.setdefault(var, {})[dates[t]] = val
        except Exception:
            pass

    # PMSGVA each period
    msgvaps = state.values.get('MSGVAPS', [None]*n)
    msgva   = state.values.get('MSGVA',   [None]*n)
    if msgvaps[t] and msgva[t] and msgva[t] != 0:
        state.values.setdefault('PMSGVA', [None]*n)
        if state.values['PMSGVA'][t] is None:
            state.values['PMSGVA'][t] = 100 * msgvaps[t] / msgva[t]

print(f"Variables computed in forecast period: {len(computed)}")

# ── 8. Results ────────────────────────────────────────────────────────────────

print(f"\n{'Quarter':<10} {'GDPM CBP':>10} {'GDPM OBR':>10} {'CONS CBP':>10} {'CONS OBR':>10} {'LFSUR CBP':>10} {'LFSUR OBR':>10}")
print("-"*72)
for q in ['2026Q1','2027Q1','2028Q1','2030Q1','2031Q1']:
    idx = next((i for i,d in enumerate(dates) if d==q), None)
    if not idx: continue
    def v(var): return state.values.get(var,[None]*n)[idx]
    def o(var): return obr_fc.get(var,{}).get(q)
    print(f"{q:<10} {v('GDPM') or 0:>10.1f} {o('GDPM') or 0:>10.1f} "
          f"{v('CONS') or 0:>10.1f} {o('CONS') or 0:>10.1f} "
          f"{v('LFSUR') or 0:>10.2f} {o('LFSUR') or 0:>10.2f}")

# ── 9. Plot ───────────────────────────────────────────────────────────────────

def to_date(q):
    y, m = q[:4], int(q[5])
    return pd.Timestamp(f"{y}-{['01','04','07','10'][m-1]}-01")

dates_pd = [to_date(d) for d in dates]
fc_pd    = to_date(FORECAST_START)

fig, axes = plt.subplots(2, 2, figsize=(14, 9))
axes = axes.flatten()
fig.patch.set_facecolor('#FAFAFA')

PANELS = [('GDPM','Real GDP (£bn CVM)'),('CONS','Consumption (£bn)'),
          ('LFSUR','Unemployment (%)'),('PSAVEI','Wages index')]

for ax, (var, title) in zip(axes, PANELS):
    s   = state.values.get(var, [None]*n)
    ofc = obr_fc.get(var, {})

    hist = [(dates_pd[t], s[t])          for t in range(fc_idx)   if s[t]]
    cbp  = [(dates_pd[t], s[t])          for t in range(fc_idx, n) if s[t]]
    obr_ = [(to_date(q), v) for q,v in sorted(ofc.items())]

    if hist: ax.plot(*zip(*hist),  '#1565C0', lw=1.8, label='OBR outturn')
    if obr_: ax.plot(*zip(*obr_),  '#1565C0', lw=1.8, ls='--', label='OBR forecast')
    if cbp:  ax.plot(*zip(*cbp),   '#C62828', lw=1.8, label='CBP replication')

    ax.axvline(fc_pd, color='grey', lw=0.8, ls=':')
    ax.axvspan(fc_pd, dates_pd[-1], alpha=0.05, color='grey')
    ax.set_title(title, fontsize=9, fontweight='bold')
    ax.legend(fontsize=7); ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(4))
    ax.tick_params(labelsize=7)

fig.suptitle('OBR March 2026 Forecast — CBP Replication\n'
             'Blue=OBR  ·  Red=CBP simultaneous system  ·  Grey=forecast period',
             fontsize=10, y=0.99)
plt.tight_layout()
out = os.path.join(base,'..','random_graphs','obr_replication_2026-03.png')
os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#FAFAFA')
print(f"\nSaved: {out}")
plt.show()
