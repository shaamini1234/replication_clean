"""
Pipeline diagram showing where data comes from and how it flows
through the CBP fiscal framework.
"""

import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(22, 14))
ax.set_xlim(0, 22)
ax.set_ylim(0, 14)
ax.axis('off')
fig.patch.set_facecolor('#F5F5F5')
ax.set_facecolor('#F5F5F5')

# ── colours ────────────────────────────────────────────────────────────────────
C_OBR   = '#1565C0'   # dark blue   — OBR source
C_ONS   = '#2E7D32'   # dark green  — ONS source
C_LOAD  = '#6A1B9A'   # purple      — loading / parsing
C_STATE = '#E65100'   # orange      — model state
C_SOLVE = '#AD1457'   # crimson     — solver / derived
C_OUT   = '#37474F'   # dark grey   — outputs
C_DB    = '#00695C'   # teal        — database

def box(ax, x, y, w, h, label, sublabel, color, fontsize=8, subsize=6.5, alpha=0.88):
    p = FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.08',
                        facecolor=color, edgecolor='white', lw=1.5,
                        alpha=alpha, zorder=3)
    ax.add_patch(p)
    ax.text(x + w/2, y + h/2 + (0.08 if sublabel else 0),
            label, ha='center', va='center',
            fontsize=fontsize, fontweight='bold', color='white', zorder=4)
    if sublabel:
        ax.text(x + w/2, y + h/2 - 0.16, sublabel, ha='center', va='center',
                fontsize=subsize, color='white', alpha=0.88, zorder=4, style='italic')

def arr(ax, x1, y1, x2, y2, color='#888', lw=1.4, ls='-'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=lw,
                                linestyle=ls, connectionstyle='arc3,rad=0.0'),
                zorder=2)

def label(ax, x, y, text, color='#333', fs=8.5, bold=False):
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            color=color, fontweight='bold' if bold else 'normal')

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN 1: Raw data sources
# ══════════════════════════════════════════════════════════════════════════════
label(ax, 2.2, 13.5, 'DATA SOURCES', C_OBR, fs=10, bold=True)

# OBR EFO files
box(ax, 0.3, 11.6, 3.8, 1.6, 'OBR EFO Spreadsheets',
    'March 2026 / Nov 2025 / March 2025\ndata/2026-03/obr/*.xlsx', C_OBR, fontsize=8.5)

# Sheets within EFO
sheets = [
    (0.3, 10.8, '1.1 GDP expenditure (real)'),
    (0.3, 10.3, '1.2 GDP expenditure (nominal)'),
    (0.3,  9.8, '1.3 GDP income'),
    (0.3,  9.3, '1.6 Labour market'),
    (0.3,  8.8, '1.7 Inflation / price indices'),
    (0.3,  8.3, '1.8 Balance of payments'),
    (0.3,  7.8, '1.9 Market assumptions'),
    (0.3,  7.3, '1.11 Household balance sheet'),
    (0.3,  6.8, '1.12 Household income'),
    (0.3,  6.3, '1.14 Output gap'),
    (0.3,  6.0, '1.15 Potential output'),
    (0.3,  5.5, '6.5 Fiscal aggregates'),
]
for sx, sy, slbl in sheets:
    box(ax, sx, sy, 3.8, 0.42, slbl, None, C_OBR, fontsize=6.8, alpha=0.72)

# OBR model code
box(ax, 0.3, 4.5, 3.8, 0.8, 'OBR Winsolve Model Code',
    'docs/Macroeconomic_model_code_March_2025.txt\n372 equations', C_OBR, fontsize=8, alpha=0.85)

# ONS API
box(ax, 0.3, 2.8, 3.8, 1.5, 'ONS API',
    'www.ons.gov.uk — fetched on demand\n9 series: NTAO, EBAQ, GB7S, KAC4,\nDTWM-DTWP, MGRZ chain, N2V3, RPZW, ABMM-KLS2', C_ONS, fontsize=7.8)

# ONS codes reference
box(ax, 0.3, 1.6, 3.8, 0.9, 'OBR Variable → ONS Code Map',
    'docs/OBR_Model_Variables_March_2025.xlsx\n466 variables with ONS identifiers', C_ONS, fontsize=7.5, alpha=0.75)

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN 2: Loaders / parsers
# ══════════════════════════════════════════════════════════════════════════════
label(ax, 7.5, 13.5, 'LOADING & PARSING', C_LOAD, fs=10, bold=True)

box(ax, 5.5, 10.5, 4.0, 1.2, 'OBRForecastLoader',
    'inputs/loaders.py\nParses each sheet into typed dataclasses\nHandles vintage naming conventions', C_LOAD)

# Data stores
stores = [
    (5.5, 9.7,  'gdp_components          (93 quarters)'),
    (5.5, 9.25, 'nominal_gdp             (93 quarters)'),
    (5.5, 8.8,  'labour_market           (93 quarters)'),
    (5.5, 8.35, 'price_indices           (93 quarters)'),
    (5.5, 7.9,  'market_assumptions      (93 quarters)'),
    (5.5, 7.45, 'balance_of_payments     (93 quarters)'),
    (5.5, 7.0,  'household_balance_sheet (77 quarters)'),
    (5.5, 6.55, 'household_income        (77 quarters)'),
    (5.5, 6.1,  'output_gap              (215 quarters)'),
    (5.5, 5.65, 'potential_output        (49 quarters)'),
    (5.5, 5.2,  'fiscal_aggregates       (6 fiscal years)'),
]
for sx, sy, slbl in stores:
    box(ax, sx, sy, 4.0, 0.38, slbl, None, C_LOAD, fontsize=6.5, alpha=0.65)

box(ax, 5.5, 4.0, 4.0, 1.0, 'WinsolveParser',
    'core/winsolve/parser.py\nParses equation text → AST\n372 equations, 23 groups', C_LOAD)

box(ax, 5.5, 2.5, 4.0, 1.2, 'ONSFetcher + ONSLoader',
    'inputs/ons_fetcher.py / ons_loader.py\nFetches ONS series by code, handles\ncompound formulas (A+B, 100*(A-B)/(C-D))', C_ONS)

box(ax, 5.5, 1.5, 4.0, 0.75, 'DataManager',
    'inputs/data_manager.py  —  orchestrates all loaders', C_LOAD, fontsize=8)

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN 3: Model state & solver
# ══════════════════════════════════════════════════════════════════════════════
label(ax, 13.0, 13.5, 'MODEL STATE & SOLVER', C_STATE, fs=10, bold=True)

box(ax, 10.5, 11.5, 5.0, 1.6, 'ModelState',
    'core/winsolve/variable_map.py\n105 variables loaded from published data\n(83 OBR EFO + 9 ONS + 13 calibrated constants)\nCanonical date list: 2008Q1–2031Q1 (93 quarters)', C_STATE)

box(ax, 10.5, 9.7, 5.0, 1.5, 'IdentitySolver',
    'core/winsolve/solver.py\nDependency-ordered Tarjan SCC solver\nComputes 33 derived variables from identities\ne.g. GVA=GDPM−BPA, RHHDI=100×HHDI/PCE\nTotal: 138 variables with substantial coverage', C_SOLVE)

box(ax, 10.5, 8.0, 5.0, 1.4, 'EquationValidator',
    'core/winsolve/equation_validator.py\n79 equations testable (258 skipped — missing vars)\n71/79 PASS  ·  8 FAIL (model approximations\nor chain-linking artefacts — all understood)', C_SOLVE)

# Variable map
box(ax, 10.5, 6.3, 5.0, 1.4, 'WinsolveModel',
    'core/winsolve/model.py\n372 equations parsed from OBR model code\nDependency graph  ·  endogenous/exogenous split\n370 endogenous vars  ·  220 exogenous vars', C_STATE, alpha=0.75)

# Remaining gaps
box(ax, 10.5, 4.8, 5.0, 1.2,
    'Remaining gaps (258 equations skipped)',
    'Needs ONS: PPI (GB7S→PMNOG chain), capital stocks,\nPSF monthly, BoP trade volumes (BQKO)\nOBR-internal: add-factors, wage adjustment params', '#B71C1C', fontsize=7.5)

# Behavioural
box(ax, 10.5, 3.4, 5.0, 1.1, 'Consumption ECM (Track B — started)',
    'cbp_fiscal_framework/consumption_ecm.py\nEstimated OLS on 2012–2024 · inputs: RHHDI, NFWPE, LFSUR, R\nForecasts ~£25–65bn below OBR (housing wealth gap)', '#6A1B9A')

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN 4: Database & outputs
# ══════════════════════════════════════════════════════════════════════════════
label(ax, 18.8, 13.5, 'STORAGE & OUTPUTS', C_DB, fs=10, bold=True)

box(ax, 16.5, 11.2, 5.2, 2.2, 'Time Series Database (proposed)',
    'SQLite · cbp_fiscal_framework/db/timeseries.db\n\nTables:\n  series(id, label, source, unit, ons_code, obr_sheet)\n  observations(series_id, vintage, quarter, value)\n\nEliminates re-fetching OBR XLSXs and ONS API\nevery run. Query by series, vintage, date range.', C_DB)

box(ax, 16.5, 9.5, 5.2, 1.4, 'Validation Report',
    '71/79 equations passing\nPer-equation: tested periods, max residual\nFailing equations all understood — documented', C_OUT)

box(ax, 16.5, 7.9, 5.2, 1.3, 'Forward Forecast Charts',
    'random_graphs/\ncomputed_vs_obr_2026-03.png\nconsumption_ecm_2026-03.png\nforward_forecast_2026-03.png', C_OUT)

box(ax, 16.5, 6.5, 5.2, 1.1, 'Dependency Maps',
    'cons_dependency_map.png\nobr_equation_residuals_2026-03.png', C_OUT)

box(ax, 16.5, 5.2, 5.2, 1.0, 'OBR Equation Residual Plots',
    'Predicted vs observed for 7 failing identities\nDiagnoses: scaling bugs fixed, chain-link artefacts', C_OUT)

# ══════════════════════════════════════════════════════════════════════════════
# ARROWS
# ══════════════════════════════════════════════════════════════════════════════

# Sources → Loaders
arr(ax, 4.1, 11.5, 5.5, 11.2, C_OBR)   # EFO → OBRForecastLoader
arr(ax, 4.1,  4.9,  5.5,  4.5, C_OBR)   # model code → parser
arr(ax, 4.1,  3.5,  5.5,  3.1, C_ONS)   # ONS API → fetcher
arr(ax, 4.1,  1.95, 5.5,  1.85, C_ONS)  # ONS variable map → fetcher

# Loaders → DataManager
arr(ax, 7.5,  9.6,  7.5,  2.25, C_LOAD, lw=1.2)  # stores → DM (implied)

# DataManager → ModelState
arr(ax, 9.5,  1.85, 10.5, 11.6, C_LOAD, lw=1.4)

# ModelState → Solver
arr(ax, 13.0, 11.5, 13.0, 11.2, C_STATE)

# Solver → Validator
arr(ax, 13.0, 9.7, 13.0, 9.4, C_SOLVE)

# Solver → ECM
arr(ax, 13.0, 9.7, 13.0, 4.5, C_SOLVE)

# Model code → WinsolveModel
arr(ax, 7.5, 4.0, 10.5, 6.9, C_LOAD, lw=1.2)

# ModelState → Database
arr(ax, 15.5, 11.8, 16.5, 12.2, C_DB, lw=1.5)

# Validator → Report
arr(ax, 15.5, 8.7, 16.5, 9.9, C_OUT)

# ECM → Charts
arr(ax, 15.5, 3.9, 16.5, 8.2, C_OUT)

# ══════════════════════════════════════════════════════════════════════════════
# COLUMN SEPARATORS
# ══════════════════════════════════════════════════════════════════════════════
for x in [4.5, 10.0, 16.0]:
    ax.axvline(x, color='#CCCCCC', lw=0.8, ls='--', alpha=0.5, zorder=1)

# ══════════════════════════════════════════════════════════════════════════════
# LEGEND
# ══════════════════════════════════════════════════════════════════════════════
legend = [
    mpatches.Patch(facecolor=C_OBR,   label='OBR published data'),
    mpatches.Patch(facecolor=C_ONS,   label='ONS API data'),
    mpatches.Patch(facecolor=C_LOAD,  label='Loading / parsing layer'),
    mpatches.Patch(facecolor=C_STATE, label='Model state'),
    mpatches.Patch(facecolor=C_SOLVE, label='Solver / validator'),
    mpatches.Patch(facecolor=C_DB,    label='Database / outputs'),
]
ax.legend(handles=legend, loc='lower center', ncol=6,
          bbox_to_anchor=(0.5, -0.02), fontsize=8.5,
          framealpha=0.9, edgecolor='#CCCCCC')

fig.suptitle('CBP Fiscal Framework — Data Pipeline', fontsize=14, fontweight='bold', y=0.99)
plt.tight_layout(rect=[0, 0.03, 1, 0.98])

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', 'random_graphs', 'pipeline_diagram.png')
os.makedirs(os.path.dirname(out), exist_ok=True)
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#F5F5F5')
print(f"Saved: {out}")
plt.show()
