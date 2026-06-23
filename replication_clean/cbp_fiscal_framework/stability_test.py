"""
Stability test: start from OBR forecast with random noise, run the
simultaneous system, and see if it returns to the OBR baseline.

If the model is stable: perturbed paths converge back toward OBR.
If unstable: perturbations amplify — meaning add-factors are doing
heavy lifting to hold the OBR forecast in place.
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

base    = os.path.dirname(os.path.abspath(__file__))
PUB     = '2026-03'
FC_DATE = '2026Q1'
NOISE   = 0.02   # ±2% perturbation
N_RUNS  = 10     # number of noisy simulations
np.random.seed(42)

# ── Load state ────────────────────────────────────────────────────────────────

db   = TimeSeriesDB(os.path.join(base, 'db', 'timeseries.db'))
conn = db._conn

state0, _ = build_model_state_from_db(db, obr_pub_date=PUB)
dates = state0.dates
n     = len(dates)
fc_idx = next(i for i,d in enumerate(dates) if d >= FC_DATE)

# Add OBR forecast values
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

# Fix BPA + load IHHPS, APH, PMNOG, MSGVAPS
bpa_scale = (conn.execute("SELECT ons_scale FROM series WHERE id='BPA'").fetchone() or (0.001,))[0]
for var, scale, overwrite in [('BPA', bpa_scale, True), ('IHHPS', 1.0, False),
                               ('PMNOG', 1.0, True), ('MSGVAPS', 1.0, True),
                               ('EMS', 1.0, True), ('WFP', 1.0, True)]:
    rows = conn.execute(
        "SELECT quarter,value FROM observations WHERE series_id=? AND source='ONS'", (var,)
    ).fetchall()
    if rows:
        data = {r[0]: r[1]*scale for r in rows}
        series = [data.get(d) for d in dates]
        if overwrite:
            state0.values[var] = series
        else:
            state0.values.setdefault(var, [None]*n)
            for t, v in enumerate(series):
                if v and state0.values[var][t] is None:
                    state0.values[var][t] = v

# APH
aph = dict(conn.execute(
    "SELECT quarter,value FROM observations WHERE series_id='APH' AND source='OBR_EFO' AND publication_date=?",
    (PUB,)
).fetchall())
state0.values['APH'] = [aph.get(d) for d in dates]

dtwp = conn.execute(
    "SELECT quarter,value FROM observations WHERE series_id='DTWP' AND source='ONS'"
).fetchall()
if dtwp:
    state0.values['EMPSC'] = [{r[0]: r[1]/1000 for r in dtwp}.get(d) for d in dates]

db.close()

# ── Parse model ───────────────────────────────────────────────────────────────

with open(os.path.join(base, '..', 'docs',
          'Macroeconomic_model_code_March_2025.txt')) as f:
    model = WinsolveModel(WinsolveParser.parse_model(f.read()))

solver = IdentitySolver(model)

def run_solver(st):
    """Run one pass of the simultaneous solver."""
    for t in range(1, n):
        st.current_t = t
        for block in solver.blocks:
            try:
                if len(block) == 1 and block[0] in model._by_name:
                    val = solve_equation(model.get_equation(block[0]), st)
                    if val is not None and val == val and not np.isinf(val):
                        st.values.setdefault(block[0], [None]*n)
                        if st.values[block[0]][t] is None:
                            st.values[block[0]][t] = val
            except Exception:
                pass
    # PMSGVA
    ms = st.values.get('MSGVAPS', [None]*n)
    mv = st.values.get('MSGVA',   [None]*n)
    st.values['PMSGVA'] = [
        100*ms[t]/mv[t] if (ms[t] and mv[t] and mv[t]!=0) else None
        for t in range(n)
    ]
    # GPW
    aph_s = st.values.get('APH',   [None]*n)
    ih_s  = st.values.get('IHHPS', [None]*n)
    gpw = list(st.values.get('GPW', [None]*n))
    seed = next((gpw[t] for t in range(fc_idx) if gpw[t]), None)
    if not seed:
        gdp = st.values.get('GDPM', [None]*n)
        seed = next((gdp[t]*3.5 for t in range(fc_idx) if gdp[t]), 2000.0)
    for t in range(n):
        if aph_s[t] and ih_s[t]:
            prev = aph_s[t-1] if t > 0 and aph_s[t-1] else aph_s[t]
            seed = seed * 0.9933 * (aph_s[t]/prev) + 0.001 * ih_s[t]
            gpw[t] = seed
    st.values['GPW'] = gpw
    return st

# ── Baseline: run solver on OBR starting point ────────────────────────────────

import copy
baseline_state = copy.deepcopy(state0)
run_solver(baseline_state)

# OBR published forecast (before any solver)
TRACK = ['GDPM', 'CONS', 'LFSUR', 'PSAVEI']
obr = {var: [state0.values.get(var,[None]*n)[t] for t in range(n)] for var in TRACK}

print(f"Baseline computed. Running {N_RUNS} noisy simulations (±{NOISE*100:.0f}% noise)...")

# ── Noisy runs ────────────────────────────────────────────────────────────────

# Variables to perturb: endogenous outputs in forecast period
PERTURB_VARS = ['CONS', 'GDPM', 'EMS', 'PSAVEI', 'LFSUR']

noisy_paths = {var: [] for var in TRACK}

for run in range(N_RUNS):
    st = copy.deepcopy(state0)

    # Apply ±NOISE perturbation to endogenous forecast variables
    for var in PERTURB_VARS:
        if var not in st.values:
            continue
        for t in range(fc_idx, n):
            v = st.values[var][t]
            if v is not None:
                shock = 1.0 + np.random.uniform(-NOISE, NOISE)
                st.values[var][t] = v * shock

    # Run solver
    run_solver(st)

    for var in TRACK:
        noisy_paths[var].append([st.values.get(var,[None]*n)[t] for t in range(n)])

    if (run+1) % 2 == 0:
        print(f"  Run {run+1}/{N_RUNS} done")

# ── Plot ──────────────────────────────────────────────────────────────────────

def to_date(q):
    y, m = q[:4], int(q[5])
    return pd.Timestamp(f"{y}-{['01','04','07','10'][m-1]}-01")

dates_pd = [to_date(d) for d in dates]
fc_pd    = to_date(FC_DATE)

LABELS = {'GDPM': 'Real GDP (£bn)',
          'CONS': 'Consumption (£bn)',
          'LFSUR': 'Unemployment rate (%)',
          'PSAVEI': 'Wages index (2008Q1=100)'}

fig, axes = plt.subplots(2, 2, figsize=(14, 9))
axes = axes.flatten()
fig.patch.set_facecolor('#FAFAFA')

for ax, var in zip(axes, TRACK):
    title = LABELS[var]
    obr_s = obr[var]

    # OBR published
    hist_pairs = [(dates_pd[t], obr_s[t]) for t in range(fc_idx) if obr_s[t]]
    fc_pairs   = [(dates_pd[t], obr_s[t]) for t in range(fc_idx, n) if obr_s[t]]
    if hist_pairs: ax.plot(*zip(*hist_pairs), '#1565C0', lw=2.0, label='OBR outturn', zorder=5)
    if fc_pairs:   ax.plot(*zip(*fc_pairs),   '#1565C0', lw=2.0, ls='--', label='OBR forecast', zorder=5)

    # Noisy simulations
    for i, run_path in enumerate(noisy_paths[var]):
        run_fc = [(dates_pd[t], run_path[t]) for t in range(fc_idx, n) if run_path[t]]
        if run_fc:
            ax.plot(*zip(*run_fc), '#FF6B6B', lw=0.9, alpha=0.5,
                    label='Noisy runs' if i == 0 else '')

    ax.axvline(fc_pd, color='grey', lw=0.8, ls=':')
    ax.axvspan(fc_pd, dates_pd[-1], alpha=0.05, color='grey')
    ax.set_title(title, fontsize=9, fontweight='bold')
    ax.legend(fontsize=7); ax.grid(True, alpha=0.25)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(4))
    ax.tick_params(labelsize=7)

fig.suptitle(
    f'Stability Test: OBR Forecast vs ±{NOISE*100:.0f}% Random Perturbations ({N_RUNS} runs)\n'
    'If noisy paths converge toward OBR (blue dashed) → model is stable. '
    'If they diverge → add-factors are load-bearing.',
    fontsize=9, y=0.99
)
plt.tight_layout()

out = os.path.join(base, '..', 'random_graphs', 'stability_test_2026-03.png')
os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#FAFAFA')
print(f"\nSaved: {out}")

# Print convergence summary
print(f"\nConvergence: are noisy paths closer to OBR at end than at start?")
print(f"{'Variable':<10} {'Initial spread':>16} {'Final spread':>14} {'Converges?'}")
print("-"*55)
for var in TRACK:
    paths = noisy_paths[var]
    init_vals  = [p[fc_idx]   for p in paths if p[fc_idx]]
    final_vals = [p[n-4]      for p in paths if p[n-4]]
    obr_init   = obr[var][fc_idx] or 1
    obr_final  = obr[var][n-4]   or 1
    if init_vals and final_vals:
        init_spread  = np.std(init_vals) / abs(obr_init)  * 100
        final_spread = np.std(final_vals) / abs(obr_final) * 100
        direction = '→ YES' if final_spread < init_spread else '→ NO (diverging!)'
        print(f"{var:<10} {init_spread:>14.2f}%  {final_spread:>12.2f}%  {direction}")

plt.show()
