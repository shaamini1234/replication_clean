#!/usr/bin/env python3
"""
BUILD DIPHHuf (household unsecured interest payments, FISIM) — a CONSTRUCTION, not a fetch.

DIPHHuf is exogenous in the model (no equation, no ONS code), so we construct it the same
way the model builds its SECURED sibling DIPHHmf:

    DIPHHmf = LHP(-1)   * ((1 + (RMORT  - R)/100)^0.25 - 1)     # secured (in the model)
    DIPHHuf = OLPEx(-1) * ((1 + (Runsec - R)/100)^0.25 - 1)     # unsecured (this build)

Inputs:
  - OLPEx  : unsecured-debt stock (£bn)  -> already in timeseries.db
  - R      : Bank Rate (%)               -> already in timeseries.db
  - Runsec : effective interest rate on consumer credit (%), which YOU download from the
             Bank of England 'effective interest rates' tables (interest-charging consumer
             credit). Save it as a 2-column CSV (date, rate) at RATE_CSV below.

The result is stored as a CONSTRUCTION (source='COMPUTED', value_source==value, clearly
labelled). It is NOT the OBR's own DIPHHuf — confirm the method/rate choice with the economist.
ADDS ONLY; removes nothing. Does NOT modify cbp_fiscal_framework.

Run:
    python sources_new/extraction_pipeline/16_build_diphhuf.py
"""
import os, csv, re, sqlite3, shutil
from datetime import datetime

def _find_repo():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(d, 'timeseries.db')):
            return d
        d = os.path.dirname(d)
    raise SystemExit('Could not locate repo root (needs timeseries.db)')

REPO = _find_repo()
DB   = os.path.join(REPO, 'timeseries.db')
# >>> download the BoE consumer-credit effective rate and save it here (date,rate columns):
RATE_CSV = os.path.join(REPO, 'sources_new', 'raw_data', 'timeseries', 'boe',
                        'consumer_credit_rate.csv')

QPAT = re.compile(r'^(\d{4})Q([1-4])$')
SRC_PRIORITY = ['OBR_EFO', 'ONS', 'COMPUTED', 'FRED', 'HMRC', 'MHCLG', 'CONSTANT']

def series_from_db(con, sid):
    """{YYYYQn: value} for a series, preferring sources in SRC_PRIORITY order."""
    rows = con.execute("SELECT quarter, value, source FROM observations WHERE series_id=? AND value IS NOT NULL", (sid,)).fetchall()
    best = {}
    for q, v, src in rows:
        pr = SRC_PRIORITY.index(src) if src in SRC_PRIORITY else 99
        if q not in best or pr < best[q][0]:
            best[q] = (pr, v)
    return {q: v for q, (_, v) in best.items()}

def prev_q(q):
    y, n = int(q[:4]), int(q[5]); return f'{y-1}Q4' if n == 1 else f'{y}Q{n-1}'

def parse_to_quarter(s):
    s = str(s).strip()
    m = QPAT.match(s)
    if m: return f'{m.group(1)}Q{m.group(2)}', True   # already quarterly
    for fmt in ('%Y-%m-%d', '%Y-%m', '%d %b %Y', '%d %b %y', '%b %Y', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            d = datetime.strptime(s, fmt)
            return f'{d.year}Q{(d.month-1)//3 + 1}', False   # monthly/daily -> needs averaging
        except ValueError:
            continue
    return None, None

def load_rate_csv(path):
    if not os.path.isfile(path):
        raise SystemExit(f'Rate CSV not found: {path}\n'
                         '  -> download the BoE consumer-credit effective rate, save as date,rate CSV here.')
    monthly = {}           # quarter -> [rates] (for averaging if sub-quarterly)
    quarterly = {}
    with open(path, newline='') as f:
        r = csv.reader(f)
        for row in r:
            if len(row) < 2: continue
            q, is_q = parse_to_quarter(row[0])
            if not q: continue                       # header / junk
            # rate = last numeric cell in the row
            rate = None
            for cell in row[1:]:
                try: rate = float(str(cell).replace(',', '').replace('%', '')); break
                except ValueError: continue
            if rate is None: continue
            if is_q: quarterly[q] = rate
            else: monthly.setdefault(q, []).append(rate)
    out = dict(quarterly)
    for q, vs in monthly.items():
        if len(vs) == 3 or q not in out:             # complete quarter, or fill if no quarterly given
            out[q] = sum(vs)/len(vs)
    return out

def main():
    con = sqlite3.connect(DB)
    olpex = series_from_db(con, 'OLPEx')
    rbase = series_from_db(con, 'R')
    if not olpex or not rbase:
        raise SystemExit(f'missing inputs in DB: OLPEx={len(olpex)} R={len(rbase)}')
    runsec = load_rate_csv(RATE_CSV)

    diphhuf = {}
    for q in sorted(set(rbase) & set(runsec)):
        pq = prev_q(q)
        if pq not in olpex: continue
        spread = runsec[q] - rbase[q]
        diphhuf[q] = olpex[pq] * ((1 + spread/100)**0.25 - 1)   # £bn (OLPEx is £bn)

    if not diphhuf:
        raise SystemExit('no overlapping quarters for OLPEx(-1), R and Runsec — check the rate CSV span.')

    shutil.copy(DB, DB + '.bak')
    if 'value_source' not in [c[1] for c in con.execute('PRAGMA table_info(observations)')]:
        con.execute('ALTER TABLE observations ADD COLUMN value_source REAL')
    if 'source_scale' not in [c[1] for c in con.execute('PRAGMA table_info(series)')]:
        con.execute('ALTER TABLE series ADD COLUMN source_scale REAL DEFAULT 1.0')
    con.execute("""INSERT INTO series(id,label,unit,ons_code,ons_scale,source_scale)
                   VALUES('DIPHHuf',?, '£bn','',1.0,1.0)
                   ON CONFLICT(id) DO UPDATE SET label=excluded.label, ons_scale=1.0, source_scale=1.0""",
                ('CONSTRUCTED (FISIM proxy): OLPEx(-1)*((1+(Runsec-R)/100)^0.25-1), mirrors DIPHHmf. '
                 'NOT the OBR series — confirm method/rate with economist.',))
    for q, v in sorted(diphhuf.items()):
        con.execute("""INSERT INTO observations
            (series_id,source,publication_date,quarter,value,data_type,value_source)
            VALUES('DIPHHuf','COMPUTED','CONSTRUCTED',?,?,'OUTTURN',?)
            ON CONFLICT(series_id,source,publication_date,quarter,data_type)
            DO UPDATE SET value=excluded.value, value_source=excluded.value_source""",
            (q, v, v))
    con.commit()
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()
    qs, vals = sorted(diphhuf), list(diphhuf.values())
    print(f'DIPHHuf: built {len(diphhuf)} quarters ({qs[0]}-{qs[-1]}); £bn range [{round(min(vals),3)}, {round(max(vals),3)}]')
    print(f'integrity_check: {ic}  (backup at timeseries.db.bak)')
    print('CONSTRUCTED (not the OBR series). Note: DIPHH in the DB looks like £m while this build is £bn '
          '(same unit as DIPHHmf); flag the DIPHHx identity units to the economist.')

if __name__ == '__main__':
    main()
