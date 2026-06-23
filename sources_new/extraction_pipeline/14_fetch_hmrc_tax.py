#!/usr/bin/env python3
"""
Load SDLT and APPLEVY from the LOCAL HMRC monthly tax-receipts file (no web).

Source: sources_new/raw_data/reference/neidle_tax_census_2024_25/data/
        hmrc_tax_receipts_nics_statistics_table_2026-05-22.ods, sheet 'Receipts_Monthly'
        (monthly £m from April 2017; columns 'Stamp Duty Land Tax', 'Apprenticeship Levy').

Receipts are FLOWS, so a quarter = SUM of its 3 months (only complete quarters kept),
then £m -> £bn. value_source = quarterly £m, value = £bn.

NOTE: CORP ('HMRC owner-managed corporations') is NOT a receipts line — it's an
owner-manager income/count measure and is not in this file. It stays PENDING (HMRC
owner-manager stats / OBR assumption). The OBR detailed Receipts tables are annual
fiscal-year forecasts (no quarterly history), so they are not used here.

Needs: pandas, odfpy.  Does NOT modify cbp_fiscal_framework.

Run:
    python sources_new/extraction_pipeline/14_fetch_hmrc_tax.py
"""
import os, sqlite3, shutil
import pandas as pd

def _find_repo():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(d, 'timeseries.db')):
            return d
        d = os.path.dirname(d)
    raise SystemExit('Could not locate repo root (needs timeseries.db)')

REPO = _find_repo()
DB   = os.path.join(REPO, 'timeseries.db')
ODS  = os.path.join(REPO, 'sources_new', 'raw_data', 'reference', 'neidle_tax_census_2024_25',
                    'data', 'hmrc_tax_receipts_nics_statistics_table_2026-05-22.ods')

MONTHS = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
          'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}
TARGETS = {'SDLT': 'Stamp Duty Land Tax', 'APPLEVY': 'Apprenticeship Levy'}

def load_monthly():
    df = pd.read_excel(ODS, engine='odf', sheet_name='Receipts_Monthly', header=None)
    # locate header row (the one containing our column names) and the month column (col 0)
    hdr = None
    for r in range(12):
        rowvals = [str(x) for x in df.iloc[r].tolist()]
        if any('Stamp Duty Land Tax' == v for v in rowvals):
            hdr = r; break
    if hdr is None:
        raise SystemExit('header row not found in Receipts_Monthly')
    headers = [str(x).strip() for x in df.iloc[hdr].tolist()]
    colidx = {name: headers.index(col) for name, col in TARGETS.items() if col in headers}
    missing = [n for n in TARGETS if n not in colidx]
    if missing:
        raise SystemExit(f'columns not found: {missing}')

    # parse month rows below the header
    series = {n: {} for n in colidx}                  # var -> {YYYYQn: [monthly £m, ...]}
    for r in range(hdr + 1, df.shape[0]):
        label = str(df.iloc[r, 0]).strip()
        parts = label.split()
        if len(parts) != 2 or parts[0].lower() not in MONTHS:
            continue
        m = MONTHS[parts[0].lower()]
        try:
            y = int(parts[1])
        except ValueError:
            continue
        q = f'{y}Q{(m-1)//3 + 1}'
        for n, ci in colidx.items():
            v = df.iloc[r, ci]
            try:
                v = float(v)                          # '[X]'/blank -> ValueError -> skip
            except (ValueError, TypeError):
                continue
            series[n].setdefault(q, []).append(v)
    # complete quarters only (3 months); sum the flow
    return {n: {q: sum(vs) for q, vs in qd.items() if len(vs) == 3} for n, qd in series.items()}

def main():
    data = load_monthly()
    shutil.copy(DB, DB + '.bak')
    con = sqlite3.connect(DB)
    if 'value_source' not in [c[1] for c in con.execute('PRAGMA table_info(observations)')]:
        con.execute('ALTER TABLE observations ADD COLUMN value_source REAL')
    if 'source_scale' not in [c[1] for c in con.execute('PRAGMA table_info(series)')]:
        con.execute('ALTER TABLE series ADD COLUMN source_scale REAL DEFAULT 1.0')

    summary = []
    for var, qd in data.items():
        con.execute("""INSERT INTO series(id,label,unit,ons_code,ons_scale,source_scale)
                       VALUES(?,?,?,?,1.0,0.001)
                       ON CONFLICT(id) DO UPDATE SET label=excluded.label, ons_scale=1.0, source_scale=0.001""",
                    (var, f'{var} quarterly receipts from HMRC monthly stats (sum of 3 months); '
                          f'value=£bn, value_source=£m', '£bn', ''))
        for q, sv in sorted(qd.items()):              # sv = quarterly sum in £m
            con.execute("""INSERT INTO observations
                (series_id,source,publication_date,quarter,value,data_type,value_source)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(series_id,source,publication_date,quarter,data_type)
                DO UPDATE SET value=excluded.value, value_source=excluded.value_source""",
                (var, 'HMRC', 'HMRC', q, sv*0.001, 'OUTTURN', sv))
        qs = sorted(qd); vals = [v*0.001 for v in qd.values()]
        summary.append((var, len(qd), qs[0] if qs else None, qs[-1] if qs else None,
                        round(min(vals),3) if vals else None, round(max(vals),3) if vals else None))
    con.commit()
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()
    print(f'{"var":9}{"quarters":>9}  span            £bn range')
    for var, n, q0, q1, lo, hi in summary:
        print(f'{var:9}{n:>9}  {q0}-{q1}   [{lo}, {hi}]')
    print(f'integrity_check: {ic}  (backup at timeseries.db.bak)')
    print('CORP not loaded (not a receipts line) — stays PENDING. History starts 2017Q2 (HMRC monthly).')

if __name__ == '__main__':
    main()
