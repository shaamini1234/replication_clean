"""
CBP consumption ECM — estimate on outturn, forecast forward.

Two-step Engle-Granger ECM:
  Step 1 (long-run): log(CONS) = a + b*log(RHHDI) + c*log(NFWPE/PCE) + d*LFSUR
  Step 2 (short-run): Δlog(CONS) = α + β1*Δlog(RHHDI) + β2*ΔLFSUR + β3*ΔR + γ*EC(-1)

All inputs available from loaded OBR data + identity solver.

Usage:
    python3 consumption_ecm.py
"""

import os, sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from cbp_fiscal_framework.inputs.data_manager import DataManager
from cbp_fiscal_framework.core.winsolve import (
    build_model_state, WinsolveParser, WinsolveModel, IdentitySolver, solve_equation,
)
import logging
logging.basicConfig(level=logging.WARNING)

# ── load and solve ────────────────────────────────────────────────────────────

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

# ── extract series ────────────────────────────────────────────────────────────

def get(var):
    return state.values.get(var, [None]*len(dates))

CONS  = get('CONS')
RHHDI = get('RHHDI')
NFWPE = get('NFWPE')
PCE   = get('PCE')
LFSUR = get('LFSUR')
R     = get('R')

# Forecast cutoff — last period with ONS outturn data
FORECAST_CUTOFF = '2025Q1'
cutoff_idx = next(i for i, d in enumerate(dates) if d >= FORECAST_CUTOFF)

# Estimation sample: periods with all variables available, up to cutoff
def valid_range(series_list, end):
    """Return indices where all series have non-None, positive values."""
    ok = []
    for t in range(1, end):
        try:
            vals = [s[t] for s in series_list]
            if all(v is not None and v > 0 for v in vals):
                ok.append(t)
        except IndexError:
            pass
    return ok

est_idx = valid_range([CONS, RHHDI, NFWPE, PCE, LFSUR, R], cutoff_idx)
print(f"Estimation sample: {dates[est_idx[0]]} to {dates[est_idx[-1]]} ({len(est_idx)} quarters)")

# ── OLS helper ────────────────────────────────────────────────────────────────

def ols(Y, X):
    """OLS: β = (X'X)^-1 X'y. X should include constant column."""
    X = np.array(X, dtype=float)
    Y = np.array(Y, dtype=float)
    beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    fitted = X @ beta
    resid = Y - fitted
    ss_res = resid @ resid
    ss_tot = ((Y - Y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot
    return beta, fitted, resid, r2

# ── Step 1: long-run cointegrating equation ───────────────────────────────────

log_cons  = np.array([np.log(CONS[t])  for t in est_idx])
log_rhhdi = np.array([np.log(RHHDI[t]) for t in est_idx])
log_wealth= np.array([np.log(NFWPE[t] / (PCE[t] / 100)) for t in est_idx])
lfsur_arr = np.array([LFSUR[t]         for t in est_idx])

X_lr = np.column_stack([np.ones(len(est_idx)), log_rhhdi, log_wealth, lfsur_arr])
beta_lr, fitted_lr, ec_lr, r2_lr = ols(log_cons, X_lr)

print(f"\nLong-run equation (R² = {r2_lr:.3f})")
print(f"  log(CONS) = {beta_lr[0]:.4f} + {beta_lr[1]:.4f}*log(RHHDI)"
      f" + {beta_lr[2]:.4f}*log(NFWPE/PCE) + {beta_lr[3]:.4f}*LFSUR")

# EC term aligned to estimation sample (lagged 1)
ec_full = [None] * len(dates)
for i, t in enumerate(est_idx):
    ec_full[t] = ec_lr[i]

# ── Step 2: short-run ECM ─────────────────────────────────────────────────────

# Need t and t-1 both in est_idx
sr_idx = [t for t in est_idx if t-1 in est_idx and ec_full[t-1] is not None]

dlog_cons  = [np.log(CONS[t]) - np.log(CONS[t-1])   for t in sr_idx]
dlog_rhhdi = [np.log(RHHDI[t]) - np.log(RHHDI[t-1]) for t in sr_idx]
dlfsur     = [LFSUR[t] - LFSUR[t-1]                 for t in sr_idx]
dr         = [R[t] - R[t-1]                          for t in sr_idx]
ec_lag     = [ec_full[t-1]                           for t in sr_idx]

X_sr = np.column_stack([np.ones(len(sr_idx)), dlog_rhhdi, dlfsur, dr, ec_lag])
beta_sr, fitted_sr, resid_sr, r2_sr = ols(dlog_cons, X_sr)

α, β1, β2, β3, γ = beta_sr
print(f"\nShort-run ECM (R² = {r2_sr:.3f})")
print(f"  Δlog(CONS) = {α:.4f} + {β1:.4f}*Δlog(RHHDI) + {β2:.4f}*ΔLFSUR"
      f" + {β3:.4f}*ΔR + {γ:.4f}*EC(-1)")
print(f"  Speed of adjustment: {γ:.4f} (half-life ≈ {-np.log(2)/np.log(1+γ):.1f} quarters)")

# ── Dynamic forecast ──────────────────────────────────────────────────────────

cons_cbp = [None] * len(dates)
for t in est_idx:
    cons_cbp[t] = CONS[t]  # in-sample: use actuals for initialisation

for t in range(cutoff_idx, len(dates)):
    t_prev = t - 1
    if cons_cbp[t_prev] is None:
        break
    if any(s[t] is None for s in [RHHDI, NFWPE, PCE, LFSUR, R]):
        break
    if RHHDI[t_prev] is None or NFWPE[t_prev] is None:
        break

    # EC term at t-1 using CBP's own forecast path
    try:
        ec_t1 = (np.log(cons_cbp[t_prev])
                 - beta_lr[0]
                 - beta_lr[1] * np.log(RHHDI[t_prev])
                 - beta_lr[2] * np.log(NFWPE[t_prev] / (PCE[t_prev] / 100))
                 - beta_lr[3] * LFSUR[t_prev])

        dlog_rhhdi_t = np.log(RHHDI[t]) - np.log(RHHDI[t_prev])
        dlfsur_t     = LFSUR[t] - LFSUR[t_prev]
        dr_t         = R[t] - R[t_prev]

        dlog_cons_t = α + β1*dlog_rhhdi_t + β2*dlfsur_t + β3*dr_t + γ*ec_t1
        cons_cbp[t] = cons_cbp[t_prev] * np.exp(dlog_cons_t)
    except Exception:
        break

# ── Plot ──────────────────────────────────────────────────────────────────────

dates_pd = pd.to_datetime([d.replace('Q1','-01-01').replace('Q2','-04-01')
                            .replace('Q3','-07-01').replace('Q4','-10-01')
                            for d in dates])

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Panel 1: CONS levels
ax = axes[0]
# OBR published (history solid, forecast dashed)
obr_hist = [(dates_pd[t], CONS[t]) for t in range(len(dates))
            if t < cutoff_idx and CONS[t] is not None]
obr_fore = [(dates_pd[t], CONS[t]) for t in range(len(dates))
            if t >= cutoff_idx and CONS[t] is not None]
cbp_fore = [(dates_pd[t], cons_cbp[t]) for t in range(len(dates))
            if t >= cutoff_idx and cons_cbp[t] is not None]

if obr_hist:
    d, v = zip(*obr_hist); ax.plot(d, v, '#1f77b4', lw=1.8, label='OBR (outturn)')
if obr_fore:
    d, v = zip(*obr_fore); ax.plot(d, v, '#1f77b4', lw=1.8, ls='--', label='OBR (forecast)')
if cbp_fore:
    d, v = zip(*cbp_fore); ax.plot(d, v, '#d62728', lw=2.0, label='CBP ECM forecast')

ax.axvspan(dates_pd[cutoff_idx], dates_pd[-1], alpha=0.06, color='grey')
ax.axvline(dates_pd[cutoff_idx], color='grey', lw=0.8, ls=':')
ax.set_title('Private Consumption (£bn CVM)', fontsize=10, fontweight='bold')
ax.set_ylabel('£ billion (2023 prices)')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax.xaxis.set_major_locator(mdates.YearLocator(4))
ax.grid(True, alpha=0.25)
ax.legend(fontsize=8)
ax.tick_params(labelsize=8)

# Panel 2: Deviation (CBP forecast - OBR forecast)
ax2 = axes[1]
deviations = [(dates_pd[t], cons_cbp[t] - CONS[t])
              for t in range(cutoff_idx, len(dates))
              if cons_cbp[t] is not None and CONS[t] is not None]
if deviations:
    d, v = zip(*deviations)
    v = np.array(v)
    ax2.bar(d, v, width=60, color=['#d62728' if x < 0 else '#2ca02c' for x in v], alpha=0.7)
    ax2.axhline(0, color='black', lw=0.8)
    ax2.set_title('CBP minus OBR Forecast (£bn)', fontsize=10, fontweight='bold')
    ax2.set_ylabel('£bn difference')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax2.xaxis.set_major_locator(mdates.YearLocator(1))
    ax2.grid(True, alpha=0.25)
    ax2.tick_params(labelsize=8)

    final_dev = v[-1]
    final_date = d[-1].strftime('%Y')
    ax2.annotate(f'{final_dev:+.1f}bn by {final_date}',
                 xy=(d[-1], final_dev), xytext=(-40, 15),
                 textcoords='offset points', fontsize=8,
                 arrowprops=dict(arrowstyle='->', color='black'))

fig.suptitle(
    'CBP Consumption ECM vs OBR March 2026 Forecast\n'
    'ECM estimated on 2013–2024 outturn · Inputs: RHHDI, NFWPE, LFSUR, R',
    fontsize=10, y=1.02
)
plt.tight_layout()

out = os.path.join(base, '..', 'random_graphs', 'consumption_ecm_2026-03.png')
plt.savefig(out, dpi=150, bbox_inches='tight')
print(f"\nSaved: {out}")
plt.show()
