#!/usr/bin/env python3
"""
Load GAS and PELEC from the LOCAL OBR Economy detailed-forecast tables (no web).

  GAS   <- Table 1.9  'Gas prices (£)'      -> model wants pence/therm
  PELEC <- Table 1.20 'Pence per MWh' col   -> model wants pence/MWh

UNIT CAUTION (read this):
  The OBR figures look like £ (GAS ~0.5; PELEC ~45 = £/MWh), while the model labels are in
  PENCE. So we apply a ×100 (£->pence) conversion to `value`, but this is an ASSUMPTION.
  `value_source` keeps the exact OBR number, and the series label is flagged
  "UNIT UNCONFIRMED". Confirm the ×100 against the model before relying on `value`; if it's
  wrong, set CONVERT below to 1.0 and re-run.

Source: sources_new/raw_data/2026-03/obr/efo-march-2026-detailed-forecast-tables-economy.xlsx
Does NOT modify cbp_fiscal_framework.

Run:
    python sources_new/extraction_pipeline/13_fetch_energy_obr.py
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

CONVERT = 100.0          # £ -> pence assumption; set to 1.0 if the model expects £
QPAT = re.compile(r'^\d{4}Q[1-4]$')

def _quarter_col(ws):
    """Find the column index that holds the YYYYQn quarter labels."""
    for r in range(1, 12):
        for cidx in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=cidx).value
            if isinstance(v, str) and QPAT.match(v.strip()):
                return cidx
    raise RuntimeError('quarter column not found')

def extract(ws, header_match=None):
    """Return {YYYYQn: raw_value}. If header_match given, pick the column whose header
       contains that text; else the first numeric column to the right of the quarter column."""
    qcol = _quarter_col(ws)
    vcol = None
    if header_match:
        for r in range(1, 6):
            for cidx in range(1, ws.max_column + 1):
                v = ws.cell(row=r, column=cidx).value
                if isinstance(v, str) and header_match.lower() in v.lower():
                    vcol = cidx; break
            if vcol: break
        if not vcol:
            raise RuntimeError(f'header {header_match!r} not found')
    else:
        vcol = qcol + 1
    out = {}
    for r in range(1, ws.max_row + 1):
        q = ws.cell(row=r, column=qcol).value
        if isinstance(q, str) and QPAT.match(q.strip()):
            val = ws.cell(row=r, column=vcol).value
            if isinstance(val, (int, float)):
                out[q.strip()] = float(val)
    return out

def main():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    gas   = extract(wb['1.9'],  header_match='Gas prices')
    pelec = extract(wb['1.20'])                       # single value column
    wb.close()
    if not gas or not pelec:
        raise SystemExit(f'extraction empty: GAS={len(gas)} PELEC={len(pelec)}')

    shutil.copy(DB, DB + '.bak')
    con = sqlite3.connect(DB)
    if 'value_source' not in [c[1] for c in con.execute('PRAGMA table_info(observations)')]:
        con.execute('ALTER TABLE observations ADD COLUMN value_source REAL')
    if 'source_scale' not in [c[1] for c in con.execute('PRAGMA table_info(series)')]:
        con.execute('ALTER TABLE series ADD COLUMN source_scale REAL DEFAULT 1.0')

    def load(var, raw, model_unit):
        con.execute("""INSERT INTO series(id,label,unit,ons_code,ons_scale,source_scale)
                       VALUES(?,?,?,?,1.0,?)
                       ON CONFLICT(id) DO UPDATE SET label=excluded.label, ons_scale=1.0, source_scale=excluded.source_scale""",
                    (var, f'{var} from OBR EFO economy tables — UNIT UNCONFIRMED '
                          f'(value = raw x{CONVERT:g}, assumed £->pence; confirm vs model)',
                     model_unit, '', CONVERT))
        for q, sv in sorted(raw.items()):
            con.execute("""INSERT INTO observations
                (series_id,source,publication_date,quarter,value,data_type,value_source)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(series_id,source,publication_date,quarter,data_type)
                DO UPDATE SET value=excluded.value, value_source=excluded.value_source""",
                (var, 'OBR_EFO', '2026-03', q, sv * CONVERT, 'OUTTURN', sv))
        return len(raw)

    ng = load('GAS',   gas,   'pence per therm')
    np_ = load('PELEC', pelec, 'pence per MWh')
    con.commit()
    ic = con.execute('PRAGMA integrity_check').fetchone()[0]
    con.close()

    def rng(d): vs=list(d.values()); return round(min(vs),3), round(max(vs),3)
    print(f'GAS:   {ng} quarters; raw £ range {rng(gas)}  -> value (x{CONVERT:g}) {tuple(round(v*CONVERT,1) for v in rng(gas))}')
    print(f'PELEC: {np_} quarters; raw range {rng(pelec)} -> value (x{CONVERT:g}) {tuple(round(v*CONVERT,1) for v in rng(pelec))}')
    print(f'integrity_check: {ic}  (backup at timeseries.db.bak)')
    print('** UNIT UNCONFIRMED: value assumes £->pence (x100). Confirm vs the model; '
          'if it expects £, set CONVERT=1.0 and re-run. value_source keeps the raw OBR figure. **')

if __name__ == '__main__':
    main()
