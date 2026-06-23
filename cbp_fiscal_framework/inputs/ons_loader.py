"""
Load ONS time series data and integrate into the model state.

Fetches from the ONS website, applies unit conversions, and returns
a dict of {winsolve_var: {YYYYQN: value}} ready for build_model_state.
"""

import logging
from typing import Dict, List, Optional

from .ons_fetcher import ONSFetcher

logger = logging.getLogger(__name__)

# (model_var, ons_formula, scale_factor, description)
# scale_factor: multiply ONS value by this to get model units
ONS_VARIABLES = [
    # Population — ONS publishes in thousands, model uses millions
    ('POPAL', 'EBAQ',          1/1000,  'Total population, millions'),
    # Producer price index — exogenous, used as-is
    ('PPIY',  'GB7S',          1.0,     'Producer output price index ex. taxes'),
    # Basic Price Adjustment — ONS publishes in £m, model in £bn
    ('BPA',   'NTAO',          1/1000,  'Basic Price Adjustment CVM, £bn'),
    # Household GFCF — £m → £bn
    ('IHHPS', 'RPZW',          1/1000,  'Household gross fixed capital formation, £bn'),
    # Wages & salaries — £m → £bn
    ('WFP',   'DTWM-DTWP',    1/1000,  'Wages & salaries inc. benefits in kind, £bn'),
    # Direct investment claims on ROW — £m → £bn
    ('DLROW', 'N2V3',          1/1000,  'UK direct investment claims on ROW, £bn'),
    # Average weekly earnings — ONS publishes £/week, use as level
    ('PSAVEI','KAC4',          1.0,     'Private sector avg weekly earnings, £/week'),
    # North Sea GVA — £m → £bn
    ('NSGVA', 'ABMM-KLS2',    1/1000,  'North Sea oil & gas GVA nominal, £bn'),
    # Market sector employment = MGRZ - G6NQ - G6NT - MGRT - MGRW (thousands)
    ('EMS',   'MGRZ-G6NQ-G6NT-MGRT-MGRW', 1.0, 'Market sector employment, thousands'),
]


def load_ons_data(variables_xlsx: str) -> Dict[str, Dict[str, float]]:
    """
    Fetch all ONS series and return {model_var: {YYYYQN: scaled_value}}.
    """
    fetcher = ONSFetcher(variables_xlsx)
    result: Dict[str, Dict[str, float]] = {}

    for model_var, formula, scale, desc in ONS_VARIABLES:
        logger.info("Fetching %s (%s)...", model_var, formula)
        raw = fetcher.fetch_variable(model_var)
        if raw:
            result[model_var] = {k: v * scale for k, v in raw.items()}
            sample = sorted(result[model_var].items())
            logger.info("  %s: %d quarters, 2008Q1=%.3f, latest=%s:%.3f",
                        model_var, len(raw),
                        result[model_var].get('2008Q1', float('nan')),
                        sample[-1][0] if sample else '?',
                        sample[-1][1] if sample else float('nan'))
        else:
            logger.warning("  %s: no data returned", model_var)

    return result


def align_to_state(ons_data: Dict[str, Dict[str, float]],
                   dates: List[str]) -> Dict[str, List[Optional[float]]]:
    """
    Align ONS quarterly data to the model's canonical date list.
    Returns {model_var: [value_or_None, ...]}.
    """
    aligned = {}
    for var, series in ons_data.items():
        aligned[var] = [series.get(d) for d in dates]
    return aligned
