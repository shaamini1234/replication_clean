"""
SQLite time series database for the CBP fiscal framework.

Stores OBR EFO, ONS, and computed series in a single queryable DB,
eliminating repeated XLSX parsing and ONS API calls.

Schema:
    series(id, label, source, unit, ons_code, obr_sheet, last_updated)
    observations(series_id, vintage, quarter, value)

Usage:
    from cbp_fiscal_framework.db.timeseries_db import TimeSeriesDB

    db = TimeSeriesDB('cbp_fiscal_framework/db/timeseries.db')
    db.build_from_obr('data/2026-03/obr', '2026-03')
    db.build_from_ons('docs/OBR_Model_Variables_March_2025.xlsx')

    gdpm = db.get_series('GDPM', vintage='2026-03')
    # → {'2008Q1': 399.7, '2008Q2': 401.2, ...}
"""

import os
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    id                  TEXT PRIMARY KEY,
    label               TEXT,
    unit                TEXT,
    ons_code            TEXT,
    ons_scale           REAL DEFAULT 1.0,  -- multiply raw ONS value to get OBR units
    has_obr             INTEGER DEFAULT 0, -- 1 if OBR_EFO data is loaded
    has_ons             INTEGER DEFAULT 0, -- 1 if ONS mirror data is loaded
    obr_pub_dates       TEXT,              -- comma-separated OBR publication rounds
    ons_fetch_dates     TEXT,              -- comma-separated ONS fetch dates
    divergence_start    TEXT,              -- first quarter where OBR/ONS differ >0.5%
    divergence_avg_pct  REAL,              -- avg abs % difference in diverging period
    last_updated        TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    series_id        TEXT NOT NULL,
    source           TEXT NOT NULL,       -- 'OBR_EFO' or 'ONS'
    publication_date TEXT NOT NULL,       -- '2026-03' for OBR rounds, '2026-06-12' for ONS fetches
    quarter          TEXT NOT NULL,       -- '2008Q1'
    value            REAL,
    data_type        TEXT DEFAULT 'OUTTURN',  -- 'OUTTURN' or 'FORECAST'
    PRIMARY KEY (series_id, source, publication_date, quarter)
);

CREATE INDEX IF NOT EXISTS idx_obs_series  ON observations(series_id);
CREATE INDEX IF NOT EXISTS idx_obs_quarter ON observations(quarter);
CREATE INDEX IF NOT EXISTS idx_obs_source  ON observations(source);
CREATE INDEX IF NOT EXISTS idx_obs_pubdate ON observations(publication_date);
"""

# Priority order when merging sources — first match wins
SOURCE_PRIORITY = ['OBR_EFO', 'ONS', 'COMPUTED', 'CALIBRATED']


class TimeSeriesDB:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        logger.info("Database: %s", path)

    # ── write ─────────────────────────────────────────────────────────────────

    def upsert_series(self, series_id: str, label: str, source: str,
                      unit: str = '', ons_code: str = '', obr_sheet: str = '',
                      ons_scale: float = 1.0):
        """Upsert a series entry. source must be 'OBR_EFO' or 'ONS'."""
        has_obr = 1 if source == 'OBR_EFO' else 0
        has_ons = 1 if source == 'ONS' else 0
        self._conn.execute(
            """INSERT INTO series(id, label, unit, ons_code, ons_scale,
                                  has_obr, has_ons, last_updated)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 label=COALESCE(excluded.label, series.label),
                 unit=COALESCE(excluded.unit, series.unit),
                 ons_code=COALESCE(NULLIF(excluded.ons_code,''), series.ons_code),
                 ons_scale=CASE WHEN excluded.has_ons=1 THEN excluded.ons_scale ELSE series.ons_scale END,
                 has_obr=MAX(series.has_obr, excluded.has_obr),
                 has_ons=MAX(series.has_ons, excluded.has_ons),
                 last_updated=excluded.last_updated""",
            (series_id, label, unit, ons_code, ons_scale,
             has_obr, has_ons, datetime.utcnow().isoformat())
        )

    def upsert_observations(self, series_id: str, source: str,
                            publication_date: str, data: Dict[str, float],
                            data_type: str = 'OUTTURN'):
        rows = [(series_id, source, publication_date, quarter, value, data_type)
                for quarter, value in data.items() if value is not None]
        self._conn.executemany(
            """INSERT INTO observations(series_id, source, publication_date, quarter, value, data_type)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(series_id, source, publication_date, quarter)
               DO UPDATE SET value=excluded.value, data_type=excluded.data_type""",
            rows
        )
        self._conn.commit()

    # ── read ──────────────────────────────────────────────────────────────────

    def get_series(self, series_id: str, source: Optional[str] = None,
                   publication_date: Optional[str] = None) -> Dict[str, float]:
        """Return {quarter: value} for a series, optionally filtered by source/date."""
        where, params = ['series_id=?'], [series_id]
        if source:
            where.append('source=?'); params.append(source)
        if publication_date:
            where.append('publication_date=?'); params.append(publication_date)
        rows = self._conn.execute(
            f"SELECT quarter, value FROM observations WHERE {' AND '.join(where)} ORDER BY quarter",
            params
        ).fetchall()
        return {r['quarter']: r['value'] for r in rows}

    def get_series_preferred(self, series_id: str,
                              obr_pub_date: str = '2026-03') -> Dict[str, float]:
        """
        Return {quarter: value} preferring OBR_EFO where available,
        filling gaps from ONS (scaled to OBR units).
        """
        result: Dict[str, float] = {}

        # OBR data first
        for r in self._conn.execute(
            "SELECT quarter, value FROM observations WHERE series_id=? AND source='OBR_EFO' AND publication_date=? ORDER BY quarter",
            (series_id, obr_pub_date)
        ).fetchall():
            result[r['quarter']] = r['value']

        # Fill gaps from ONS, applying scale
        scale_row = self._conn.execute(
            "SELECT ons_scale FROM series WHERE id=?", (series_id,)
        ).fetchone()
        scale = scale_row['ons_scale'] if scale_row else 1.0

        for r in self._conn.execute(
            "SELECT quarter, value FROM observations WHERE series_id=? AND source='ONS' ORDER BY quarter",
            (series_id,)
        ).fetchall():
            if r['quarter'] not in result:
                result[r['quarter']] = r['value'] * scale

        return dict(sorted(result.items()))

    def detect_ons_scale(self, series_id: str,
                          obr_pub_date: str = '2026-03') -> Optional[float]:
        """
        Auto-detect the scale factor to convert ONS units to OBR units.
        Uses the median ratio of OBR/ONS in the overlapping historical period.
        Returns None if insufficient overlap.
        """
        import statistics
        obr = self.get_series(series_id, source='OBR_EFO', publication_date=obr_pub_date)
        ons_rows = self._conn.execute(
            "SELECT quarter, value FROM observations WHERE series_id=? AND source='ONS'",
            (series_id,)
        ).fetchall()
        ons = {r['quarter']: r['value'] for r in ons_rows}

        ratios = []
        for q in obr:
            if q in ons and ons[q] != 0 and obr[q] is not None:
                ratios.append(obr[q] / ons[q])

        if len(ratios) < 4:
            return None
        median = statistics.median(ratios)
        # Round to nearest power of 10 — should be 1.0, 0.001, 0.01 etc.
        import math
        if median <= 0:
            return None
        rounded = 10 ** round(math.log10(median))
        return rounded

    def list_series(self, source: Optional[str] = None) -> List[dict]:
        if source:
            rows = self._conn.execute(
                "SELECT * FROM series WHERE source=? ORDER BY id", (source,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM series ORDER BY source, id").fetchall()
        return [dict(r) for r in rows]

    def publication_dates(self, source: Optional[str] = None) -> List[str]:
        if source:
            rows = self._conn.execute(
                "SELECT DISTINCT publication_date FROM observations WHERE source=? ORDER BY publication_date",
                (source,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT DISTINCT source, publication_date FROM observations ORDER BY source, publication_date"
            ).fetchall()
        return [dict(r) for r in rows]

    def coverage(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT series_id) as n_series, COUNT(*) as n_obs FROM observations"
        ).fetchone()
        return dict(row)

    # ── bulk builders ─────────────────────────────────────────────────────────

    def build_from_obr(self, vintage_dir: str, vintage: str):
        """Load all OBR EFO series into the DB for a given vintage."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

        from cbp_fiscal_framework.inputs.data_manager import DataManager
        from cbp_fiscal_framework.core.winsolve import build_model_state

        dm = DataManager()
        dm.register_obr_vintage(vintage_dir)
        dm.load_all_data()
        state, coverage = build_model_state(dm)

        # Variable metadata from OBR variables spreadsheet (if available)
        var_meta = self._load_obr_variable_meta(
            os.path.join(os.path.dirname(vintage_dir), '..', '..',
                         'docs', 'OBR_Model_Variables_March_2025.xlsx')
        )

        # Write each loaded variable
        dates = state.dates
        for var, series in state.values.items():
            meta = var_meta.get(var, {})
            label = meta.get('label', var)
            ons_code = meta.get('ons_code', '')
            data = {dates[t]: v for t, v in enumerate(series) if v is not None}
            if data:
                self.upsert_series(var, label, 'OBR_EFO', ons_code=ons_code)
                self.upsert_observations(var, 'OBR_EFO', vintage, data)

        n = self.coverage()
        logger.info("OBR %s: wrote %d series, %d observations", vintage, n['n_series'], n['n_obs'])
        return n

    def build_from_ons(self, variables_xlsx: str, vintage: str = 'ONS'):
        """Fetch ONS series and store in DB."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

        from cbp_fiscal_framework.inputs.ons_loader import ONS_VARIABLES, load_ons_data

        raw = load_ons_data(variables_xlsx)
        for model_var, formula, scale, desc in ONS_VARIABLES:
            data = raw.get(model_var, {})
            if data:
                self.upsert_series(model_var, desc, 'ONS', ons_code=formula)
                self.upsert_observations(model_var, 'ONS', vintage, data)
                logger.info("ONS %s: %d quarters", model_var, len(data))

    def build_ons_mirrors(self, obr_vintage: str = '2026-03',
                           ons_vintage: str = 'ONS'):
        """
        For every OBR series that has a simple single ONS code and a known
        path, fetch the ONS version and store it at OBR units (auto-detected
        scale). This lets get_series_preferred() extend history pre-2008.

        Only fetches series with simple codes (no arithmetic formulas).
        """
        import re, time, requests
        from cbp_fiscal_framework.inputs.ons_fetcher import ONS_PATHS

        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        BASE = 'https://www.ons.gov.uk'

        # Get all series with a single clean ONS code (new schema: one row per series)
        rows = self._conn.execute(
            "SELECT id, label, ons_code FROM series WHERE ons_code != '' AND ons_code IS NOT NULL"
        ).fetchall()

        fetched, skipped = 0, 0
        for r in rows:
            code = r['ons_code'].strip()
            # Skip compound formulas — only handle bare 4-6 char codes
            if not re.fullmatch(r'[A-Z][A-Z0-9]{2,6}', code):
                skipped += 1
                continue
            path = ONS_PATHS.get(code)
            if not path:
                skipped += 1
                continue

            url = f'{BASE}{path}/timeseries/{code}/data'
            try:
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code != 200:
                    skipped += 1
                    continue
                ons_qtrs = resp.json().get('quarters', [])
                raw = {f"{q['year']}{q['quarter']}": float(q['value'].replace(',', ''))
                       for q in ons_qtrs if q.get('value')}
            except Exception:
                skipped += 1
                continue
            time.sleep(0.3)

            if not raw:
                skipped += 1
                continue

            # Store raw ONS data temporarily to detect scale
            self.upsert_series(r['id'], r['label'], 'ONS', ons_code=code)
            self.upsert_observations(r['id'], 'ONS', ons_vintage, raw)

            # Detect scale against OBR data
            scale = self.detect_ons_scale(r['id'], obr_vintage)
            if scale is None:
                scale = 1.0

            # Update scale in series table
            self._conn.execute(
                "UPDATE series SET ons_scale=? WHERE id=?",
                (scale, r['id'])
            )
            self._conn.commit()

            fetched += 1
            logger.info("ONS mirror %s (%s): %d quarters, scale=%.4g",
                        r['id'], code, len(raw), scale)

        logger.info("build_ons_mirrors: fetched=%d skipped=%d", fetched, skipped)
        return {'fetched': fetched, 'skipped': skipped}

    def store_cbp_computed(self, state_values: dict, dates: list,
                           run_label: str = 'CBP'):
        """
        Store CBP solver-computed variables back into the DB as CBP_COMPUTED.

        run_label is used as the publication_date so different model runs
        can be compared (e.g. 'CBP-2026-06-12', 'CBP-consumption-ecm').
        Only stores values in the FORECAST period (slots that were None on
        load — i.e. genuinely computed by the CBP solver, not passed through).
        """
        for var, series in state_values.items():
            data = {dates[t]: v for t, v in enumerate(series) if v is not None}
            if data:
                self.upsert_series(var, var, 'OBR_EFO')  # ensure series exists
                self.upsert_observations(var, 'CBP', run_label, data,
                                         data_type='CBP_COMPUTED')

    def build_from_computed(self, state_values: dict, dates: list,
                             vintage: str = 'COMPUTED'):
        """Legacy method — use store_cbp_computed() for new code."""
        for var, series in state_values.items():
            data = {dates[t]: v for t, v in enumerate(series) if v is not None}
            if data:
                self.upsert_series(var, var, 'OBR_EFO')
                self.upsert_observations(var, 'CBP', vintage, data,
                                         data_type='CBP_COMPUTED')

    def _load_obr_variable_meta(self, xlsx_path: str) -> dict:
        meta = {}
        try:
            import openpyxl
            wb = openpyxl.load_workbook(xlsx_path, read_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                if not row or not row[2]:
                    continue
                var = str(row[2]).strip()
                label = str(row[1]).strip()[:80] if row[1] else var
                ons = str(row[3]).strip() if row[3] else ''
                if ons in ('No Codes', 'Codes', 'ONS identifier code', ''):
                    ons = ''
                meta[var] = {'label': label, 'ons_code': ons}
            wb.close()
        except Exception as e:
            logger.warning("Could not load OBR variable metadata: %s", e)
        return meta

    def close(self):
        self._conn.close()
