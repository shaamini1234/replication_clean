"""
Plot predicted vs observed for failing Winsolve identity equations.

Usage:
    python3 plot_equation_residuals.py              # March 2026 (default)
    python3 plot_equation_residuals.py 2025-11      # November 2025
"""

import os
import sys

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from cbp_fiscal_framework.inputs.data_manager import DataManager
from cbp_fiscal_framework.core.winsolve import (
    build_model_state, WinsolveParser, WinsolveModel, solve_equation,
)
from cbp_fiscal_framework.core.winsolve.model import extract_variables

import logging
logging.basicConfig(level=logging.WARNING, format='%(message)s')


VINTAGE = sys.argv[1] if len(sys.argv) > 1 else '2026-03'

# ── load data ────────────────────────────────────────────────────────────────

base_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(base_dir, '..', 'data', VINTAGE, 'obr')
model_path = os.path.join(base_dir, '..', 'docs', 'Macroeconomic_model_code_March_2025.txt')

dm = DataManager()
dm.register_obr_vintage(data_dir)
if os.path.isfile(model_path):
    dm.register_model_code(model_path)
dm.load_all_data()

state, coverage = build_model_state(dm)
print(f"Loaded {len(coverage['loaded'])} variables, {coverage['total_dates']} quarters "
      f"({coverage['date_range']})")

# ── parse model ──────────────────────────────────────────────────────────────

with open(model_path) as f:
    model = WinsolveModel(WinsolveParser.parse_model(f.read()))

# ── identify failing equations ───────────────────────────────────────────────

available = set(state.values.keys())
START_T = 4

results = {}
for eq in model.identity_equations():
    var = eq.lhs_variable
    if var == '?' or var not in available:
        continue
    all_vars = extract_variables(eq.rhs) | extract_variables(eq.lhs)
    missing = all_vars - available
    if missing:
        continue

    observed_series, computed_series, dates_used = [], [], []
    for t in range(START_T, len(state.dates)):
        state.current_t = t
        try:
            obs = state.get(var)
            pred = solve_equation(eq, state)
            observed_series.append(obs)
            computed_series.append(pred)
            dates_used.append(state.dates[t])
        except Exception:
            pass

    if not observed_series:
        continue

    obs_arr = np.array(observed_series, dtype=float)
    pred_arr = np.array(computed_series, dtype=float)
    residuals = np.abs(pred_arr - obs_arr)
    tolerance = np.maximum(0.05, np.abs(obs_arr) * 0.001)
    pass_rate = np.mean(residuals <= tolerance)

    results[var] = {
        'eq': eq,
        'dates': dates_used,
        'observed': obs_arr,
        'computed': pred_arr,
        'residuals': residuals,
        'pass_rate': pass_rate,
        'raw': eq.raw[:60],
    }

# split into passing / failing
passing = {v: r for v, r in results.items() if r['pass_rate'] == 1.0}
failing = {v: r for v, r in results.items() if r['pass_rate'] < 1.0}

print(f"\nEquations tested: {len(results)}  |  "
      f"Passing: {len(passing)}  |  Failing: {len(failing)}\n")

if not failing:
    print("No failing equations to plot.")
    sys.exit(0)

# ── plot ─────────────────────────────────────────────────────────────────────

N = len(failing)
COLS = 2
ROWS = (N + 1) // COLS

fig, axes = plt.subplots(ROWS, COLS, figsize=(14, 4 * ROWS))
axes = np.array(axes).flatten()

for ax, (var, r) in zip(axes, failing.items()):
    import pandas as pd
    dates_pd = pd.to_datetime(r['dates'])

    ax.plot(dates_pd, r['observed'], color='#1f77b4', linewidth=1.8,
            label='Observed (OBR published)')
    ax.plot(dates_pd, r['computed'], color='#d62728', linewidth=1.4,
            linestyle='--', label='Predicted (model RHS)')

    ax.set_title(f"{var}  —  {int(r['pass_rate']*100)}% pass\n"
                 f"$\\it{{{r['raw'][:55]}}}$",
                 fontsize=8, pad=4)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(4))
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, loc='best')
    ax.grid(True, alpha=0.3)
    ax.set_ylabel('£bn / index', fontsize=7)

# hide unused axes
for ax in axes[N:]:
    ax.set_visible(False)

fig.suptitle(
    f"OBR Winsolve — Failing Identity Equations\n"
    f"Vintage: {VINTAGE}  |  Observed vs Model-Predicted",
    fontsize=11, y=1.01
)
plt.tight_layout()

out_path = os.path.join(base_dir, '..', 'random_graphs', f'obr_equation_residuals_{VINTAGE}.png')
os.makedirs(os.path.dirname(out_path), exist_ok=True)
plt.savefig(out_path, dpi=150, bbox_inches='tight')
print(f"Saved: {out_path}")
plt.show()
