#!/usr/bin/env python3
"""
Load the OBR trend/potential series from the LOCAL OBR Potential-output table (no web).

Source: sources_new/raw_data/2026-03/obr/efo-march-2026-detailed-forecast-tables-economy.xlsx
        sheet '1.15' (Potential output), the LEVELS columns.

  NAIRU    <- 'of which: equilibrium unemployment'   (per cent)
  TRER     <- 'Potential employment rate'            (per cent)
  TRPART16 <- 'of which: potential participation'    (per cent)
  TRAVH    <- 'Potential average hours'              (hours)
  TRPRODH  <- 'Potential productivity per hour'      (level/index — UNIT UNCONFIRMED)

These are rates/hours/levels, so value == value_source (no unit conversion).
History starts 2019Q1 (that's where table 1.15 begins). TRHS (trend total hours) is NOT a
column in 1.15 — left PENDING, not faked. ADDS ONLY; removes nothing.

Run:
    python sources_new/extraction_pipeline/15_fetch_obr_trends.py
"""
import os, re, sqlite3, shutil, openpyxl

def _find_repo():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(d, 'timeseries.db')):
            return d
        d = os.path.dirname(d)
    raise SystemExit('Could not locate repo root (needs timeseries.db)')

REPO = _find_repo()
DB   = os.path.join(REPO, 'timeseries.db')
XLSX = os.path.join(REPO, 'sources_new', 'raw_data', '2026-03', 'obr',
                    'efo-march-2026-detailed-forecast-tables-economy.xlsx')
QPAT = re.compile(r'^\d{4}Q[1-4]$')

# model var -> (header substring to match, model unit)
TARGETS = {
    'NAIRU':    ('equilibrium unemployment',     'per cent'),
    'TRER':     ('potential employment rate',    'per cent'),
    'TRPART16': ('potential participation',      'per cent'),
    'TRAVH':    ('potential average hours',      'hours'),
    'TRPRODH':  ('potential productivity per hour', 'per hour (UNIT UNCONFIRMED)'),
}

def build():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb['1.15']
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    # header row = the one containing 'equilibrium unemployment'
    hr = next(i for i, r in enumerate(rows)
              if any(isinstance(c, str) and 'equilibrium unemployment' in c.lower() for c in r))
    header = [str(c).lower() if c is not None else '' for c in rows[hr]]
    # quarter column = first column whose cells match YYYYQn
    qcol = None
    for ci in range(len(rows[hr+1]) if hr+1 < len(rows) else 0):
        for r in rows[hr+1:hr+6]:
            if ci < len(r) and isinstance(r[ci], str) and QPAT.match(r[ci].strip()):
                qcol = ci; break
        if qcol is not None:
            break
    # for each target, the FIRST column whose header contains the substring = the LEVELS column
    colmap = {}
    for var, (sub, _) in TARGETS.items():
        for ci, h in enumerate(header):
            if sub in h:
                colmap[var] = ci; break
    out = {var: {} for var in colmap}
    for r in rows[hr+1:]:
        if qcol is None or qcol >= len(r):
            continue
        q = r[qcol]
        if not (isinstance(q, str) and QPAT.match(q.strip())):
            continue
        for var, ci in colmap.items():
            v = r[ci] if ci < len(r) else None
            if isinstance(v, (int, float)):
                out[var][q.strip()] = float(v)
    return out

def main():
    data = build()
    if not any(data.values()):
        raise SystemExit('no trend data extracted from 1.15')
    shutil.copy(DB, DB + '.bak')
    con = sqlite3.connect(DB)
    if 'value_source' not in [c[1] for c in con.execute('PRAGMA table_info(observations)')]:
        con.execute('ALTER TABLE observations ADD COLUMN value_source REAL')
    if 'source_scale' not in [c[1] for c in con.execute('PRAGMA table_info(series)')]:
        con.execute('ALTER TABLE series ADD COLUMN source_scale REAL DEFAULT 1.0')

    summary = []
    for var, qd in data.items():
        if not qd:
            summary.append((var, 0, None, None, None)); continue
        unit = TARGETS[var][1]
        con.execute("""INSERT INTO series(id,label,unit,ons_code,ons_scale,source_scale)
                       VALUES(?,?,?,?,1.0,1.0)
                       ON CONFLICT(id) DO UPDATE SET label=excluded.label, ons_scale=1.0, source_scale=1.0""",
                    (var, f'{var} from OBR Potential-output table 1.15 (levels); '
                          f'value==value_source ({unit})', unit, ''))
        for q, v in sorted(qd.items()):
            con.execute("""INSERT INTO observations
                (series_id,source,publication_date,quarter,value,data_type,value_source)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(series_id,source,publication_date,quarter,data_type)
                DO UPDATE SET value=excluded.value, value_source=excluded.value_source""",
                (var, 'OBR_EFO', '2026-03', q, v, 'OUTTURN', v))
        qs = sorted(qd); vals = list(qd.values())
        summary.append((var, len(qd), qs[0], qs[-1], (round(min(vals),2), round(max(vals),2))))
    con.commit()
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()
    print(f'{"var":10}{"quarters":>9}  span            range')
    for var, n, q0, q1, rng in summary:
        print(f'{var:10}{n:>9}  {q0}-{q1}   {rng}')
    print(f'integrity_check: {ic}  (backup at timeseries.db.bak)')
    print('History starts 2019Q1 (table 1.15 range). TRHS not in 1.15 -> still PENDING.')
    print('Eyeball: NAIRU/TRER/TRPART16 ~ per-cent; TRAVH ~32 hours; TRPRODH ~600s (confirm its unit).')

if __name__ == '__main__':
    main()
