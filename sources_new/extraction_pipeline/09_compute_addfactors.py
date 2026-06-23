"""
Compute and store add-factors for all DLOG and D behavioural equations.

An add-factor is the gap between what an equation predicts and what actually
happened in that quarter. Storing them lets the model track historical data
exactly during the outturn period, and start the forecast from the right place.

For a DLOG equation like  dlog(CONS) = β₁*X₁ + β₂*X₂ + ...:
  add_factor = log(CONS_actual / CONS_prev) - equation_rhs
  (i.e., the residual in log-difference space)

For a D equation like  d(RIC) = γ₁*Z₁ + ...:
  add_factor = (RIC_actual - RIC_prev) - equation_rhs
  (i.e., the residual in first-difference space)

These are stored in the DB as source='ADDFACTOR'. The runner then adds them
back when solving: for DLOG, value *= exp(addfactor); for D, value += addfactor.

Requires bootstrap_seeds.py to have run first (so RIC, EPS, RPRICE, TDOIL
have COMPUTED values in the DB).

Uses /tmp write pattern (virtiofs limitation).
"""

import os, sys, math, shutil, sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cbp_fiscal_framework.core.winsolve import (
    WinsolveParser, WinsolveModel
)
from cbp_fiscal_framework.core.winsolve.parser import LHSForm
from cbp_fiscal_framework.core.winsolve.evaluator import ModelState, evaluate

MODEL_TXT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'docs', 'Macroeconomic_model_code_March_2025.txt'
)

DB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'timeseries_p5.db')
WORK_DB  = '/tmp/timeseries_p5_addfactors.db'
PUB_DATE = '2026-06-17'

shutil.copy(DB_PATH, WORK_DB)
conn = sqlite3.connect(WORK_DB)

# ── 1. Parse model ────────────────────────────────────────────────────────────
print("Step 1: Parse model")
with open(MODEL_TXT) as f:
    equations = WinsolveParser.parse_model(f.read())
model = WinsolveModel(equations)

# Only compute add-factors for DLOG and D equations (not accounting identities).
behav_eqs = [eq for eq in equations
             if eq.lhs_form in (LHSForm.DLOG, LHSForm.D)
             and eq.lhs_variable != '?']
print(f"  {len(behav_eqs)} behavioural equations (DLOG + D) to process")

# ── 2. Load all outturn data from DB ─────────────────────────────────────────
print("Step 2: Load outturn data from DB")

SOURCE_PRIORITY = {'ONS': 0, 'OBR_EFO': 1, 'COMPUTED': 2}

rows = conn.execute(
    "SELECT series_id, source, quarter, value FROM observations"
).fetchall()

# Best value per (series, quarter)
best: dict = {}
for sid, src, q, val in rows:
    pri = SOURCE_PRIORITY.get(src, 99)
    if src == 'ADDFACTOR':
        continue   # never use existing add-factors as inputs
    if (sid, q) not in best or pri < best[(sid, q)][0]:
        best[(sid, q)] = (pri, val)

# Group by variable → {quarter: value}
data: dict = defaultdict(dict)
for (sid, q), (_, val) in best.items():
    data[sid][q] = val

# All outturn quarters available
all_quarters = sorted({q for (_, q) in best})
# Limit to genuine outturn (before forecast — use 2025Q4 as safe boundary)
outturn_quarters = [q for q in all_quarters if q <= '2025Q4']
print(f"  {len(outturn_quarters)} outturn quarters ({outturn_quarters[0]} – {outturn_quarters[-1]})")
print(f"  {len(data)} variables loaded")

# ── 3. Build a ModelState for the full range ──────────────────────────────────
# We need a state object that evaluate() can call. We build it over the full
# outturn range plus a few quarters of pre-history for lag access.

print("Step 3: Build ModelState")

# Date list: start from 2004Q1 (for lag-4 headroom at 2008Q1)
def gen_quarters(start, end):
    result = []
    q = start
    while q <= end:
        result.append(q)
        y, n = int(q[:4]), int(q[5])
        q = f"{y}Q{n+1}" if n < 4 else f"{y+1}Q1"
    return result

dates = gen_quarters('2004Q1', '2025Q4')
state = ModelState(dates)

for var, qmap in data.items():
    series = [qmap.get(d) for d in dates]
    state.init_variable(var, series)

print(f"  State: {len(dates)} dates, {len(state.values)} variables")

# ── 4. Compute add-factors ────────────────────────────────────────────────────
print("Step 4: Computing add-factors")

addfactors_written = 0
skipped_no_data    = 0
skipped_eval_error = 0

def get_val(var, t):
    """Safe read from state at index t."""
    try:
        if var not in state.values:
            return None
        v = state.values[var][t]
        return v
    except IndexError:
        return None

for eq in behav_eqs:
    var = eq.lhs_variable
    var_written = 0

    for i, q in enumerate(dates):
        if q not in outturn_quarters:
            continue  # only compute add-factors for outturn periods

        state.current_t = i

        # We need the actual value and its lag-1 to compute the actual LHS form.
        actual_t  = get_val(var, i)
        actual_t1 = get_val(var, i - 1) if i > 0 else None

        if actual_t is None or actual_t1 is None:
            skipped_no_data += 1
            continue

        # Evaluate the equation's RHS using actual data
        try:
            rhs_val = evaluate(eq.rhs, state)
        except Exception:
            skipped_eval_error += 1
            continue

        # Compute the add-factor: actual_lhs_form - equation_rhs
        try:
            if eq.lhs_form == LHSForm.DLOG:
                if actual_t <= 0 or actual_t1 <= 0:
                    skipped_no_data += 1
                    continue
                actual_lhs = math.log(actual_t / actual_t1)
                addf = actual_lhs - rhs_val

            elif eq.lhs_form == LHSForm.D:
                actual_lhs = actual_t - actual_t1
                addf = actual_lhs - rhs_val

            else:
                continue  # shouldn't happen (we filtered above)

        except (ValueError, ZeroDivisionError):
            skipped_eval_error += 1
            continue

        # Skip negligibly small add-factors (equation fits well enough)
        if abs(addf) < 1e-12:
            continue

        conn.execute(
            """INSERT OR REPLACE INTO observations
               (series_id, source, publication_date, quarter, value, data_type)
               VALUES (?, 'ADDFACTOR', ?, ?, ?, 'ADDFACTOR')""",
            (var, PUB_DATE, q, addf)
        )
        addfactors_written += 1
        var_written += 1

    if var_written > 0:
        print(f"  {var:<16}: {var_written} add-factors")

conn.commit()

print(f"\nSummary:")
print(f"  Add-factors written  : {addfactors_written}")
print(f"  Skipped (no data)    : {skipped_no_data}")
print(f"  Skipped (eval error) : {skipped_eval_error}")

conn.close()
shutil.copy(WORK_DB, DB_PATH)
print(f"\nDone — copied working DB back to {DB_PATH}")
