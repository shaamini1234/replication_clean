"""
Plot computed forward-forecast values vs OBR published data.

Focuses on variables that are genuinely computed by the identity solver
rather than loaded directly from the OBR EFO tables.

Usage:
    python3 plot_forward_forecast.py
"""

import os, sys
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from cbp_fiscal_framework.inputs.data_manager import DataManager
from cbp_fiscal_framework.core.winsolve import (
    build_model_state, WinsolveParser, WinsolveModel, IdentitySolver, solve_equation,
)

import logging
logging.basicConfig(level=logging.WARNING)

# ── load ─────────────────────────────────────────────────────────────────────

base = os.path.dirname(os.path.abspath(__file__))
dm = DataManager()
dm.register_obr_vintage(os.path.join(base, '..', 'data', '2026-03', 'obr'))
dm.register_model_code(os.path.join(base, '..', 'docs', 'Macroeconomic_model_code_March_2025.txt'))
dm.load_all_data()

state, _ = build_model_state(dm)

with open(os.path.join(base, '..', 'docs', 'Macroeconomic_model_code_March_2025.txt')) as f:
    model = WinsolveModel(WinsolveParser.parse_model(f.read()))

solver = IdentitySolver(model)
dates = state.dates

# ── run solver forward ────────────────────────────────────────────────────────

# Record which variables were in state BEFORE solving (= OBR published)
published_vars = set(state.values.keys())

for t in range(1, len(dates)):
    state.current_t = t
    for block in solver.blocks:
        try:
            if len(block) == 1:
                var = block[0]
                if var not in model._by_name:
                    continue
                eq = model.get_equation(var)
                val = solve_equation(eq, state)
                if val is not None and val == val:
                    if var not in state.values:
                        state.values[var] = [None] * len(dates)
                    state.values[var][t] = val
        except Exception:
            pass

# ── define panels ─────────────────────────────────────────────────────────────

# (title, computed_var, published_var_or_None, y_label, description)
PANELS = [
    ('Unemployment rate (%)',
     'LFSUR', 'LFSUR',
     'Per cent',
     'Computed: 100×ULFS/(ETLFS+ULFS)'),

    ('Employment (thousands)',
     'ETLFS', None,
     'Thousands',
     'Computed: 1000×(HWA/AVH)'),

    ('Real household disposable income',
     'RHHDI', None,
     'Index (2023=100)',
     'Computed: 100×HHDI/PCE'),

    ('Household net financial wealth (£bn)',
     'NFWPE', None,
     '£ billion',
     'Computed: GFWPE−LHP−OLPE'),

    ('Government consumption deflator',
     'GGFCD', None,
     'Index',
     'Computed: 100×CGGPS/CGG'),

    ('Labour productivity (£bn/mn hrs)',
     'PRODH', None,
     '£bn per million hours',
     'Computed: GDPM/HWA'),
]

forecast_cutoff = '2025Q1'
cutoff_idx = next(i for i, d in enumerate(dates) if d >= forecast_cutoff)

fig, axes = plt.subplots(2, 3, figsize=(16, 9))
axes = axes.flatten()

obr_blue = '#1f77b4'
cbp_red  = '#d62728'
shade_alpha = 0.08

for ax, (title, comp_var, pub_var, ylabel, desc) in zip(axes, PANELS):
    if comp_var not in state.values:
        ax.set_visible(False)
        continue

    series = state.values[comp_var]
    dates_pd = pd.to_datetime(dates)

    # Historical computed (solid blue)
    hist_vals = [v if i < cutoff_idx else None for i, v in enumerate(series)]
    # Forecast computed (dashed red)
    fore_vals = [v if i >= cutoff_idx else None for i, v in enumerate(series)]

    hist_clean = [(d, v) for d, v in zip(dates_pd, hist_vals) if v is not None]
    fore_clean = [(d, v) for d, v in zip(dates_pd, fore_vals) if v is not None]

    if hist_clean:
        hd, hv = zip(*hist_clean)
        ax.plot(hd, hv, color=obr_blue, linewidth=1.8, label='Computed (historical)')
    if fore_clean:
        fd, fv = zip(*fore_clean)
        ax.plot(fd, fv, color=cbp_red, linewidth=1.8, linestyle='--', label='Computed (forecast)')

    # Shade forecast region
    ax.axvspan(dates_pd[cutoff_idx], dates_pd[-1], alpha=shade_alpha, color='grey')
    ax.axvline(dates_pd[cutoff_idx], color='grey', linewidth=0.8, linestyle=':')

    ax.set_title(title, fontsize=9, fontweight='bold', pad=4)
    ax.set_ylabel(ylabel, fontsize=7)
    ax.tick_params(labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator(4))
    ax.grid(True, alpha=0.25)

    # Annotation
    ax.annotate(desc, xy=(0.02, 0.04), xycoords='axes fraction',
                fontsize=6.5, color='#555555', style='italic')

    if hist_clean or fore_clean:
        ax.legend(fontsize=6.5, loc='upper left')

fig.suptitle(
    'CBP Fiscal Framework — Forward Forecast\n'
    'Computed from OBR identity equations · March 2026 vintage · Grey shading = forecast period',
    fontsize=11, y=1.01
)
plt.tight_layout()

out = os.path.join(base, '..', 'random_graphs', 'forward_forecast_2026-03.png')
os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=150, bbox_inches='tight')
print(f"Saved: {out}")
plt.show()
