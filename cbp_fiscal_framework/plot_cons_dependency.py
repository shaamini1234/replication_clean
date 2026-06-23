"""
Dependency diagram for the CBP Consumption ECM.

Shows what CONS depends on, what those inputs depend on,
and how each variable is sourced.
"""

import os, sys
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# ── colour palette ─────────────────────────────────────────────────────────────
C_OBR      = '#2196F3'   # blue   — OBR published directly
C_IDENTITY = '#4CAF50'   # green  — computed from identity equation
C_CBP      = '#FF9800'   # orange — CBP estimated / behavioural assumption
C_MISSING  = '#F44336'   # red    — not available / OBR-internal

BG         = '#FAFAFA'
TEXT_DARK  = '#1A1A1A'

fig, ax = plt.subplots(figsize=(18, 11))
ax.set_xlim(0, 18)
ax.set_ylim(0, 11)
ax.axis('off')
ax.set_facecolor(BG)
fig.patch.set_facecolor(BG)

# ── node drawing helper ────────────────────────────────────────────────────────

def node(ax, x, y, label, sublabel, color, w=2.3, h=0.7, fontsize=8.5):
    box = FancyBboxPatch((x - w/2, y - h/2), w, h,
                          boxstyle='round,pad=0.05',
                          facecolor=color, edgecolor='white',
                          linewidth=1.5, alpha=0.92, zorder=3)
    ax.add_patch(box)
    ax.text(x, y + 0.08, label, ha='center', va='center',
            fontsize=fontsize, fontweight='bold', color='white', zorder=4)
    if sublabel:
        ax.text(x, y - 0.19, sublabel, ha='center', va='center',
                fontsize=6.5, color='white', alpha=0.88, zorder=4, style='italic')

def arrow(ax, x1, y1, x2, y2, color='#888888'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color,
                                lw=1.4, connectionstyle='arc3,rad=0.0'),
                zorder=2)

def dashed_arrow(ax, x1, y1, x2, y2, color='#BBBBBB'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color,
                                lw=1.2, linestyle='dashed',
                                connectionstyle='arc3,rad=0.0'),
                zorder=2)

# ── column x positions ─────────────────────────────────────────────────────────
X_RAW  = 2.8    # column 1: raw OBR published data
X_COMP = 7.5    # column 2: identity-computed variables
X_CONS = 12.5   # column 3: consumption equation
X_MISS = 16.5   # column 4: missing / OBR-internal

# ── COLUMN 1: Raw OBR published data ──────────────────────────────────────────

raw_nodes = [
    # (y,  label,   sublabel)
    (9.8,  'HHDI',   'Household disposable income\n(Sheet 1.12, £bn nominal)'),
    (8.7,  'PCE',    'Consumer expenditure deflator\n(Sheet 1.7, 2023=100)'),
    (7.4,  'ULFS',   'ILO unemployment, millions\n(Sheet 1.6)'),
    (6.2,  'HWA',    'Total hours worked, mn hrs\n(Sheet 1.6)'),
    (5.2,  'AVH',    'Average hours worked\n(Sheet 1.6)'),
    (3.9,  'GFWPE',  'Household financial assets, £bn\n(Sheet 1.11, from 2012Q1)'),
    (2.9,  'LHP',    'Secured liabilities (mortgages)\n(Sheet 1.11, from 2012Q1)'),
    (1.9,  'OLPE',   'Other liabilities, £bn\n(Sheet 1.11, from 2012Q1)'),
    (0.8,  'R',      'Bank rate, %\n(Sheet 1.9)'),
]

for y, lbl, sub in raw_nodes:
    node(ax, X_RAW, y, lbl, sub, C_OBR, w=2.8, h=0.72)

# ── COLUMN 2: Identity-computed variables ──────────────────────────────────────

comp_nodes = [
    (9.3,  'RHHDI',  'Real household disposable income\n= 100 × HHDI / PCE'),
    (6.8,  'ETLFS',  'Employment (LFS), thousands\n= 1000 × HWA / AVH'),
    (5.6,  'LFSUR',  'Unemployment rate, %\n= 100 × ULFS / (ETLFS+ULFS)'),
    (2.9,  'NFWPE',  'Net household financial wealth\n= GFWPE − LHP − OLPE'),
]

for y, lbl, sub in comp_nodes:
    node(ax, X_COMP, y, lbl, sub, C_IDENTITY, w=3.0, h=0.76)

# ── COLUMN 3: Consumption equation ────────────────────────────────────────────

# Short-run ECM box
node(ax, X_CONS, 7.8, 'CBP ECM Coefficients',
     'Estimated by OLS on 2012–2024 outturn\n(α, β₁, β₂, β₃, γ, long-run)',
     C_CBP, w=3.2, h=0.82)

# CONS target
node(ax, X_CONS, 5.5, 'CONS', 'Private consumption, £bn CVM\n(TARGET)', C_CBP, w=2.8, h=0.78)

# ECM structure label
ax.text(X_CONS, 10.3,
        'SHORT-RUN:\nΔlog(CONS) = α + β₁·Δlog(RHHDI) + β₂·ΔLFSUR + β₃·ΔR + γ·EC(−1)',
        ha='center', va='center', fontsize=7.8, color='#333333',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#FFF3E0', edgecolor=C_CBP, lw=1.2))

ax.text(X_CONS, 9.3,
        'LONG-RUN (error-correction term):\nlog(CONS) = δ₀ + δ₁·log(RHHDI) + δ₂·log(NFWPE/PCE) + δ₃·LFSUR',
        ha='center', va='center', fontsize=7.8, color='#333333',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='#FFF3E0', edgecolor=C_CBP, lw=1.2))

# ── COLUMN 4: Missing variables ────────────────────────────────────────────────

miss_nodes = [
    (8.5,  'GPW',        "Gross product wages\n(OBR: needs WFJ/ET — WFJ\nloaded but equation needs\nmarket-sector split)"),
    (6.5,  'Add-factors','OBR residual adjustments\napplied each vintage\n(not published externally)'),
    (4.5,  'RMORT',      "Avg. mortgage rate (loaded ✓)\nbut not in CBP ECM yet —\nadding would reduce\npessimism gap"),
]

for y, lbl, sub in miss_nodes:
    node(ax, X_MISS, y, lbl, sub, C_MISSING, w=3.0, h=0.88)

# ── ARROWS: raw → computed ─────────────────────────────────────────────────────

# HHDI + PCE → RHHDI
arrow(ax, X_RAW+1.4, 9.8,   X_COMP-1.5, 9.4)
arrow(ax, X_RAW+1.4, 8.7,   X_COMP-1.5, 9.2)

# HWA + AVH → ETLFS
arrow(ax, X_RAW+1.4, 6.2,   X_COMP-1.5, 6.85)
arrow(ax, X_RAW+1.4, 5.2,   X_COMP-1.5, 6.75)

# ULFS + ETLFS → LFSUR
arrow(ax, X_RAW+1.4, 7.4,   X_COMP-1.5, 5.65)
arrow(ax, X_COMP+0.0, 6.42, X_COMP+0.0, 5.98)   # ETLFS down to LFSUR

# GFWPE + LHP + OLPE → NFWPE
arrow(ax, X_RAW+1.4, 3.9,   X_COMP-1.5, 3.0)
arrow(ax, X_RAW+1.4, 2.9,   X_COMP-1.5, 2.88)
arrow(ax, X_RAW+1.4, 1.9,   X_COMP-1.5, 2.76)

# ── ARROWS: computed / raw → CONS ─────────────────────────────────────────────

# RHHDI → CONS
arrow(ax, X_COMP+1.5, 9.3,  X_CONS-1.6, 5.75)
# LFSUR → CONS
arrow(ax, X_COMP+1.5, 5.6,  X_CONS-1.6, 5.55)
# NFWPE → CONS (long-run EC)
arrow(ax, X_COMP+1.5, 2.9,  X_CONS-1.6, 5.3)
# R → CONS
arrow(ax, X_RAW+1.4, 0.8,   X_CONS-1.6, 5.1)
# CBP coefficients → CONS
arrow(ax, X_CONS, 7.38,      X_CONS, 5.92)

# ── DASHED ARROWS: missing variables (what OBR uses but we don't) ──────────────
dashed_arrow(ax, X_MISS-1.5, 8.5,  X_CONS+1.6, 7.9)   # GPW → ECM
dashed_arrow(ax, X_MISS-1.5, 6.5,  X_CONS+1.6, 7.75)  # add-factors → ECM
dashed_arrow(ax, X_MISS-1.5, 4.5,  X_CONS+1.6, 5.5)   # RMORT → CONS

# ── COLUMN LABELS ─────────────────────────────────────────────────────────────

for x, lbl, col in [
    (X_RAW,  'OBR PUBLISHED DATA', C_OBR),
    (X_COMP, 'COMPUTED\n(identity equations)', C_IDENTITY),
    (X_CONS, 'CBP CONSUMPTION MODEL', C_CBP),
    (X_MISS, 'NOT YET USED / MISSING', C_MISSING),
]:
    ax.text(x, 10.75, lbl, ha='center', va='center', fontsize=9,
            fontweight='bold', color=col)
    ax.axvline(x, color=col, alpha=0.12, lw=20, ymin=0, ymax=0.93)

# ── LEGEND ────────────────────────────────────────────────────────────────────
legend_items = [
    mpatches.Patch(facecolor=C_OBR,      label='OBR published (EFO spreadsheets)'),
    mpatches.Patch(facecolor=C_IDENTITY,  label='Computed from identity equation'),
    mpatches.Patch(facecolor=C_CBP,       label='CBP estimated / behavioural assumption'),
    mpatches.Patch(facecolor=C_MISSING,   label='Not yet in model / OBR-internal only'),
]
ax.legend(handles=legend_items, loc='lower center', ncol=4,
          bbox_to_anchor=(0.5, -0.02), fontsize=8.5,
          framealpha=0.9, edgecolor='#CCCCCC')

# Dashed arrow label
ax.annotate('dashed = OBR uses this\nbut CBP does not yet',
            xy=(14.8, 4.2), fontsize=7, color='#888888', style='italic')

fig.suptitle('Consumption ECM — Dependency Map', fontsize=13, fontweight='bold', y=0.98)
plt.tight_layout(rect=[0, 0.03, 1, 0.97])

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', 'random_graphs', 'cons_dependency_map.png')
os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=BG)
print(f"Saved: {out}")
plt.show()
