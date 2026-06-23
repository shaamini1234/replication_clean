#!/usr/bin/env python3
"""
Fetch CPIPRIVRENT (ONS code KYHJ, CPI private rents) and load it.

KYHJ is a MONTHLY series, which the project's ONSFetcher doesn't read (it only
handles quarterly/annual) — that's why the main script skipped it. This script
fetches KYHJ's monthly data directly and averages each calendar quarter to a
quarterly index, then loads it with the two-column convention.

It does NOT modify cbp_fiscal_framework (the model package is untouched).

RUN ON A MACHINE THAT CAN REACH ONS:
    python fetch_cpiprivrent.py
"""
import os, sqlite3, shutil, requests

def _find_repo():
    """Locate the repo root (works whether this script sits at root or in a subfolder)."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(d, 'timeseries.db')):
            return d
        d = os.path.dirname(d)
    raise SystemExit('Could not locate repo root (needs timeseries.db)')

REPO = _find_repo()
DB   = os.path.join(REPO, 'timeseries.db')
URL  = 'https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/KYHJ/data'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}

MONTHS = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
          'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}

def monthly_to_quarterly(months):
    """months: list of ONS month dicts -> {YYYYQn: mean index over the quarter}."""
    buckets = {}
    for it in months:
        try:
            y = int(it['year'])
            m = MONTHS[str(it['month']).strip().lower()]
            v = float(str(it['value']).replace(',', ''))
        except (KeyError, ValueError):
            continue
        q = (m - 1)//3 + 1
        buckets.setdefault(f'{y}Q{q}', []).append(v)
    # only keep complete quarters (3 months) to avoid part-quarter distortion
    return {q: sum(vs)/len(vs) for q, vs in buckets.items() if len(vs) == 3}

def main():
    r = requests.get(URL, headers=HEADERS, timeout=20); r.raise_for_status()
    data = r.json()
    qd = monthly_to_quarterly(data.get('months', []))
    if not qd:
        raise SystemExit('No monthly data parsed for KYHJ — check the response.')

    shutil.copy(DB, DB + '.bak')
    con = sqlite3.connect(DB)
    # ensure two-column schema
    if 'value_source' not in [c[1] for c in con.execute('PRAGMA table_info(observations)')]:
        con.execute('ALTER TABLE observations ADD COLUMN value_source REAL')
    if 'source_scale' not in [c[1] for c in con.execute('PRAGMA table_info(series)')]:
        con.execute('ALTER TABLE series ADD COLUMN source_scale REAL DEFAULT 1.0')

    con.execute("""INSERT INTO series(id,label,unit,ons_code,ons_scale,source_scale)
                   VALUES('CPIPRIVRENT','CPI private rents (KYHJ, monthly->quarterly avg)','index','KYHJ',1.0,1.0)
                   ON CONFLICT(id) DO UPDATE SET label=excluded.label, ons_scale=1.0, source_scale=1.0""")
    for q, v in sorted(qd.items()):
        con.execute("""INSERT INTO observations
            (series_id,source,publication_date,quarter,value,data_type,value_source)
            VALUES('CPIPRIVRENT','ONS','ONS',?,?,'OUTTURN',?)
            ON CONFLICT(series_id,source,publication_date,quarter,data_type)
            DO UPDATE SET value=excluded.value, value_source=excluded.value_source""",
            (q, v, v))     # index: value_source == value (no unit conversion)
    con.commit()
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    vals = list(qd.values())
    con.close()
    qs = sorted(qd)
    print(f'CPIPRIVRENT: loaded {len(qd)} quarters ({qs[0]}-{qs[-1]}); '
          f'index range [{round(min(vals),2)}, {round(max(vals),2)}]')
    print(f'integrity_check: {ic}  (backup at timeseries.db.bak)')
    print('Eyeball: CPI private rents is an index, ~100-based around its reference year.')

if __name__ == '__main__':
    main()
