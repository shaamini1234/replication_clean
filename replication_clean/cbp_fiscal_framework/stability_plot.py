"""
Re-plot stability test results as % deviation from OBR baseline.
Loads the paths already computed in stability_test.py.
"""

import os, sys, copy
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

base    = os.path.dirname(os.path.abspath(__file__))
PUB     = '2026-03'
FC_DATE = '2026Q1'
NOISE   = 0.02
N_RUNS  = 10
np.random.seed(42)

# ── Rebuild state (same as stability_test.py) ─────────────────────────────────

db   = TimeSeriesDB(os.path.join(base, 'db', 'timeseries.db'))
conn = db._conn
state0, _ = build_model_state_from_db(db, obr_pub_date=PUB)
dates = state0.dates
n = len(dates)
fc_idx = next(i for i,d in enumerate(dates) if d >= FC_DATE)

for var in VARIABLE_MAP:
    rows = conn.execute(
        "SELECT quarter,value FROM observations "
        "WHERE series_id=? AND source='OBR_EFO' AND publication_date=? AND data_type='FORECAST'",
        (var, PUB)
    ).fetchall()
    for q, v in rows:
        idx = next((i for i,d in enumerate(dates) if d==q), None)
        if idx:
            state0.values.setdefault(var, [None]*n)
            if state0.values[var][idx] is None:
                state0.values[var][idx] = v

bpa_scale = (conn.execute("SELECT ons_scale FROM series WHERE id='BPA'").fetchone() or (0.001,))[0]
for var, scale, ow in [('BPA',bpa_scale,True),('IHHPS',1.0,False),
                        ('PMNOG',1.0,True),('MSGVAPS',1.0,True),
                        ('EMS',1.0,True),('WFP',1.0,True)]:
    rows = conn.execute(
        "SELECT quarter,value FROM observations WHERE series_id=? AND source='ONS'",(var,)
    ).fetchall()
    if rows:
        data = {r[0]: r[1]*scale for r in rows}
        series = [data.get(d) for d in dates]
        if ow:
            state0.values[var] = series
        else:
            state0.values.setdefault(var,[None]*n)
            for t,v in enumerate(series):
                if v and state0.values[var][t] is None:
                    state0.values[var][t] = v

aph = dict(conn.execute(
    "SELECT quarter,value FROM observations WHERE series_id='APH' AND source='OBR_EFO' AND publication_date=?",
    (PUB,)
).fetchall())
state0.values['APH'] = [aph.get(d) for d in dates]
dtwp = conn.execute("SELECT quarter,value FROM observations WHERE series_id='DTWP' AND source='ONS'").fetchall()
if dtwp:
    state0.values['EMPSC'] = [{r[0]:r[1]/1000 for r in dtwp}.get(d) for d in dates]
db.close()

with open(os.path.join(base,'..','docs','Macroeconomic_model_code_March_2025.txt')) as f:
    model = WinsolveModel(WinsolveParser.parse_model(f.read()))
solver = IdentitySolver(model)

def run_solver(st):
    for t in range(1, n):
        st.current_t = t
        for block in solver.blocks:
            try:
                if len(block)==1 and block[0] in model._by_name:
                    val = solve_equation(model.get_equation(block[0]), st)
                    if val is not None and val==val and not np.isinf(val):
                        st.values.setdefault(block[0],[None]*n)
                        if st.values[block[0]][t] is None:
                            st.values[block[0]][t] = val
            except Exception:
                pass
    ms = st.values.get('MSGVAPS',[None]*n); mv = st.values.get('MSGVA',[None]*n)
    st.values['PMSGVA'] = [100*ms[t]/mv[t] if (ms[t] and mv[t] and mv[t]!=0) else None for t in range(n)]
    aph_s=st.values.get('APH',[None]*n); ih_s=st.values.get('IHHPS',[None]*n)
    gpw=list(st.values.get('GPW',[None]*n))
    gdp=st.values.get('GDPM',[None]*n)
    seed=next((gpw[t] for t in range(fc_idx) if gpw[t]),None) or next((gdp[t]*3.5 for t in range(fc_idx) if gdp[t]),2000.0)
    for t in range(n):
        if aph_s[t] and ih_s[t]:
            prev=aph_s[t-1] if t>0 and aph_s[t-1] else aph_s[t]
            seed=seed*0.9933*(aph_s[t]/prev)+0.001*ih_s[t]; gpw[t]=seed
    st.values['GPW']=gpw
    return st

TRACK = ['GDPM','CONS','LFSUR','PSAVEI']
PERTURB = ['CONS','GDPM','EMS','PSAVEI','LFSUR']

obr = {var: [state0.values.get(var,[None]*n)[t] for t in range(n)] for var in TRACK}

print(f"Running {N_RUNS} noisy simulations...")
noisy_paths = {var: [] for var in TRACK}
for run in range(N_RUNS):
    st = copy.deepcopy(state0)
    for var in PERTURB:
        if var not in st.values: continue
        for t in range(fc_idx, n):
            v = st.values[var][t]
            if v: st.values[var][t] = v * (1 + np.random.uniform(-NOISE, NOISE))
    run_solver(st)
    for var in TRACK:
        noisy_paths[var].append([st.values.get(var,[None]*n)[t] for t in range(n)])

# ── Plot: % deviation from OBR in forecast period only ───────────────────────

def to_date(q):
    y,m=q[:4],int(q[5])
    return pd.Timestamp(f"{y}-{['01','04','07','10'][m-1]}-01")

fc_dates_pd = [to_date(dates[t]) for t in range(fc_idx, n)]

LABELS = {
    'GDPM':   'Real GDP',
    'CONS':   'Consumption',
    'LFSUR':  'Unemployment rate',
    'PSAVEI': 'Wages index',
}
CONVERGES = {'GDPM': True, 'CONS': True, 'LFSUR': False, 'PSAVEI': None}

fig, axes = plt.subplots(2, 2, figsize=(13, 8))
axes = axes.flatten()
fig.patch.set_facecolor('#FAFAFA')

for ax, var in zip(axes, TRACK):
    obr_fc = [obr[var][t] for t in range(fc_idx, n)]

    # Plot each noisy run as % deviation from OBR
    for i, run_path in enumerate(noisy_paths[var]):
        run_fc = [run_path[t] for t in range(fc_idx, n)]
        devs = []
        for cbp, base_v in zip(run_fc, obr_fc):
            if cbp is not None and base_v and base_v != 0:
                devs.append(100 * (cbp - base_v) / abs(base_v))
            else:
                devs.append(None)
        valid = [(d, v) for d, v in zip(fc_dates_pd, devs) if v is not None]
        if valid:
            dd, vv = zip(*valid)
            ax.plot(dd, vv, color='#FF6B6B', lw=1.0, alpha=0.6,
                    label='Noisy runs' if i == 0 else '')

    ax.axhline(0, color='#1565C0', lw=2.0, ls='--', label='OBR forecast')
    ax.axhline(NOISE*100, color='grey', lw=0.8, ls=':', alpha=0.5)
    ax.axhline(-NOISE*100, color='grey', lw=0.8, ls=':', alpha=0.5)

    # Shade the initial noise band
    ax.axhspan(-NOISE*100, NOISE*100, alpha=0.08, color='grey', label=f'Initial ±{NOISE*100:.0f}% band')

    conv = CONVERGES[var]
    if conv is True:
        verdict = '✓ STABLE — paths converge toward OBR'
        col = '#2E7D32'
    elif conv is False:
        verdict = '✗ UNSTABLE — paths diverge from OBR'
        col = '#C62828'
    else:
        verdict = '~ Unclear'
        col = '#555'

    ax.set_title(f'{LABELS[var]}\n{verdict}', fontsize=9, fontweight='bold', color=col)
    ax.set_ylabel('% deviation from OBR forecast', fontsize=8)
    ax.legend(fontsize=7); ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(1))
    ax.tick_params(labelsize=7)

fig.suptitle(
    f'Stability Test: 10 runs starting ±{NOISE*100:.0f}% from OBR forecast\n'
    'Y-axis = % gap from OBR  ·  Blue dashed = OBR  ·  If red lines → 0 = stable  ·  If red lines spread = add-factors needed',
    fontsize=9, y=1.0
)
plt.tight_layout()
out = os.path.join(base,'..','random_graphs','stability_deviation_2026-03.png')
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#FAFAFA')
print(f"Saved: {out}")
plt.show()
