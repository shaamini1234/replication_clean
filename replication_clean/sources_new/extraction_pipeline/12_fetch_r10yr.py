#!/usr/bin/env python3
"""
Load R10YR (10-year gilt yield) from the local FRED CSV — no web needed.

Source: sources_new/raw_data/timeseries/fred/gilt_yields.csv
        column IRLTLT01GBM156N = UK 10-year government bond yield, MONTHLY, per cent.
This averages each complete calendar quarter to a quarterly yield and loads it with the
two-column convention. R10YR is a rate (%), so value == value_source (no unit conversion).

Provenance note: this is FRED data (tagged source='FRED'), not ONS/OBR — honest tagging.
Does NOT modify cbp_fiscal_framework.

Run (from the repo root, in your venv):
    python sources_new/extraction_pipeline/12_fetch_r10yr.py
"""
import os, csv, sqlite3, shutil

def _find_repo():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(d, 'timeseries.db')):
            return d
        d = os.path.dirname(d)
    raise SystemExit('Could not locate repo root (needs timeseries.db)')

REPO = _find_repo()
DB   = os.path.join(REPO, 'timeseries.db')
CSV  = os.path.join(REPO, 'sources_new', 'raw_data', 'timeseries', 'fred', 'gilt_yields.csv')

def monthly_to_quarterly(path):
    """Read the FRED monthly CSV -> {YYYYQn: mean yield over the quarter} (complete quarters only)."""
    buckets = {}
    with open(path, newline='') as f:
        r = csv.reader(f)
        next(r, None)                      # skip header (observation_date, IRLTLT01GBM156N)
        for row in r:
            if len(row) < 2:
                continue
            date, raw = row[0].strip(), row[1].strip()
            try:
                y, m = int(date[:4]), int(date[5:7])
                v = float(raw)             # FRED missing values are '.', which raises -> skipped
            except ValueError:
                continue
            q = (m - 1)//3 + 1
            buckets.setdefault(f'{y}Q{q}', []).append(v)
    return {q: sum(vs)/len(vs) for q, vs in buckets.items() if len(vs) == 3}

def main():
    if not os.path.isfile(CSV):
        raise SystemExit(f'FRED CSV not found: {CSV}')
    qd = monthly_to_quarterly(CSV)
    if not qd:
        raise SystemExit('No quarterly yields parsed — check the CSV.')

    shutil.copy(DB, DB + '.bak')
    con = sqlite3.connect(DB)
    if 'value_source' not in [c[1] for c in con.execute('PRAGMA table_info(observations)')]:
        con.execute('ALTER TABLE observations ADD COLUMN value_source REAL')
    if 'source_scale' not in [c[1] for c in con.execute('PRAGMA table_info(series)')]:
        con.execute('ALTER TABLE series ADD COLUMN source_scale REAL DEFAULT 1.0')

    con.execute("""INSERT INTO series(id,label,unit,ons_code,ons_scale,source_scale)
                   VALUES('R10YR','10-year gilt yield (FRED IRLTLT01GBM156N, monthly->quarterly avg)','per cent','',1.0,1.0)
                   ON CONFLICT(id) DO UPDATE SET label=excluded.label, ons_scale=1.0, source_scale=1.0""")
    for q, v in sorted(qd.items()):
        con.execute("""INSERT INTO observations
            (series_id,source,publication_date,quarter,value,data_type,value_source)
            VALUES('R10YR','FRED','FRED',?,?,'OUTTURN',?)
            ON CONFLICT(series_id,source,publication_date,quarter,data_type)
            DO UPDATE SET value=excluded.value, value_source=excluded.value_source""",
            (q, v, v))           # rate: value == value_source
    con.commit()
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()

    qs, vals = sorted(qd), list(qd.values())
    print(f'R10YR: loaded {len(qd)} quarters ({qs[0]}-{qs[-1]}); yield range '
          f'[{round(min(vals),2)}, {round(max(vals),2)}] %')
    print(f'integrity_check: {ic}  (backup at timeseries.db.bak)')
    print('Eyeball: UK 10-yr gilt yield, ~0.2% (2020) to ~15% (early 1980s) historically.')

if __name__ == '__main__':
    main()
