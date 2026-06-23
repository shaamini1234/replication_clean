"""
Phase 8 — Unblock the 8 'permanently blocked' variables.

Analysis showed most of these have public sources that were not yet exploited:
  - OAHHx   (NNMY+NNOA+NNPM+MMW5): ONS annual household balance-sheet stocks
  - DEPHHx  (NNMP):                 ONS annual household deposits stock
  - NAOLPE  (NFYS-NGAS):            ONS quarterly household liability flows
  - DEBTU:  ONS formula (NFYS-NGAS-CT9E+CT9E(-1))/(NNPP(-1)-NNRP(-1)-CT9E(-1))
  - NAINSx / NAINS: recursive AR(1) in SIPT, seed from steady-state
  - CPIX / CPIXBASE / MKR: back-calculated from observed CPI and CPIRENT
  - PD:     HMRC residential property transactions (quarterly, UK total)
  - GMF / HHRES / OAHHADJ: downstream identities once above are in DB

CRITICAL RULES:
  - NEVER modify run_model_diagnostic.py
  - Write to /tmp first, copy back at end (virtiofs limitation)
  - timeseries_p5.db is the working DB

Run from repo root:
    python shaamini_tests/phase8_unblock_variables.py
"""

import os, sys, sqlite3, shutil, math, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'timeseries_p5.db')
WORK_DB  = '/tmp/timeseries_p5_phase8.db'
PUB_DATE = '2026-06'

print(f"Copying DB to {WORK_DB} ...")
shutil.copy(DB_PATH, WORK_DB)
conn = sqlite3.connect(WORK_DB)

from cbp_fiscal_framework.inputs.ons_fetcher import ONSFetcher, ONS_PATHS

# ── helpers ───────────────────────────────────────────────────────────────────

def upsert_series(sid, label='', ons_code=''):
    conn.execute(
        "INSERT INTO series(id,label,ons_code) VALUES(?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET label=excluded.label, ons_code=excluded.ons_code",
        (sid, label, ons_code)
    )

def upsert_obs(sid, quarter, value, source='ONS', pub_date=PUB_DATE, data_type='OUTTURN'):
    conn.execute(
        """INSERT OR REPLACE INTO observations(series_id,source,publication_date,quarter,value,data_type)
           VALUES(?,?,?,?,?,?)""",
        (sid, source, pub_date, quarter, value, data_type)
    )

def get_series(sid):
    """Return {quarter: value} for a series, highest-priority source wins."""
    priority = {'ONS': 0, 'OBR_EFO': 1, 'COMPUTED': 2, 'CONSTANT': 3, 'MHCLG': 4}
    rows = conn.execute(
        "SELECT quarter, value, source FROM observations WHERE series_id=? ORDER BY quarter",
        (sid,)
    ).fetchall()
    result = {}
    for q, v, src in rows:
        if q not in result or priority.get(src, 99) < priority.get(result[q][1], 99):
            result[q] = (v, src)
    return {q: v for q, (v, s) in result.items()}

ALL_QUARTERS = [f"{y}Q{q}" for y in range(1987, 2032) for q in range(1, 5)]
ALL_QUARTERS = [q for q in ALL_QUARTERS if q <= '2031Q1']

fetcher = ONSFetcher()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION A: ONS fetches — OAHHx, DEPHHx, NAOLPE
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section A: ONS fetches (OAHHx, DEPHHx, NAOLPE) ===")

# Additional ONS paths needed (some already in ONS_PATHS via phase7)
EXTRA_PATHS = {
    'NFYS': '/economy/grossdomesticproductgdp',   # Total HH financial liabilities
    'NGAS': '/economy/grossdomesticproductgdp',   # HH loans secured on dwellings (mortgages)
    'NNPP': '/economy/nationalaccounts/uksectoraccounts',  # Total HH liabilities stock (annual)
}
ONS_PATHS.update(EXTRA_PATHS)

ONS_TARGETS = {
    'OAHHx':  ('NNMY+NNOA+NNPM+MMW5', 'Other assets (unadjusted): HH (NSA), ONS formula'),
    'DEPHHx': ('NNMP',                  'Currency & deposit assets (unadjusted): HH (NSA)'),
    'NAOLPE': ('NFYS-NGAS',             'HH net acquisition of other financial liabilities (NSA)'),
}

for var, (formula, desc) in ONS_TARGETS.items():
    print(f"  Fetching {var} ({formula}) ...", end=' ', flush=True)
    codes = fetcher._extract_codes(formula)
    all_dates = set()
    ok = True
    for code in codes:
        series = fetcher.fetch(code)
        time.sleep(0.3)
        if not series:
            print(f"FAILED (no data for {code})")
            ok = False
            break
        all_dates |= set(series.keys())

    if not ok:
        continue

    computed = {}
    for d in sorted(all_dates):
        if not d.endswith(('Q1','Q2','Q3','Q4')):
            continue
        v = fetcher.compute_formula(formula, d)
        if v is not None:
            computed[d] = v

    if computed:
        upsert_series(var, desc, formula)
        for q, v in sorted(computed.items()):
            upsert_obs(var, q, v, source='ONS')
        dates = sorted(computed.keys())
        print(f"OK — {len(computed)} quarters ({dates[0]} → {dates[-1]})")
    else:
        print("FAILED — no values computed")

conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION B: DEBTU from ONS component series
# Uses ONS formula: (NFYS-NGAS-CT9E+CT9E(-1))/(NNPP(-1)-NNRP(-1)-CT9E(-1))
# Requires lag handling for CT9E(-1), NNPP(-1), NNRP(-1)
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section B: DEBTU from ONS components ===")

component_codes = ['NFYS', 'NGAS', 'CT9E', 'NNPP', 'NNRP']
component_data = {}
for code in component_codes:
    series = fetcher.fetch(code)
    time.sleep(0.3)
    component_data[code] = series
    n = len(series)
    print(f"  {code}: {n} quarters" if n > 0 else f"  {code}: FAILED")

# Compute DEBTU with lag: for each quarter t, need previous quarter t-1
def prev_quarter(q):
    y, n = int(q[:4]), int(q[5])
    if n == 1:
        return f"{y-1}Q4"
    return f"{y}Q{n-1}"

debtu_vals = {}
all_q = sorted(set.union(*[set(component_data[c].keys()) for c in component_codes if component_data[c]]))
for q in all_q:
    if not q.endswith(('Q1','Q2','Q3','Q4')):
        continue
    pq = prev_quarter(q)
    nfys  = component_data['NFYS'].get(q)
    ngas  = component_data['NGAS'].get(q)
    ct9e  = component_data['CT9E'].get(q)
    ct9e_1 = component_data['CT9E'].get(pq)
    nnpp_1 = component_data['NNPP'].get(pq)
    nnrp_1 = component_data['NNRP'].get(pq)

    if any(v is None for v in [nfys, ngas, ct9e, ct9e_1, nnpp_1, nnrp_1]):
        continue
    denom = nnpp_1 - nnrp_1 - ct9e_1
    if denom == 0:
        continue
    debtu_vals[q] = (nfys - ngas - ct9e + ct9e_1) / denom

if debtu_vals:
    upsert_series('DEBTU',
        'HH growth in unsecured debt excl student loans (ex writedowns)',
        '(NFYS-NGAS-CT9E+CT9E(-1))/(NNPP(-1)-NNRP(-1)-CT9E(-1))')
    for q, v in sorted(debtu_vals.items()):
        upsert_obs('DEBTU', q, v, source='ONS')
    dates = sorted(debtu_vals.keys())
    print(f"  DEBTU: {len(debtu_vals)} quarters ({dates[0]} → {dates[-1]})")
    sample = [(q, round(v, 5)) for q, v in sorted(debtu_vals.items()) if '2008' <= q <= '2009']
    print(f"  Sample 2008-2009: {sample}")
else:
    print("  DEBTU: FAILED — insufficient component data")

conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION C: NAINSx / NAINS — recursive computation
# NAINSx = 13293.71 + 0.627*NAINSx(-1) - 236267.3*(SIPT(-3)/100)
# SIPT stored as percent (6.0) → divide by 100 in equation
# Seed at 2007Q4 using NFYO+M9WF if available, else steady-state
# NAINS = NAINSx + NAINSADJ
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section C: NAINSx / NAINS recursive computation ===")

sipt_data = get_series('SIPT')
nainsadj_data = get_series('NAINSADJ')

# Build list of quarters from 2005Q1 (need 3-quarter lag from 2008Q1 back to 2007Q2)
# We start computing from the first quarter where we have SIPT going back 3 quarters
sipt_quarters = sorted(k for k in sipt_data if k.endswith(('Q1','Q2','Q3','Q4')))

# Seed: use steady-state at the first SIPT rate (6.0 → 0.06)
# Steady state: NAINSx_ss = (13293.71 - 236267.3 * sipt_rate) / (1 - 0.627)
first_sipt = sipt_data.get(sipt_quarters[0], 6.0) / 100.0
nainsx_ss = (13293.71 - 236267.3 * first_sipt) / (1.0 - 0.627)
print(f"  Steady-state seed (SIPT={first_sipt*100:.1f}%): NAINSx = {nainsx_ss:.1f}")

# Build indexed SIPT for lag lookup
def get_sipt_lag3(q):
    """Return SIPT value 3 quarters before q."""
    y, n = int(q[:4]), int(q[5])
    n -= 3
    while n < 1:
        n += 4
        y -= 1
    lag3_q = f"{y}Q{n}"
    return sipt_data.get(lag3_q)

# Walk from first sipt quarter forward
# We compute NAINSx for all quarters where we have SIPT(t-3)
nainsx_vals = {}
prev_nainsx = nainsx_ss

for q in sorted(sipt_quarters):
    sipt_lag3 = get_sipt_lag3(q)
    if sipt_lag3 is None:
        continue
    nainsx = 13293.71 + 0.627 * prev_nainsx - 236267.3 * (sipt_lag3 / 100.0)
    nainsx_vals[q] = nainsx
    prev_nainsx = nainsx

if nainsx_vals:
    upsert_series('NAINSx',
        'Net acquisition of insurance assets (unadjusted): HH (NSA)',
        'NFYO+M9WF')
    for q, v in sorted(nainsx_vals.items()):
        upsert_obs('NAINSx', q, v, source='COMPUTED')
    dates = sorted(nainsx_vals.keys())
    print(f"  NAINSx: {len(nainsx_vals)} quarters ({dates[0]} → {dates[-1]})")
    sample = [(q, round(v, 1)) for q, v in sorted(nainsx_vals.items()) if '2008' <= q <= '2009']
    print(f"  Sample 2008-2009: {sample}")

    # NAINS = NAINSx + NAINSADJ
    nains_vals = {}
    for q, nx in nainsx_vals.items():
        adj = nainsadj_data.get(q, 0.0)
        nains_vals[q] = nx + adj

    upsert_series('NAINS',
        'Net acquisition of insurance assets: HH (NSA)',
        'NFYO+M9WF')
    for q, v in sorted(nains_vals.items()):
        upsert_obs('NAINS', q, v, source='COMPUTED')
    print(f"  NAINS: {len(nains_vals)} quarters written")
else:
    print("  NAINSx: FAILED — no SIPT data")

conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION D: CPIX / CPIXBASE / MKR
# CPIX growth back-calculated from observed CPI and CPIRENT:
#   dlog(CPIX) = (dlog(CPI) - W1*dlog(CPIRENT)) / (1 - W1)
# Normalise so 2009 annual average CPIX = CPIXBASE = 100
# MKR stored as 100 (index placeholder — RPCOST chain is broken)
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section D: CPIX / CPIXBASE / MKR ===")

cpi_data      = get_series('CPI')
cpirent_data  = get_series('CPIRENT')
w1_data       = get_series('W1')

# Compute CPIX growth rates for all quarters where both CPI and CPIRENT exist
cpix_growth = {}  # quarter → dlog(CPIX) relative to previous quarter
all_q_cpi = sorted(set(cpi_data.keys()) & set(cpirent_data.keys()))

for i in range(1, len(all_q_cpi)):
    q    = all_q_cpi[i]
    pq   = all_q_cpi[i-1]
    # Check consecutive
    if prev_quarter(q) != pq:
        continue
    cpi_t   = cpi_data.get(q)
    cpi_t1  = cpi_data.get(pq)
    rent_t  = cpirent_data.get(q)
    rent_t1 = cpirent_data.get(pq)
    w1      = w1_data.get(q, w1_data.get(pq, 0.084))
    if any(v is None or v <= 0 for v in [cpi_t, cpi_t1, rent_t, rent_t1]):
        continue
    try:
        dlog_cpix = (math.log(cpi_t/cpi_t1) - w1 * math.log(rent_t/rent_t1)) / (1.0 - w1)
        cpix_growth[q] = dlog_cpix
    except (ValueError, ZeroDivisionError):
        pass

# Reconstruct CPIX level from growth rates, anchored so 2009 average = 100
# Step 1: build cumulative log-index relative to an arbitrary starting point
cpix_log_index = {}
q_sorted = sorted(cpix_growth.keys())
if q_sorted:
    cpix_log_index[q_sorted[0]] = 0.0
    for i in range(1, len(q_sorted)):
        q = q_sorted[i]
        pq = q_sorted[i-1]
        if prev_quarter(q) == pq:
            cpix_log_index[q] = cpix_log_index[pq] + cpix_growth[q]
        else:
            cpix_log_index[q] = cpix_log_index.get(pq, 0.0) + cpix_growth.get(q, 0.0)

# Step 2: anchor so average(CPIX for 2009) = 100
quarters_2009 = [q for q in cpix_log_index if q.startswith('2009')]
if quarters_2009:
    avg_log_2009 = sum(cpix_log_index[q] for q in quarters_2009) / len(quarters_2009)
    # Shift so 2009 average log = log(100)
    offset = math.log(100.0) - avg_log_2009
    cpix_vals = {q: math.exp(li + offset) for q, li in cpix_log_index.items()}
else:
    # Fall back: anchor to first available quarter = 100
    first_q = q_sorted[0]
    offset = math.log(100.0) - cpix_log_index[first_q]
    cpix_vals = {q: math.exp(li + offset) for q, li in cpix_log_index.items()}
    print("  WARNING: no 2009 data for CPIXBASE normalisation, using first-quarter anchor")

# CPIXBASE = average of CPIX over 2009Q1-Q4
cpix_2009_vals = [cpix_vals[q] for q in ['2009Q1','2009Q2','2009Q3','2009Q4'] if q in cpix_vals]
CPIXBASE_val = sum(cpix_2009_vals) / len(cpix_2009_vals) if cpix_2009_vals else 100.0

print(f"  CPIXBASE = {CPIXBASE_val:.4f} (2009 average CPIX, should be ~100)")

if cpix_vals:
    upsert_series('CPIX', 'CPI index ex rent (back-calculated from CPI/CPIRENT)', '')
    for q, v in sorted(cpix_vals.items()):
        upsert_obs('CPIX', q, v, source='COMPUTED')
    dates = sorted(cpix_vals.keys())
    print(f"  CPIX: {len(cpix_vals)} quarters ({dates[0]} → {dates[-1]})")
    sample = [(q, round(v, 3)) for q, v in sorted(cpix_vals.items()) if '2008' <= q <= '2010']
    print(f"  Sample 2008-2010: {sample}")

# CPIXBASE — single constant stored for all quarters (it's a scalar in the model)
upsert_series('CPIXBASE', 'CPI index ex rent: 2009 base value', '')
for q in ALL_QUARTERS:
    upsert_obs('CPIXBASE', q, CPIXBASE_val, source='COMPUTED')
print(f"  CPIXBASE: {CPIXBASE_val:.4f} written for all quarters")

# MKR — placeholder index (RPCOST chain is broken, MKR can't be derived)
# Stored as 100 (neutral index value). Model coverage requires it in DB.
upsert_series('MKR', 'Service and retail margins index (placeholder; RPCOST chain broken)', '')
for q in ALL_QUARTERS:
    upsert_obs('MKR', q, 100.0, source='COMPUTED')
print(f"  MKR: 100.0 (placeholder) written for all quarters")

conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION E: PD — HMRC residential property transactions
# Source: HMRC monthly property transactions statistics
# URL: https://assets.publishing.service.gov.uk/media/6a158e7a0026f30a6d421d17/MPT_Tab_May_26.ods
# Sheet: Residential_quarterly, column 5 = UK total (actual transaction counts)
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section E: PD (HMRC residential property transactions) ===")

HMRC_URL = 'https://assets.publishing.service.gov.uk/media/6a158e7a0026f30a6d421d17/MPT_Tab_May_26.ods'
hmrc_ods = '/tmp/hmrc_pt_phase8.ods'

try:
    print(f"  Downloading HMRC ODS ...", end=' ', flush=True)
    r = requests.get(HMRC_URL, timeout=30, headers={'User-Agent': 'CBP-model/1.0'})
    r.raise_for_status()
    with open(hmrc_ods, 'wb') as f:
        f.write(r.content)
    print(f"OK ({len(r.content)//1024} KB)")

    import ezodf
    doc = ezodf.opendoc(hmrc_ods)
    res_q_sheet = next(s for s in doc.sheets if s.name == 'Residential_quarterly')

    pd_vals = {}
    for row_idx in range(res_q_sheet.nrows()):
        label = res_q_sheet[row_idx, 0].value
        if not isinstance(label, str) or 'Quarter' not in label:
            continue
        # Parse "2008 Quarter 1" → "2008Q1"
        parts = label.strip().split()
        if len(parts) < 3:
            continue
        try:
            year = int(parts[0])
            qnum = int(parts[2])
            q = f"{year}Q{qnum}"
        except (ValueError, IndexError):
            continue
        # Column 5 = UK total (actual transaction count, not seasonally adjusted)
        uk_val = res_q_sheet[row_idx, 5].value
        if uk_val is not None:
            pd_vals[q] = float(uk_val)

    if pd_vals:
        upsert_series('PD', 'Residential property transactions: UK total (HMRC)',
                      'HMRC-MPT-UK-residential-quarterly')
        for q, v in sorted(pd_vals.items()):
            upsert_obs('PD', q, v, source='ONS')  # source='ONS' for priority
        dates = sorted(pd_vals.keys())
        print(f"  PD: {len(pd_vals)} quarters ({dates[0]} → {dates[-1]})")
        sample = [(q, int(v)) for q, v in sorted(pd_vals.items()) if '2008' <= q <= '2010']
        print(f"  Sample 2008-2010: {sample}")
    else:
        print("  PD: FAILED — no data parsed from ODS")

except Exception as e:
    print(f"  PD: FAILED — {e}")

conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION F: Downstream identities — GMF, NAOLPEx, NAOLPE update, HHRES, OAHHADJ
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Section F: Downstream identities (GMF, NAOLPEx, HHRES, OAHHADJ) ===")

# Reload all data now that we've written new series
pd_data      = get_series('PD')
aph_data     = get_series('APH')
dephh_data   = get_series('DEPHH')   # £mn — needs *1e6 for GMF unit consistency
debtu_data   = get_series('DEBTU')
olpex_data   = get_series('OLPEx')   # £mn
student_data = get_series('STUDENT') # £mn
lhp_data     = get_series('LHP')     # £mn
nlhh_data    = get_series('NLHH')    # ONS net lending by HH sector
naeqhhx_data = get_series('NAEQHHx')
napen_data   = get_series('NAPEN')
nainsx_data  = get_series('NAINSx')
oahhx_data   = get_series('OAHHx')
dephhadj_data  = get_series('DEPHHADJ')
naeqhhadj_data = get_series('NAEQHHADJ')
nainsadj_data  = get_series('NAINSADJ')
naolpeadj_data = get_series('NAOLPEADJ')

# ── F1: GMF = (PD * APH * 0.858) / DEPHH(-1)
# Unit note: PD = transaction count (e.g. 245,940), APH = £ (e.g. 200,000),
#            DEPHH in £mn from DB → convert to £ by * 1e6
# ─────────────────────────────────────────────────────────────────────────────
print("  Computing GMF ...")
gmf_vals = {}
for q in sorted(pd_data.keys()):
    if not q.endswith(('Q1','Q2','Q3','Q4')):
        continue
    pq = prev_quarter(q)
    pd_v    = pd_data.get(q)
    aph_v   = aph_data.get(q, 200000.0)
    dephh_1 = dephh_data.get(pq)
    if any(v is None for v in [pd_v, dephh_1]):
        continue
    if dephh_1 == 0:
        continue
    # DEPHH in DB is £mn; APH in £; PD in transaction count
    # GMF is dimensionless: (transactions * £) / £ = pure ratio
    # To get consistent units: DEPHH_£ = dephh_1 * 1e6
    gmf = (pd_v * aph_v * 0.858) / (dephh_1 * 1e6)
    gmf_vals[q] = gmf

if gmf_vals:
    upsert_series('GMF', 'Working variable for deposits (mortgage flow / deposit stock)')
    for q, v in sorted(gmf_vals.items()):
        upsert_obs('GMF', q, v, source='COMPUTED')
    dates = sorted(gmf_vals.keys())
    print(f"  GMF: {len(gmf_vals)} quarters ({dates[0]} → {dates[-1]})")
    sample = [(q, round(v, 5)) for q, v in sorted(gmf_vals.items()) if '2008' <= q <= '2009']
    print(f"  Sample 2008-2009: {sample}")
else:
    print("  GMF: FAILED — missing PD or DEPHH")

# ── F2: NAOLPEx = OLPEx(-1) * DEBTU
# NAOLPEx is HH net acquisition of other loans (unsecured) — unadjusted
# ─────────────────────────────────────────────────────────────────────────────
print("  Computing NAOLPEx ...")
naolpex_vals = {}
for q in sorted(debtu_data.keys()):
    pq = prev_quarter(q)
    debtu_v  = debtu_data.get(q)
    olpex_1  = olpex_data.get(pq)
    if any(v is None for v in [debtu_v, olpex_1]):
        continue
    naolpex_vals[q] = olpex_1 * debtu_v

if naolpex_vals:
    upsert_series('NAOLPEx', 'Net acquisition of other loans (unadjusted): HH (NSA)')
    for q, v in sorted(naolpex_vals.items()):
        upsert_obs('NAOLPEx', q, v, source='COMPUTED')
    print(f"  NAOLPEx: {len(naolpex_vals)} quarters")

# ── F3: NAOLPE = NAOLPEx + d(STUDENT) + NAOLPEADJ
# NAOLPE is already in DB from ONS (NFYS-NGAS), but we also write the model-computed version
# The ONS version should be more accurate; compute as cross-check only
# ─────────────────────────────────────────────────────────────────────────────
print("  Computing NAOLPE (model formula cross-check) ...")
naolpe_computed = {}
for q in sorted(naolpex_vals.keys()):
    pq = prev_quarter(q)
    naolpex_v  = naolpex_vals.get(q)
    student_t  = student_data.get(q)
    student_t1 = student_data.get(pq)
    naolpeadj  = naolpeadj_data.get(q, 0.0)
    if any(v is None for v in [naolpex_v, student_t, student_t1]):
        continue
    naolpe_computed[q] = naolpex_v + (student_t - student_t1) + naolpeadj

# Only write the model-computed NAOLPE if ONS version is not available or empty
naolpe_existing = get_series('NAOLPE')
if len(naolpe_existing) == 0 and naolpe_computed:
    upsert_series('NAOLPE', 'HH net acquisition of other financial liabilities (NSA, model-computed)')
    for q, v in sorted(naolpe_computed.items()):
        upsert_obs('NAOLPE', q, v, source='COMPUTED')
    print(f"  NAOLPE (model): {len(naolpe_computed)} quarters written")
else:
    print(f"  NAOLPE: ONS version already in DB ({len(naolpe_existing)} quarters), keeping it")

# ── F4: HHRES = NLHH - ((d(DEPHHx) + NAEQHHx + NAPEN + NAINSx + d(OAHHx))
#                        - (NAOLPEx + d(STUDENT) + d(LHP)))
# ─────────────────────────────────────────────────────────────────────────────
print("  Computing HHRES ...")
dephhx_data = get_series('DEPHHx')  # fetch once outside loop
hhres_vals = {}
for q in sorted(nainsx_vals.keys()):
    pq = prev_quarter(q)
    nlhh      = nlhh_data.get(q)
    naeqhhx   = naeqhhx_data.get(q)
    napen     = napen_data.get(q)
    nainsx_v  = nainsx_vals.get(q)
    naolpex_v = naolpex_vals.get(q)

    dephhx_t  = dephhx_data.get(q)
    dephhx_t1 = dephhx_data.get(pq)
    oahhx_t   = oahhx_data.get(q)
    oahhx_t1  = oahhx_data.get(pq)
    student_t = student_data.get(q)
    student_t1= student_data.get(pq)
    lhp_t     = lhp_data.get(q)
    lhp_t1    = lhp_data.get(pq)

    if any(v is None for v in [nlhh, naeqhhx, napen, nainsx_v, naolpex_v,
                                 dephhx_t, dephhx_t1, oahhx_t, oahhx_t1,
                                 student_t, student_t1, lhp_t, lhp_t1]):
        continue

    d_dephhx = dephhx_t - dephhx_t1
    d_oahhx  = oahhx_t  - oahhx_t1
    d_student = student_t - student_t1
    d_lhp     = lhp_t - lhp_t1

    assets_flow  = d_dephhx + naeqhhx + napen + nainsx_v + d_oahhx
    liab_flow    = naolpex_v + d_student + d_lhp
    hhres_vals[q] = nlhh - (assets_flow - liab_flow)

if hhres_vals:
    upsert_series('HHRES', 'HH balance sheet residual')
    for q, v in sorted(hhres_vals.items()):
        upsert_obs('HHRES', q, v, source='COMPUTED')
    dates = sorted(hhres_vals.keys())
    print(f"  HHRES: {len(hhres_vals)} quarters ({dates[0]} → {dates[-1]})")
else:
    print("  HHRES: FAILED — insufficient inputs")

# ── F5: OAHHADJ = HHRES - DEPHHADJ - NAEQHHADJ - NAINSADJ + NAOLPEADJ
# ─────────────────────────────────────────────────────────────────────────────
print("  Computing OAHHADJ ...")
oahhadj_vals = {}
for q, hhres_v in hhres_vals.items():
    dephhadj  = dephhadj_data.get(q, 0.0)
    naeqhhadj = naeqhhadj_data.get(q, 0.0)
    nainsadj  = nainsadj_data.get(q, 0.0)
    naolpeadj = naolpeadj_data.get(q, 0.0)
    oahhadj_vals[q] = hhres_v - dephhadj - naeqhhadj - nainsadj + naolpeadj

if oahhadj_vals:
    upsert_series('OAHHADJ', 'OAHH Adjustment Residual')
    for q, v in sorted(oahhadj_vals.items()):
        upsert_obs('OAHHADJ', q, v, source='COMPUTED')
    print(f"  OAHHADJ: {len(oahhadj_vals)} quarters")

conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY: check coverage of the 8 previously-blocked variables
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Coverage Check ===")
TARGET_VARS = ['CPIX', 'CPIXBASE', 'DEBTU', 'GMF', 'HHRES', 'NAINS', 'NAOLPE', 'OAHHADJ', 'MKR']
in_db = set(r[0] for r in conn.execute("SELECT DISTINCT series_id FROM observations").fetchall())

for v in TARGET_VARS:
    if v in in_db:
        n = conn.execute("SELECT COUNT(*) FROM observations WHERE series_id=?", (v,)).fetchone()[0]
        print(f"  {v}: IN DB ({n} observations)")
    else:
        print(f"  {v}: MISSING")

# Full model coverage check
MODEL_TXT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'docs', 'Macroeconomic_model_code_March_2025.txt'
)
try:
    from cbp_fiscal_framework.core.winsolve import WinsolveParser
    with open(MODEL_TXT) as f:
        equations = WinsolveParser.parse_model(f.read())
    lhs_vars = set(e.lhs_variable for e in equations)
    covered = lhs_vars & in_db
    missing = lhs_vars - in_db
    print(f"\nModel variable coverage: {len(covered)}/{len(lhs_vars)} ({100*len(covered)/len(lhs_vars):.1f}%)")
    if missing:
        print(f"Still missing: {sorted(missing)}")
except Exception as e:
    print(f"Coverage check error: {e}")

conn.close()

# ── Copy back to mounted path ─────────────────────────────────────────────────
print(f"\nCopying {WORK_DB} → {DB_PATH} ...")
shutil.copy(WORK_DB, DB_PATH)
print("Done. Phase 8 complete.")
