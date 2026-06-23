"""
Plot model-computed forecast vs OBR official published forecast.

Saves published values before running the solver, then compares.

Usage:
    python3 plot_computed_vs_obr.py
"""

import os, sys, copy
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from cbp_fiscal_framework.inputs.data_manager import DataManager
from cbp_fiscal_framework.core.winsolve import (
    build_model_state, WinsolveParser, WinsolveModel, IdentitySolver, solve_equation,
)

import logging
logging.basicConfig(level=logging.WARNING)

base = os.path.dirname(os.path.abspath(__file__))
dm = DataManager()
dm.register_obr_vintage(os.path.join(base, '..', 'data', '2026-03', 'obr'))
dm.register_model_code(os.path.join(base, '..', 'docs', 'Macroeconomic_model_code_March_2025.txt'))
dm.load_all_data()

state, _ = build_model_state(dm)

with open(os.path.join(base, '..', 'docs', 'Macroeconomic_model_code_March_2025.txt')) as f:
    model = WinsolveModel(WinsolveParser.parse_model(f.read()))

dates = state.dates
forecast_start = next(i for i, d in enumerate(dates) if d >= '2025Q1')

# Save published values before solver overwrites
published = {var: list(series) for var, series in state.values.items()}

# Run solver
solver = IdentitySolver(model)
for t in range(1, len(dates)):
    state.current_t = t
    for block in solver.blocks:
        try:
            if len(block) == 1:
                var = block[0]
                if var not in model._by_name:
                    continue
                val = solve_equation(model.get_equation(var), state)
                if val is not None and val == val:
                    if var not in state.values:
                        state.values[var] = [None] * len(dates)
                    state.values[var][t] = val
        except Exception:
            pass

computed = {var: list(series) for var, series in state.values.items()}

# ── panels: (title, var, ylabel, pub_label, comp_label) ──────────────────────
# Only show panels where we have BOTH published OBR AND a computed value,
# and they differ meaningfully in the forecast period (i.e. interesting comparison)

PANELS = [
    ('Unemployment rate (%)',
     'LFSUR',
     'Per cent',
     'OBR published (ILO unemployment rate)',
     'Computed: 100×ULFS/(ETLFS+ULFS)'),

    ('Nominal GDP (£bn)',
     'GDPMPS',
     '£ billion',
     'OBR published (nominal GDP)',
     'Computed: TFEPS−MPS+SDEPS'),

    ('Nominal consumption (£bn)',
     'CONSPS',
     '£ billion',
     'OBR published',
     'Computed: CONS×PCE/100'),

    ('Trade balance (£bn)',
     'TB',
     '£ billion',
     'OBR published',
     'Computed: XPS−MPS'),

    ('Current account (% GDP)',
     'CBPCNT',
     'Per cent of GDP',
     'OBR published',
     'Computed: (CB/GDPMPS)×100'),

    ('Real household disposable income',
     'RHHDI',
     'Index (2023=100)',
     'OBR implied (HHDI/PCE×100)',
     'Computed: 100×HHDI/PCE'),
]

dates_pd = pd.to_datetime([d.replace('Q1', '-01-01').replace('Q2', '-04-01')
                            .replace('Q3', '-07-01').replace('Q4', '-10-01')
                            for d in dates])

OBR_BLUE = '#1f77b4'
CBP_RED  = '#d62728'

fig, axes = plt.subplots(2, 3, figsize=(16, 9))
axes = axes.flatten()

for ax, (title, var, ylabel, pub_lbl, comp_lbl) in zip(axes, PANELS):
    pub  = published.get(var, [None]*len(dates))
    comp = computed.get(var, [None]*len(dates))

    if all(v is None for v in pub) and all(v is None for v in comp):
        ax.set_visible(False)
        continue

    # Split at forecast boundary
    def split(series):
        hist = [v if i < forecast_start else None for i, v in enumerate(series)]
        fore = [v if i >= forecast_start else None for i, v in enumerate(series)]
        return hist, fore

    pub_hist, pub_fore = split(pub)
    comp_hist, comp_fore = split(comp)

    def plot_series(ax, series, color, lw, ls, label):
        pairs = [(d, v) for d, v in zip(dates_pd, series) if v is not None]
        if pairs:
            dd, vv = zip(*pairs)
            ax.plot(dd, vv, color=color, linewidth=lw, linestyle=ls, label=label)

    # Historical — OBR published (solid blue)
    plot_series(ax, pub_hist, OBR_BLUE, 1.8, '-', pub_lbl + ' (history)')
    # Forecast — OBR published (dashed blue)
    plot_series(ax, pub_fore, OBR_BLUE, 1.8, '--', pub_lbl + ' (forecast)')
    # Computed forecast — solid red
    plot_series(ax, comp_fore, CBP_RED, 1.8, '-', comp_lbl)

    # Shade forecast region
    ax.axvspan(dates_pd[forecast_start], dates_pd[-1], alpha=0.06, color='grey')
    ax.axvline(dates_pd[forecast_start], color='grey', linewidth=0.8, linestyle=':')
    ax.text(dates_pd[forecast_start], ax.get_ylim()[0] if ax.get_ylim()[0] != 0 else 0,
            ' forecast →', fontsize=6, color='grey', va='bottom')

    ax.set_title(title, fontsize=9, fontweight='bold', pad=4)
    ax.set_ylabel(ylabel, fontsize=7)
    ax.tick_params(labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(4))
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=6, loc='best')

fig.suptitle(
    'CBP Model: Computed vs OBR Published Forecast\n'
    'Blue = OBR published · Red = model computed from identity equations · March 2026 EFO',
    fontsize=11, y=1.01
)
plt.tight_layout()

out = os.path.join(base, '..', 'random_graphs', 'computed_vs_obr_2026-03.png')
plt.savefig(out, dpi=150, bbox_inches='tight')
print(f"Saved: {out}")
plt.show()
