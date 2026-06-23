"""
Labour market replication using the OBR's EMS (market sector employment) equation.

EMS equation (OBR estimated parameters):
  dlog(EMS) = -0.011
              + 0.44 * dlog(EMS(-1))          # employment momentum
              + 0.19 * dlog(EMS(-2))          # second lag
              + 0.17 * dlog(MSGVA(-1))        # output drives employment
              - 0.006 * ECM(-1)               # error correction

  ECM = log(EMS/MSGVA) + 0.4*log(PSAVEI/PMSGVA)
      = employment relative to output, adjusted for real wages

Variables:
  EMS     — market sector employment (thousands) from ONS
  MSGVA   — market sector real GVA (£bn CVM), computed from GVA - GGVA
  PSAVEI  — average weekly earnings index (2008Q1=100) from OBR EFO
  PMSGVA  — market sector GVA deflator = 100 * MSGVAPS / MSGVA

Usage:
    python3 employment_lm.py
"""

import os, sys
import sqlite3
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

import logging
logging.basicConfig(level=logging.WARNING)

base = os.path.dirname(os.path.abspath(__file__))

# ── Load state ────────────────────────────────────────────────────────────────

db = TimeSeriesDB(os.path.join(base, 'db', 'timeseries.db'))

# Use the proper builder (handles all seeding and scaling)
state, report = build_model_state_from_db(db, obr_pub_date='2026-03')
dates = state.dates
n = len(dates)
conn = db._conn

# ── Fix BPA BEFORE solver runs ────────────────────────────────────────────────
# The builder seeds BPA from GDPM (~586 £bn), but correct BPA is ~60 £bn.
# get_series_preferred applies ons_scale automatically.
bpa_preferred = db.get_series_preferred('BPA')
if bpa_preferred:
    state.values['BPA'] = [bpa_preferred.get(d) for d in dates]

# Layer OBR forecast values on top for forecast period MSGVA
from cbp_fiscal_framework.core.winsolve.variable_map import VARIABLE_MAP
for var in VARIABLE_MAP:
    rows = conn.execute(
        "SELECT quarter, value FROM observations "
        "WHERE series_id=? AND source='OBR_EFO' AND publication_date='2026-03' AND data_type='OBR_FORECAST'",
        (var,)
    ).fetchall()
    for r in rows:
        idx = next((i for i,d in enumerate(dates) if d==r[0]), None)
        if idx is not None and idx < n:
            if var not in state.values:
                state.values[var] = [None]*n
            if state.values[var][idx] is None:
                state.values[var][idx] = r[1]

# Load EMS and MSGVAPS from ONS (done before solver so they're available)
for var in ('EMS', 'MSGVAPS'):
    rows = conn.execute(
        "SELECT quarter, value FROM observations WHERE series_id=? AND source='ONS'",
        (var,)
    ).fetchall()
    if rows:
        data = {r[0]: r[1] for r in rows}
        state.values[var] = [data.get(d) for d in dates]

# ── Run solver to derive MSGVA, GGVA, GVA etc. ────────────────────────────────

with open(os.path.join(base, '..', 'docs', 'Macroeconomic_model_code_March_2025.txt')) as f:
    model = WinsolveModel(WinsolveParser.parse_model(f.read()))

solver = IdentitySolver(model)
for t in range(1, n):
    state.current_t = t
    for block in solver.blocks:
        try:
            if len(block)==1 and block[0] in model._by_name:
                val = solve_equation(model.get_equation(block[0]), state)
                if val is not None and val==val:
                    state.values.setdefault(block[0], [None]*n)
                    if state.values[block[0]][t] is None:
                        state.values[block[0]][t] = val
        except Exception:
            pass

# ── Compute PMSGVA = 100 * MSGVAPS / MSGVA ────────────────────────────────────

msgvaps_s = state.values.get('MSGVAPS', [None]*n)
msgva_s   = state.values.get('MSGVA',   [None]*n)

pmsgva = [100 * msgvaps_s[t] / msgva_s[t]
          if (msgvaps_s[t] is not None and msgva_s[t] is not None and msgva_s[t] != 0)
          else None
          for t in range(n)]
state.init_variable('PMSGVA', pmsgva)

print(f"PMSGVA computed: {sum(1 for v in pmsgva if v)} quarters")
for q in ['2008Q1','2015Q1','2020Q1','2024Q4']:
    idx = next((i for i,d in enumerate(dates) if d==q), None)
    v = pmsgva[idx] if idx else None
    print(f"  {q}: {v:.1f}" if v else f"  {q}: N/A")

# ── OBR EMS equation (published parameters) ───────────────────────────────────
# dlog(EMS) = -0.011
#             + 0.44*dlog(EMS(-1)) + 0.19*dlog(EMS(-2))
#             + 0.17*dlog(MSGVA(-1))
#             - 0.006*(log(EMS(-1)/MSGVA(-1)) + 0.4*log(PSAVEI(-1)/PMSGVA(-1)))

EMS_TREND    = -0.011
EMS_LAG1     =  0.44
EMS_LAG2     =  0.19
EMS_OUTPUT   =  0.17
EMS_ECM      = -0.006
EMS_WAGE_WT  =  0.4

ems_s    = state.values.get('EMS',    [None]*n)
msgva_s  = state.values.get('MSGVA',  [None]*n)
psavei_s = state.values.get('PSAVEI', [None]*n)

CUTOFF = '2025Q1'  # last reliable outturn for EMS from ONS
cutoff_idx = next(i for i,d in enumerate(dates) if d >= CUTOFF)

# Compute the historical mean ECM to use as equilibrium reference.
# The OBR calibrated the equation at specific units — the ECM term
# log(EMS/MSGVA) is large and positive because EMS is in thousands and
# MSGVA in £bn. The model works by tracking *deviations* from this
# historical average, not absolute levels.
ecm_history = []
for t in range(8, cutoff_idx):
    e = ems_s[t]; mv = msgva_s[t]; ps = psavei_s[t]; pm = pmsgva[t]
    if all(v is not None and v > 0 for v in [e, mv, ps, pm]):
        ecm_history.append(np.log(e/mv) + EMS_WAGE_WT * np.log(ps/pm))
ecm_mean = np.mean(ecm_history) if ecm_history else 0
print(f"Historical ECM mean (equilibrium reference): {ecm_mean:.4f}")
print(f"  (EMS/MSGVA ratio is large due to units: EMS in thousands, MSGVA in £bn)")

# Run equation — use deviation from historical mean ECM
ems_cbp = list(ems_s)  # start with ONS actuals
for t in range(6, n):
    if dates[t] < CUTOFF:
        continue  # don't overwrite outturn
    e1  = ems_cbp[t-1];   e2 = ems_cbp[t-2]
    mv1 = msgva_s[t-1];   mv0 = msgva_s[t-2]
    ps1 = psavei_s[t-1];  pm1 = pmsgva[t-1]
    if any(v is None or v <= 0 for v in [e1, e2, mv1, mv0, ps1, pm1]):
        break
    ecm = np.log(e1/mv1) + EMS_WAGE_WT * np.log(ps1/pm1)
    ecm_deviation = ecm - ecm_mean  # deviation from historical equilibrium
    dlog_ems = (EMS_TREND
                + EMS_LAG1 * np.log(e1/e2)
                + EMS_LAG2 * np.log(e2/ems_cbp[t-3] if ems_cbp[t-3] else e2)
                + EMS_OUTPUT * np.log(mv1/mv0)
                + EMS_ECM * ecm_deviation)  # error correction vs equilibrium
    ems_cbp[t] = e1 * np.exp(dlog_ems)

# ── OBR published EMS for comparison ──────────────────────────────────────────
ems_obr_rows = conn.execute(
    "SELECT quarter, value FROM observations "
    "WHERE series_id='EMS' AND source='OBR_EFO' AND publication_date='2026-03'"
).fetchall()
ems_obr = {r[0]: r[1] for r in ems_obr_rows}
db.close()

# ── Plot ──────────────────────────────────────────────────────────────────────

def to_date(q):
    y, n = q[:4], int(q[5])
    return pd.Timestamp(f"{y}-{['01','04','07','10'][n-1]}-01")

dates_pd = [to_date(d) for d in dates]
cutoff_pd = to_date(CUTOFF)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13,8), sharex=True,
                                gridspec_kw={'height_ratios':[2,1]})
fig.patch.set_facecolor('#FAFAFA')

# Level plot
ons_pairs  = [(dates_pd[t], ems_s[t])   for t in range(n) if ems_s[t]]
cbp_pairs  = [(dates_pd[t], ems_cbp[t]) for t in range(cutoff_idx, n) if ems_cbp[t]]
obr_pairs  = [(to_date(q), v) for q,v in sorted(ems_obr.items()) if to_date(q) >= cutoff_pd]

if ons_pairs:  ax1.plot(*zip(*ons_pairs),  '#1565C0', lw=1.8, label='ONS outturn')
if obr_pairs:  ax1.plot(*zip(*obr_pairs),  '#1565C0', lw=1.8, ls='--', label='OBR forecast')
if cbp_pairs:  ax1.plot(*zip(*cbp_pairs),  '#C62828', lw=1.8, label='CBP (OBR parameters)')

ax1.axvline(cutoff_pd, color='grey', lw=0.8, ls=':')
ax1.axvspan(cutoff_pd, dates_pd[-1], alpha=0.05, color='grey')
ax1.set_ylabel('Market sector employment (thousands)', fontsize=9)
ax1.set_title('EMS — Market Sector Employment', fontsize=11, fontweight='bold')
ax1.legend(fontsize=8); ax1.grid(True, alpha=0.25)

# Difference plot
obr_d = dict(obr_pairs)
diff = [(d, ems_cbp[t] - obr_d[dates[t]])
        for t, d in enumerate(dates_pd)
        if t >= cutoff_idx and ems_cbp[t] and dates[t] in obr_d]
if diff:
    dd, dv = zip(*diff)
    cols = ['#2ca02c' if v >= 0 else '#C62828' for v in dv]
    ax2.bar(dd, dv, width=60, color=cols, alpha=0.7)
    ax2.axhline(0, color='black', lw=0.6)
    ax2.set_ylabel('CBP minus OBR (thousands)', fontsize=9)
    ax2.grid(True, alpha=0.25)

for ax in (ax1, ax2):
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(3))
    ax.tick_params(labelsize=8)

eq_text = ("OBR equation: Δlog(EMS) = −0.011 + 0.44·Δlog(EMS₋₁) + 0.19·Δlog(EMS₋₂)\n"
           "              + 0.17·Δlog(MSGVA₋₁) − 0.006·[log(EMS/MSGVA) + 0.4·log(PSAVEI/PMSGVA)]₋₁")
fig.text(0.5, 0.01, eq_text, ha='center', fontsize=7.5, color='#555',
         bbox=dict(boxstyle='round', facecolor='#FFF3E0', edgecolor='#FF9800', alpha=0.8))

plt.suptitle('Labour Market — CBP vs OBR using OBR\'s own parameters\n'
             'Blue = ONS outturn / OBR forecast  ·  Red = CBP model  ·  Grey = forecast period',
             fontsize=10, y=0.99)
plt.tight_layout(rect=[0, 0.08, 1, 0.98])

out = os.path.join(base, '..', 'random_graphs', 'employment_lm_2026-03.png')
os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#FAFAFA')
print(f"\nSaved: {out}")
plt.show()

# Print comparison table
print(f"\n{'Quarter':<10} {'ONS actual':>12} {'OBR forecast':>14} {'CBP model':>12} {'CBP-OBR':>10}")
print("-"*62)
for q in ['2025Q1','2025Q4','2026Q1','2027Q1','2028Q1','2030Q1','2031Q1']:
    idx = next((i for i,d in enumerate(dates) if d==q), None)
    if idx is None: continue
    ons = ems_s[idx]
    obr = ems_obr.get(q)
    cbp = ems_cbp[idx]
    diff = (cbp - obr) if (cbp and obr) else None
    print(f"{q:<10} {str(round(ons)) if ons else '—':>12} {str(round(obr)) if obr else '—':>14} "
          f"{str(round(cbp)) if cbp else '—':>12} {str(round(diff)) if diff else '—':>10}")
