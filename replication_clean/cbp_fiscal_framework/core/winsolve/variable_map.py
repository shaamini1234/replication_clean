"""
Maps Winsolve model variable names to OBR published data fields.

Each entry: winsolve_name -> (data_store_key, field_name)
"""

import logging
from typing import Dict, List, Optional, Tuple

from .evaluator import ModelState

logger = logging.getLogger(__name__)


# Winsolve variable name → (DataManager store key, field name on dataclass)
VARIABLE_MAP: Dict[str, Tuple[str, str]] = {
    # --- Sheet 1.1: Real GDP components (£bn CVM) ---
    'CONS':  ('gdp_components', 'private_consumption'),
    'CGG':   ('gdp_components', 'government_consumption'),
    'IF':    ('gdp_components', 'fixed_investment'),
    'IBUS':  ('gdp_components', 'business_investment'),
    'IH':    ('gdp_components', 'private_dwellings'),
    'GGI':   ('gdp_components', 'general_government_investment'),
    'DINV':  ('gdp_components', 'change_in_inventories'),
    'VAL':   ('gdp_components', 'valuables'),
    'X':     ('gdp_components', 'exports'),
    'M':     ('gdp_components', 'imports'),
    'GDPM':  ('gdp_components', 'gdp'),
    'TFE':   ('gdp_components', 'total_final_expenditure'),
    'SDE':   ('gdp_components', 'statistical_discrepancy'),

    # --- Sheet 1.2: Nominal GDP components (£bn CP) ---
    'CONSPS': ('nominal_gdp', 'private_consumption'),
    'CGGPS':  ('nominal_gdp', 'government_consumption'),
    'IFPS':   ('nominal_gdp', 'fixed_investment'),
    'GGIPS':  ('nominal_gdp', 'general_government_investment'),
    'VALPS':  ('nominal_gdp', 'valuables'),
    'DINVPS': ('nominal_gdp', 'change_in_inventories'),
    'XPS':    ('nominal_gdp', 'exports'),
    'MPS':    ('nominal_gdp', 'imports'),
    'TFEPS':  ('nominal_gdp', 'total_final_expenditure'),
    'SDEPS':  ('nominal_gdp', 'statistical_discrepancy'),
    'GDPMPS': ('nominal_gdp', 'gdp_market_prices'),

    # --- Sheet 1.3: GDP income (£bn nominal) ---
    'GVAPS':  ('gdp_income', 'gva_factor_cost'),

    # --- Sheet 1.6: Labour market ---
    'ET':     ('labour_market', 'employment_millions'),
    'ER':     ('labour_market', 'employment_rate'),
    'ULFS':   ('labour_market', 'unemployment_millions'),
    'LFSUR':  ('labour_market', 'unemployment_rate'),
    'PART16': ('labour_market', 'participation_rate'),
    'AVH':    ('labour_market', 'average_hours'),
    'HWA':    ('labour_market', 'total_hours_millions'),
    'FYEMP':  ('labour_market', 'compensation_of_employees'),

    # --- Sheet 1.7: Price index levels ---
    'PR':    ('price_indices', 'rpi'),
    'CPI':   ('price_indices', 'cpi'),
    'CPIH':  ('price_indices', 'cpih'),
    'OOH':   ('price_indices', 'ooh'),
    'PCE':   ('price_indices', 'pce'),
    'PGDP':  ('price_indices', 'pgdp'),

    # --- Sheet 1.9: Market assumptions ---
    'R':      ('market_assumptions', 'bank_rate'),
    'RL':     ('market_assumptions', 'gilt_yield_20y'),
    'RMORT':  ('market_assumptions', 'average_mortgage_rate'),
    'RX':     ('market_assumptions', 'exchange_rate_eri'),
    'RDEP':   ('market_assumptions', 'deposit_rate'),
    'RXD':    ('market_assumptions', 'usd_exchange_rate'),
    'PBRENT': ('market_assumptions', 'oil_price_usd'),
    'EQPR':   ('market_assumptions', 'equity_prices'),

    # --- Sheet 1.12: Household disposable income (from 2012Q1) ---
    'MI':     ('household_income', 'mixed_income'),
    'HHDI':   ('household_income', 'household_disposable_income'),

    # --- Sheet 1.8: Balance of payments ---
    'TB':     ('balance_of_payments', 'trade_balance'),
    'CB':     ('balance_of_payments', 'current_account_balance'),
    'CBPCNT': ('balance_of_payments', 'current_account_pct_gdp'),
    'NIPD':   ('balance_of_payments', 'investment_income_balance'),
    'TRANB':  ('balance_of_payments', 'transfers_balance'),

    # --- Sheet 1.11: Household balance sheet (from 2012Q1) ---
    'GFWPE':  ('household_balance_sheet', 'financial_assets'),
    'LHP':    ('household_balance_sheet', 'secured_liabilities'),
    'OLPE':   ('household_balance_sheet', 'other_liabilities'),

    # --- Sheet 1.6: Labour market extended ---
    'ES':     ('labour_market', 'employees_millions'),
    # WFJ = ET + WRGTP in the model (employment totals, not wages) — do not map to wages_salaries_bn
    'PSAVEI': ('labour_market', 'awe_index'),

    # --- Sheet 1.14: Output gap (from 1972Q1) ---
    'GAP':    ('output_gap', 'output_gap_pct'),

    # --- Sheet 1.15: Potential output (from 2019Q1) ---
    'TRGDP':  ('potential_output', 'potential_output_bn'),
    'UNUKP':  ('potential_output', 'nairu'),
    'POP16':  ('potential_output', 'population_16plus_mn'),
}

# Calibrated constants from the model code (Macroeconomic_model_code_March_2025.txt).
# These are fixed parameters, not time-varying. Loaded as flat series.
CALIBRATED_CONSTANTS: Dict[str, float] = {
    # Investment weights (Group 3)
    'WB': 0.31,
    'WP': 0.54,
    'WV': 0.14,
    'WG': 0.03,
    # Depreciation
    'RDELTA': 0.022,
    # Zero post-Brexit / zero by definition
    'EUSUBP': 0.0,
    'SWAPS': 0.0,
    'FISIMGG': 0.0,
    'SDLHH': 0.0,
    'SDLROW': 0.0,
    # CPI/price index weights (commented out in model but referenced by equations)
    'W1': 0.084,
    'W4': 0.024,
    'W5': 0.172,
    # RPI base indices (commented out in model but referenced by PR equation)
    'I4': 222.8,
    'I7': 317.7,
    'I9': 319.5,
    'I10': 115.1,
    'I11': 114.7,
    'I12': 111.2,
}


def build_model_state(dm) -> Tuple['ModelState', Dict]:
    """
    Populate a ModelState from all available OBR published data.

    Returns (state, report) where report has coverage statistics.
    """
    gdp = dm.get_data('gdp_components')
    if not gdp:
        raise ValueError("No gdp_components loaded — cannot build ModelState")

    dates = [g.date for g in gdp]
    state = ModelState(dates)

    loaded = []
    skipped = []

    # Load time-series variables from DataManager
    for winsolve_var, (store_key, field) in VARIABLE_MAP.items():
        data_list = dm.get_data(store_key)
        if not data_list:
            skipped.append((winsolve_var, f'no data for {store_key}'))
            continue

        # Build series aligned to canonical date list
        data_by_date = {}
        for record in data_list:
            d = record.date
            v = getattr(record, field, None)
            if v is not None:
                data_by_date[d] = float(v)

        series = [data_by_date.get(d) for d in dates]
        non_null = sum(1 for v in series if v is not None)

        if non_null > 0:
            state.init_variable(winsolve_var, series)
            loaded.append(winsolve_var)
        else:
            skipped.append((winsolve_var, 'all values None'))

    # Load calibrated constants as flat time series
    for const_name, const_val in CALIBRATED_CONSTANTS.items():
        state.init_variable(const_name, [const_val] * len(dates))
        loaded.append(const_name)

    # Unit scaling for variables whose published OBR values are in different
    # units from the Winsolve model definition.
    #
    # The OBR EFO economy tables report employment headcounts in millions
    # (ET = 32.776, ES = 27.867, ULFS = 1.304) and population in millions
    # (POP16 = 53.301 from the loader's ÷1000 of the raw 53,301).
    # The Winsolve model uses thousands throughout: ETLFS = 1000*(HWA/AVH) =
    # 32,776 and equations like ER = 100*ETLFS/POP16 only balance when POP16
    # is also in thousands.  Multiply the affected series by 1000.
    for _scale_var in ('ET', 'ES', 'ULFS', 'POP16'):
        if _scale_var in state.values:
            state.values[_scale_var] = [
                v * 1000.0 if v is not None else None
                for v in state.values[_scale_var]
            ]

    # Compute pure-identity seeds at t=0.
    # Some equations like ET = ET(-1) * ETLFS / ETLFS(-1) need ETLFS at t=0
    # (= t=-1 from the perspective of the first forward-solve step at t=1).
    # We seed these by evaluating the formula directly from loaded data.
    n = len(dates)
    hwa_s = state.values.get('HWA', [None] * n)
    avh_s = state.values.get('AVH', [None] * n)
    if hwa_s[0] is not None and avh_s[0] is not None and avh_s[0] != 0:
        etlfs_series = [None] * n
        for _i, (_h, _a) in enumerate(zip(hwa_s, avh_s)):
            if _h is not None and _a is not None and _a != 0:
                etlfs_series[_i] = 1000.0 * _h / _a
        state.init_variable('ETLFS', etlfs_series)
        loaded.append('ETLFS')

    # Seed recursive variables that are not published by OBR but can be
    # computed forward from an initial value.  We place the seed in slot t=0;
    # the IdentitySolver forward pass then propagates the series from there.
    #
    # Seeding strategy:
    #   - Index / ratio-tracking vars (RATIO form): start at 100 (or a
    #     meaningful base that cancels in ratios).
    #   - Accumulator vars (self += delta): start at 0.
    #   - Moving-average vars (4-quarter MA of self): seed first 4 slots with 0.
    #   - SDI (= SDI(-1), constant): seed at 0 — statistical discrepancy.
    #   - ECUPO (= ECUPO(-1) * RX/RX(-1)): EUK output index, start at 100.
    #   - ESLFS, WRGTP: closely track ES and ET respectively — seed from them.

    n = len(dates)

    def _first_nonnull(var: str) -> float:
        """Return first non-None published value for a loaded variable."""
        series = state.values.get(var, [])
        for v in series:
            if v is not None:
                return v
        return 100.0

    # BPA: balance-of-payments statistical item. Tracks GDPM proportionally.
    # BPA / BPA(-1) = GDPM / GDPM(-1) => BPA just follows GDPM in ratio.
    # Seed at first GDPM value so that the series starts at the same magnitude.
    bpa_seed = _first_nonnull('GDPM')
    bpa_series = [None] * n
    bpa_series[0] = bpa_seed
    state.init_variable('BPA', bpa_series)
    loaded.append('BPA')

    # BV: nominal inventory stock, BV = BV(-1) + DINVPS. Seed at 0.
    bv_series = [None] * n
    bv_series[0] = 0.0
    state.init_variable('BV', bv_series)
    loaded.append('BV')

    # ECUPO: EU-capital output index, tracks RX. Seed at 100.
    ecupo_series = [None] * n
    ecupo_series[0] = 100.0
    state.init_variable('ECUPO', ecupo_series)
    loaded.append('ECUPO')

    # ESLFS: LFS employees, ESLFS / ESLFS(-1) = ES / ES(-1).
    # Seed at first published ES value.
    eslfs_seed = _first_nonnull('ES')
    eslfs_series = [None] * n
    eslfs_series[0] = eslfs_seed
    state.init_variable('ESLFS', eslfs_series)
    loaded.append('ESLFS')

    # GGVA: government GVA, tracks CGG. Seed at first CGG value.
    ggva_seed = _first_nonnull('CGG')
    ggva_series = [None] * n
    ggva_series[0] = ggva_seed
    state.init_variable('GGVA', ggva_series)
    loaded.append('GGVA')

    # INV: real inventory stock, INV = INV(-1) + DINV. Seed at 0.
    inv_series = [None] * n
    inv_series[0] = 0.0
    state.init_variable('INV', inv_series)
    loaded.append('INV')

    # LASUBPR: 4-quarter MA of itself, inflation-adjusted. Seed first 4 at 0.
    lasubpr_series = [None] * n
    for i in range(min(4, n)):
        lasubpr_series[i] = 0.0
    state.init_variable('LASUBPR', lasubpr_series)
    loaded.append('LASUBPR')

    # M4IC: broad money index tracking GDPMPS. Seed at 100.
    m4ic_series = [None] * n
    m4ic_series[0] = 100.0
    state.init_variable('M4IC', m4ic_series)
    loaded.append('M4IC')

    # NPACG: 4-quarter MA of itself. Seed first 4 at 0.
    npacg_series = [None] * n
    for i in range(min(4, n)):
        npacg_series[i] = 0.0
    state.init_variable('NPACG', npacg_series)
    loaded.append('NPACG')

    # NPALA: same pattern as NPACG.
    npala_series = [None] * n
    for i in range(min(4, n)):
        npala_series[i] = 0.0
    state.init_variable('NPALA', npala_series)
    loaded.append('NPALA')

    # PCIH: house price deflator, PCIH / PCIH(-1) = IH / IH(-1). Seed at 100.
    pcih_series = [None] * n
    pcih_series[0] = 100.0
    state.init_variable('PCIH', pcih_series)
    loaded.append('PCIH')

    # RENTCO: rental income tracking GDPMPS. Seed at 100.
    rentco_series = [None] * n
    rentco_series[0] = 100.0
    state.init_variable('RENTCO', rentco_series)
    loaded.append('RENTCO')

    # SDI: statistical discrepancy, SDI = SDI(-1). Seed at 0 (constant zero).
    sdi_series = [None] * n
    sdi_series[0] = 0.0
    state.init_variable('SDI', sdi_series)
    loaded.append('SDI')

    # WRGTP: wage bill index, WRGTP = WRGTP(-1) * ET / ET(-1). Seed from ET.
    wrgtp_seed = _first_nonnull('ET')
    wrgtp_series = [None] * n
    wrgtp_series[0] = wrgtp_seed
    state.init_variable('WRGTP', wrgtp_series)
    loaded.append('WRGTP')

    report = {
        'loaded': loaded,
        'skipped': skipped,
        'total_dates': len(dates),
        'date_range': f'{dates[0]} – {dates[-1]}',
    }
    return state, report


def build_model_state_from_db(db,
                               obr_pub_date: str = '2026-03',
                               start_quarter: str = '2008Q1') -> Tuple['ModelState', Dict]:
    """
    Populate a ModelState from the time series database.

    - OBR data is preferred; ONS fills pre-2008 gaps (scaled to OBR units).
    - Only OUTTURN observations are loaded into the state; the forecast period
      (post-outturn boundary) is left as None so the solver must compute it.
    - OBR forecast values are returned separately in the report for comparison
      against CBP model outputs.
    - Date range always runs start_quarter → 2031Q1 (full forecast horizon).

    Returns (state, report) where report includes:
        - loaded: variables successfully loaded
        - obr_forecast: {var: {quarter: value}} — OBR published forecast values,
          not in the state but available for comparison
        - date_range, total_dates
    """
    import sqlite3

    # ── canonical date list: start_quarter → latest available ────────────────
    # Use OBR GDPM to establish the date range
    gdpm_all = db.get_series(series_id='GDPM', source='OBR_EFO',
                              publication_date=obr_pub_date)
    dates = sorted(q for q in gdpm_all if q >= start_quarter)
    if not dates:
        raise ValueError(f"No GDPM data found for {obr_pub_date} from {start_quarter}")

    state = ModelState(dates)
    loaded = []
    obr_forecast: Dict[str, Dict[str, float]] = {}

    # ── helper: get outturn-only series aligned to dates ────────────────────
    def load_outturn(var: str) -> Optional[List]:
        """
        Return a list aligned to `dates` with:
        - OUTTURN values filled (OBR preferred, ONS for gaps)
        - FORECAST slots left as None
        """
        # OBR outturn
        obr_out = db._conn.execute(
            """SELECT quarter, value FROM observations
               WHERE series_id=? AND source='OBR_EFO'
               AND publication_date=? AND data_type='OUTTURN'""",
            (var, obr_pub_date)
        ).fetchall()
        data = {r[0]: r[1] for r in obr_out}

        # Fill pre-OBR gaps from ONS (apply ons_scale)
        scale_row = db._conn.execute(
            "SELECT ons_scale FROM series WHERE id=?", (var,)
        ).fetchone()
        scale = scale_row[0] if scale_row else 1.0
        ons_rows = db._conn.execute(
            """SELECT quarter, value FROM observations
               WHERE series_id=? AND source='ONS'
               AND quarter >= ?""",
            (var, start_quarter)
        ).fetchall()
        for r in ons_rows:
            if r[0] not in data:
                data[r[0]] = r[1] * scale

        return [data.get(d) for d in dates]

    def load_obr_forecast(var: str) -> Dict[str, float]:
        """Return OBR forecast values (not loaded into state, kept for comparison)."""
        rows = db._conn.execute(
            """SELECT quarter, value FROM observations
               WHERE series_id=? AND source='OBR_EFO'
               AND publication_date=? AND data_type='FORECAST'""",
            (var, obr_pub_date)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def load_assumptions(var: str) -> List:
        """Load OUTTURN + ASSUMPTION quarters (conditioning inputs go in the state)."""
        rows = db._conn.execute(
            """SELECT quarter, value FROM observations
               WHERE series_id=? AND source='OBR_EFO'
               AND publication_date=?
               AND data_type IN ('OUTTURN', 'ASSUMPTION')""",
            (var, obr_pub_date)
        ).fetchall()
        data = {r[0]: r[1] for r in rows}
        # Also fill from ONS where available
        scale_row = db._conn.execute(
            "SELECT ons_scale FROM series WHERE id=?", (var,)
        ).fetchone()
        scale = scale_row[0] if scale_row else 1.0
        for r in db._conn.execute(
            "SELECT quarter, value FROM observations WHERE series_id=? AND source='ONS' AND quarter>=?",
            (var, start_quarter)
        ).fetchall():
            if r[0] not in data:
                data[r[0]] = r[1] * scale
        return [data.get(d) for d in dates]

    def is_assumption(var: str) -> bool:
        """True if this variable has any ASSUMPTION rows in the DB."""
        row = db._conn.execute(
            "SELECT 1 FROM observations WHERE series_id=? AND data_type='ASSUMPTION' LIMIT 1",
            (var,)
        ).fetchone()
        return row is not None

    # ── load VARIABLE_MAP series ──────────────────────────────────────────────
    for winsolve_var in VARIABLE_MAP:
        series = load_assumptions(winsolve_var) if is_assumption(winsolve_var) \
                 else load_outturn(winsolve_var)
        non_null = sum(1 for v in series if v is not None)
        if non_null > 0:
            state.init_variable(winsolve_var, series)
            loaded.append(winsolve_var)
            fc = load_obr_forecast(winsolve_var)
            if fc:
                obr_forecast[winsolve_var] = fc

    # ── calibrated constants ──────────────────────────────────────────────────
    n = len(dates)
    for const_name, const_val in CALIBRATED_CONSTANTS.items():
        state.init_variable(const_name, [const_val] * n)
        loaded.append(const_name)

    # Unit scaling is NOT applied here — the DB stores values already in model
    # units (thousands for employment, £bn for national accounts) because
    # build_from_obr() populates the DB from build_model_state() which has
    # already applied all scaling. Applying ×1000 again would double-scale.

    # ── recursive seeds (identical to build_model_state) ─────────────────────
    def _first_nonnull(var: str) -> float:
        s = state.values.get(var, [])
        for v in s:
            if v is not None:
                return v
        return 100.0

    hwa_s = state.values.get('HWA', [None] * n)
    avh_s = state.values.get('AVH', [None] * n)
    if hwa_s[0] is not None and avh_s[0] is not None and avh_s[0] != 0:
        etlfs_series = [
            1000.0 * h / a if (h is not None and a is not None and a != 0) else None
            for h, a in zip(hwa_s, avh_s)
        ]
        state.init_variable('ETLFS', etlfs_series)
        loaded.append('ETLFS')

    seeds = [
        ('BPA',     _first_nonnull('GDPM'), None),
        ('BV',      0.0, None),
        ('ECUPO',   100.0, None),
        ('ESLFS',   _first_nonnull('ES'), None),
        ('GGVA',    _first_nonnull('CGG'), None),
        ('INV',     0.0, None),
        ('M4IC',    100.0, None),
        ('PCIH',    100.0, None),
        ('RENTCO',  100.0, None),
        ('SDI',     0.0, None),
        ('WRGTP',   _first_nonnull('ET'), None),
    ]
    for var, seed_val, _ in seeds:
        s = [None] * n
        s[0] = seed_val
        state.init_variable(var, s)
        loaded.append(var)

    # Moving-average seeds (4 slots)
    for var in ('LASUBPR', 'NPACG', 'NPALA'):
        s = [None] * n
        for i in range(min(4, n)):
            s[i] = 0.0
        state.init_variable(var, s)
        loaded.append(var)

    report = {
        'loaded': loaded,
        'total_dates': n,
        'date_range': f'{dates[0]} – {dates[-1]}',
        'obr_forecast': obr_forecast,
    }
    return state, report
