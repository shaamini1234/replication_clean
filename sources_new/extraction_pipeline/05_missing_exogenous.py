"""
Phase 5 — Load missing exogenous variables into timeseries.db.

Three categories:
  A) ONS compound-formula variables (~39 variables)
  B) Time-varying statutory constants (TCPRO, TPBRZ, etc.)
  C) Calibration-factor defaults (ADJW=1, LAWADJ=1, CGWADJ=1, …)
  D) GAD1/2/3 population by age from ONS

Run from repo root:
    python shaamini_tests/phase5_missing_exogenous.py
"""

import os, sys, sqlite3, time, requests, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timeseries.db")
BASE_URL = "https://www.ons.gov.uk"
PUB_DATE = "2026-03"

from cbp_fiscal_framework.inputs.ons_fetcher import ONSFetcher, ONS_PATHS

fetcher = ONSFetcher()

conn = sqlite3.connect(DB_PATH)

def upsert_series(sid, desc=""):
    conn.execute(
        "INSERT INTO series(id,label) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label",
        (sid, desc)
    )

def upsert_obs(sid, quarter, value, source="ONS", pub_date=PUB_DATE, data_type="OUTTURN"):
    conn.execute(
        """INSERT INTO observations(series_id,source,publication_date,quarter,value,data_type)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(series_id,source,publication_date,quarter)
           DO UPDATE SET value=excluded.value""",
        (sid, source, pub_date, quarter, value, data_type)
    )

# ─────────────────────────────────────────────────────────────────────────────
# A) ONS compound-formula variables
# ─────────────────────────────────────────────────────────────────────────────
PHASE5_ONS = {
    "INHT":     "ACCH+LSON",
    "NNSCTP":   "CPRN-DBJY",
    "LAEPS":    "C625",
    "OHT":      "NSFA+CQTC+NRQB+IY9O",
    "OPT":      "NZFS+NZFV+LITR+NSEZ+CUDB+LITK+DFT5-L8UA+CT9U+CRSN",
    "TXALC":    "ACDF+ACDG+ACDH+ACDI",
    "VEDCO":    "GTAX-CDDZ",
    "INCTAC":   "CYNX+RUTC+DKHE+DBKE+KIY5",
    "FCACA":    "DKHH+ZYBE",
    "TROD":     "FJUO-FJCK-MUV5-MUV6+FKKM",
    "FISIMROW": "IV8F+IV8E",
    "EUOT":     "FJWE+FJWG",
    "PIH":      "100*(L62T/L636)",
    "HRRPW":    "KYHM",
    "PRP":      "KYHL",
    "LAPR":     "QWRZ-NMKK",
    "CGLIQ":    "BKSM+BKSN",
    "LALIQ":    "BKSO+BKQG",
    "FLEASGG":  "F8YF+F8YH",
    "OFLPS":    "NKIF+NPVQ-NIJI-ACUA",
    "PSFA":     "NKFB+NPUP",
    "SWISSCAP": "KW69",
    "NDIV":     "NETZ/NLBU",
    "CGCGLA":   "QYJR",
    "KCGLA":    "NMGR+NMGT",
    "KCGPC":    "-ANND-NMGR-NMGT",
    "CTC":      "-MDYL",
    "NPISHTC":  "-CFGW",
    "CONACC":   "-GCSW-GCMR",
    "ILGAC":    "-NMQZ",
    "INSURE":   "FKNN+FLVY",
    "PCAC":     "ANVQ+JXJ4",
    "PCNDIV":   "GVHG-JW29",
    "PCRENT":   "ANCW",
    "NPAA":     "FHJL-FLWT",
    "LCGPR":    "ANRH-HEUC",
    "CGMISP":   "ANRS-ABIF",
    "ERCG":     "(NMAI*1000/C9K9)*(4/52)",
    "ERLA":     "(NMJF*1000/C9KA)*(4/52)",
}

print("=== Part A: ONS compound-formula variables ===")
total_a = 0
for var, formula in PHASE5_ONS.items():
    upsert_series(var, f"Phase 5 ONS: {formula}")
    codes = re.findall(r'[A-Z][A-Z0-9]{2,6}', formula)
    # collect all dates across component series
    all_dates = set()
    series_cache = {}
    ok = True
    for code in codes:
        if code not in ONS_PATHS:
            print(f"  {var}: SKIP — no path for {code}")
            ok = False
            break
        data = fetcher.fetch(code)
        if not data:
            print(f"  {var}: SKIP — no data for {code}")
            ok = False
            break
        series_cache[code] = data
        all_dates |= set(data.keys())
    if not ok:
        continue

    n = 0
    for q in sorted(all_dates):
        val = fetcher.compute_formula(formula, q)
        if val is not None:
            upsert_obs(var, q, val)
            n += 1
    print(f"  {var}: {n} quarters loaded")
    total_a += n

conn.commit()
print(f"Part A total: {total_a} observations\n")

# ─────────────────────────────────────────────────────────────────────────────
# B) Time-varying statutory tax rates
# ─────────────────────────────────────────────────────────────────────────────
print("=== Part B: Time-varying statutory constants ===")

# Corporation tax rate by quarter (UK main rate, from April = Q2 change)
CORP_TAX = {
    # QN: rate %
    "2008Q1": 30, "2008Q2": 28, "2008Q3": 28, "2008Q4": 28,
    "2009Q1": 28, "2009Q2": 28, "2009Q3": 28, "2009Q4": 28,
    "2010Q1": 28, "2010Q2": 27, "2010Q3": 27, "2010Q4": 27,
    "2011Q1": 27, "2011Q2": 26, "2011Q3": 26, "2011Q4": 26,
    "2012Q1": 26, "2012Q2": 24, "2012Q3": 24, "2012Q4": 24,
    "2013Q1": 24, "2013Q2": 23, "2013Q3": 23, "2013Q4": 23,
    "2014Q1": 23, "2014Q2": 21, "2014Q3": 21, "2014Q4": 21,
    "2015Q1": 21, "2015Q2": 20, "2015Q3": 20, "2015Q4": 20,
    "2016Q1": 20, "2016Q2": 20, "2016Q3": 20, "2016Q4": 20,
    "2017Q1": 20, "2017Q2": 19, "2017Q3": 19, "2017Q4": 19,
}
# 19% from 2017Q2 through 2022Q4; 25% from 2023Q2
for y in range(2018, 2023):
    for q in range(1, 5):
        CORP_TAX[f"{y}Q{q}"] = 19
CORP_TAX["2023Q1"] = 19
for y in range(2023, 2032):
    for q in range(1, 5):
        if f"{y}Q{q}" not in CORP_TAX:
            CORP_TAX[f"{y}Q{q}"] = 25
CORP_TAX["2023Q2"] = 25

upsert_series("TCPRO", "Corporation tax rate (%)")
for q, rate in CORP_TAX.items():
    upsert_obs("TCPRO", q, float(rate), source="CONSTANT")
print(f"  TCPRO: {len(CORP_TAX)} quarters")

# Basic rate of income tax: 22% pre-2008Q2, 20% from 2008Q2
upsert_series("TPBRZ", "Basic rate of income tax (%)")
for y in range(2008, 2032):
    for q in range(1, 5):
        qt = f"{y}Q{q}"
        rate = 22.0 if (y == 2008 and q == 1) else 20.0
        upsert_obs("TPBRZ", qt, rate, source="CONSTANT")
print(f"  TPBRZ: loaded")

# Insurance premium tax: 6% until 2015Q3, 9.5% 2015Q4, 10% 2017Q2, 12% 2017Q4
IPT = {}
for y in range(2008, 2016):
    for q in range(1, 5):
        IPT[f"{y}Q{q}"] = 6.0
IPT["2015Q4"] = 9.5
for q in range(1, 5):
    IPT[f"2016Q{q}"] = 9.5
IPT["2017Q1"] = 9.5; IPT["2017Q2"] = 10.0; IPT["2017Q3"] = 10.0; IPT["2017Q4"] = 12.0
for y in range(2018, 2032):
    for q in range(1, 5):
        IPT[f"{y}Q{q}"] = 12.0
upsert_series("SIPT", "Standard rate of insurance premium tax (%)")
for q, v in IPT.items():
    upsert_obs("SIPT", q, v, source="CONSTANT")
print(f"  SIPT: loaded")

conn.commit()
print()

# ─────────────────────────────────────────────────────────────────────────────
# C) Calibration defaults — constant for entire period
# ─────────────────────────────────────────────────────────────────────────────
print("=== Part C: Calibration defaults (constant series) ===")

ALL_QUARTERS = [f"{y}Q{q}" for y in range(2008, 2032) for q in range(1, 5)]
# Trim to state range
ALL_QUARTERS = [q for q in ALL_QUARTERS if q <= "2031Q1"]

CALIBRATION = {
    "ADJW":   (1.0,    "Wage bill adjustment factor (neutral default)"),
    "CGWADJ": (1.0,    "CG wage adjustment factor (neutral default)"),
    "LAWADJ": (1.0,    "LA wage adjustment factor (neutral default)"),
    "DELTA":  (2.2,    "Capital depreciation rate (%)"),
    "FP":     (100.0,  "First-year allowance rate for plant (%)"),
    "SP":     (18.0,   "Main rate plant writing-down allowance (%)"),
    "SV":     (25.0,   "Vehicle writing-down allowance (%)"),
    "SIB":    (3.0,    "Industrial buildings annual allowance (%)"),
    "IIB":    (0.0,    "Initial-year industrial buildings allowance (%)"),
    "DEBTW":  (0.5,    "Weight on debt finance in cost of capital"),
    "ROCB":   (4.0,    "Overseas central bank rate (%)"),
    "ROLT":   (3.5,    "10-year bond rate major economies (%)"),
    "DISCO":  (1.0,    "Discount factor"),
    "RULC":   (100.0,  "Road lorry user charge index"),
    "SPECX":  (1.0,    "Trend specialisation in world trade"),
    "WPG":    (100.0,  "World price of goods index"),
    "WEQPR":  (100.0,  "World equity price index (neutral default)"),
    "PROV":   (0.0,    "Allowance for tax litigation losses"),
    "CIL":    (0.0,    "Community Infrastructure Levy"),
    "CUST":   (0.0,    "Customs duties"),
    "ENVLEVY":(0.0,    "Environmental levies"),
    "EUETS":  (0.0,    "EU Emissions Trading Scheme receipts"),
    "MAJGDP": (100.0,  "Major economies GDP index (neutral default)"),
    "PEHC":   (50.0,   "Private enterprise housing completions ('000s, approx)"),
    "ROCB":   (4.0,    "Overseas central bank rate"),
    "ROLT":   (3.5,    "10y bond rate major economies"),
    "APH":    (200000.0, "Average house price (£, approx)"),
    "HH":     (27000.0,  "Number of households ('000s, approx)"),
    "GGGDRES":(0.0,    "Other changes in GGGD"),
    "PSNDRES":(0.0,    "Other changes in PSND"),
    "CGACRES":(0.0,    "CG accruals adjustment residual"),
    "CCLACA": (0.0,    "Climate change levy accruals adj."),
    "DEPHHADJ":(0.0,   "DEPHH adjustment residual"),
    "FSMADJ": (0.0,    "FISIM adjustment in HH disposable income"),
    "NAEQHHADJ":(0.0,  "NAEQHH adjustment residual"),
    "NAINSADJ":(0.0,   "NAINS adjustment residual"),
    "NAOLPEADJ":(0.0,  "NAOLPE adjustment residual"),
    "MKTIG":  (500.0,  "Stock of index-linked gilts (market value, £bn, approx)"),
    "CGGILTS":(1200.0, "Stock of CG conventional gilts (£bn, approx)"),
    "ASSETSA":(0.0,    "Public sector fixed asset sales"),
    "KGLAPC": (0.0,    "PC capital grants from local authorities"),
    "TCPRO":  (None,   ""),   # already loaded in Part B
}

n_c = 0
for var, (val, desc) in CALIBRATION.items():
    if val is None:
        continue
    upsert_series(var, desc)
    for q in ALL_QUARTERS:
        upsert_obs(var, q, val, source="CONSTANT")
    n_c += 1

conn.commit()
print(f"  Loaded {n_c} constant series ({len(ALL_QUARTERS)} quarters each)")
print()

# ─────────────────────────────────────────────────────────────────────────────
# D) GAD1/2/3 — ONS population by age band
# ─────────────────────────────────────────────────────────────────────────────
print("=== Part D: GAD1/2/3 population by age band ===")

# Try ONS timeseries codes for quarterly population by age
# MGSL = total UK population; MGXS/MGXU/MGXW are mid-year estimates (annual)
# For quarterly, try DYXY (0-15), BBFE (16-64), DYXZ (65+) etc.
POP_CANDIDATES = {
    "GAD1": ["DYXY", "MGXT", "MGXS"],    # children 0-15
    "GAD2": ["MGXU", "BBFE", "MGXV"],    # working age 16-64
    "GAD3": ["MGXW", "DYXZ", "MGXX"],    # 65+
}
POP_DESCS = {
    "GAD1": "ONS population projection: children (<16) ('000s)",
    "GAD2": "ONS population projection: working-age ('000s)",
    "GAD3": "ONS population projection: state pension age ('000s)",
}

session = requests.Session()
session.headers.update({"User-Agent": "CBP-model/1.0"})

POP_CATEGORIES = [
    "/peoplepopulationandcommunity/populationandmigration/populationestimates",
    "/economy/grossdomesticproductgdp",
    "/peoplepopulationandcommunity/populationandmigration/populationprojections",
]

def try_fetch_ons(code):
    """Try to fetch ONS series by code, trying multiple categories."""
    for cat in POP_CATEGORIES:
        url = f"{BASE_URL}{cat}/timeseries/{code.lower()}/data"
        try:
            r = session.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                quarters = data.get("quarters", [])
                if quarters:
                    return {q["date"].replace(" ", "").replace("Q", "Q"): float(q["value"].replace(",", ""))
                            for q in quarters if q.get("value", "").strip() not in ("", ".")}
        except Exception:
            pass
        time.sleep(0.1)
    return {}

gad_loaded = {}
for gad_var, candidates in POP_CANDIDATES.items():
    upsert_series(gad_var, POP_DESCS[gad_var])
    loaded = False
    for code in candidates:
        data = try_fetch_ons(code)
        if data:
            n = 0
            for q, v in data.items():
                if "Q" in q:
                    upsert_obs(gad_var, q, v)
                    n += 1
            if n > 0:
                print(f"  {gad_var}: {n} quarters from {code}")
                gad_loaded[gad_var] = n
                loaded = True
                break
    if not loaded:
        # Fallback: load approximate constant values
        approx = {"GAD1": 11800.0, "GAD2": 41800.0, "GAD3": 11500.0}
        for q in ALL_QUARTERS:
            upsert_obs(gad_var, q, approx[gad_var], source="CONSTANT")
        print(f"  {gad_var}: using constant approximation ({approx[gad_var]}k)")

conn.commit()
print()

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
in_db = set(r[0] for r in conn.execute("SELECT DISTINCT series_id FROM observations").fetchall())
conn.close()

print("=== Done ===")
print(f"Total series now in DB: {len(in_db)}")

# Check how many of the 86 missing are now loaded
missing_86 = [
    "ADJW","APH","ASSETSA","CCLACA","CGACRES","CGCGLA","CGGILTS","CGLIQ","CGMISP",
    "CGWADJ","CIL","CONACC","CORP","CTC","CUST","DEBTW","DELTA","DEPHHADJ","DIPHHuf",
    "DISCO","ENVLEVY","ERCG","ERLA","EUETS","EUOT","FCACA","FISIMROW","FLEASGG","FP",
    "FSMADJ","GAD1","GAD2","GAD3","GGGDRES","HH","HRRPW","IIB","ILGAC","INCTAC",
    "INHT","INSURE","KCGLA","KCGPC","KGLAPC","LAEPS","LALIQ","LAPR","LAWADJ","LCGPR",
    "MAJGDP","MKTIG","NAEQHHADJ","NAINSADJ","NAOLPEADJ","NDIV","NNSCTP","NPAA",
    "NPISHTC","OFLPS","OHT","OPT","PCAC","PCNDIV","PCRENT","PEHC","PIH","PROV",
    "PRP","PSFA","PSNDRES","ROCB","ROLT","RULC","SIB","SIPT","SP","SPECX","SV",
    "SWISSCAP","TCPRO","TPBRZ","TROD","TXALC","VEDCO","WEQPR","WPG",
]
now_loaded = [v for v in missing_86 if v in in_db]
still_missing = [v for v in missing_86 if v not in in_db]
print(f"Of 86 target exogenous: {len(now_loaded)} now in DB, {len(still_missing)} still missing")
if still_missing:
    print(f"  Still missing: {still_missing}")
