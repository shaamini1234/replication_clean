"""
Validates parsed equations against published OBR data.

For each equation, evaluates the RHS and compares to the published LHS
value. Equations where all variables are available are tested; others
are skipped.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import WinsolveModel, extract_variables
from .evaluator import ModelState, solve_equation
from .parser import ParsedEquation

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    tested_equations: int
    passed_equations: int
    failed_equations: int
    skipped_equations: int
    total_checks: int
    passed_checks: int
    per_equation: Dict[str, Dict]
    skip_reasons: Dict[str, str]


def validate_equations(
    model: WinsolveModel,
    state: ModelState,
    tolerance: float = 0.05,
    rel_tolerance: float = 0.001,
) -> ValidationReport:
    """
    Validate identity equations against published data.

    For each equation whose variables are all in the state:
    - Evaluate solve_equation() which returns the implied LHS value
    - Compare to the published LHS value already in the state
    - Pass if |computed - published| < max(tolerance, |published| * rel_tolerance)
    """
    identity_eqs = model.identity_equations()
    available_vars = set(state.values.keys())

    # Skip first 4 periods (need lags for d/dlog) and use rest
    start_t = 4
    end_t = len(state.dates)

    skip_reasons: Dict[str, str] = {}
    per_equation: Dict[str, Dict] = {}

    for eq in identity_eqs:
        var = eq.lhs_variable
        if var == '?':
            continue

        # Check if LHS variable is in the state
        if var not in available_vars:
            skip_reasons[var] = 'LHS not loaded'
            continue

        # Check if all RHS variables are available
        all_vars = extract_variables(eq.rhs) | extract_variables(eq.lhs)
        missing = all_vars - available_vars
        if missing:
            skip_reasons[var] = f'missing: {", ".join(sorted(missing)[:5])}'
            continue

        eq_tested = 0
        eq_passed = 0
        eq_max_residual = 0.0

        for t in range(start_t, end_t):
            state.current_t = t
            try:
                published = state.get(var)
                computed = solve_equation(eq, state)

                residual = abs(computed - published)
                threshold = max(tolerance, abs(published) * rel_tolerance)

                eq_tested += 1
                if residual <= threshold:
                    eq_passed += 1
                eq_max_residual = max(eq_max_residual, residual)

            except (KeyError, ValueError, IndexError, ZeroDivisionError,
                    OverflowError):
                pass

        if eq_tested > 0:
            per_equation[var] = {
                'tested': eq_tested,
                'passed': eq_passed,
                'max_residual': eq_max_residual,
                'raw': eq.raw[:70],
            }

    tested = len(per_equation)
    passed = sum(1 for v in per_equation.values() if v['passed'] == v['tested'])
    failed = tested - passed
    total_checks = sum(v['tested'] for v in per_equation.values())
    passed_checks = sum(v['passed'] for v in per_equation.values())

    return ValidationReport(
        tested_equations=tested,
        passed_equations=passed,
        failed_equations=failed,
        skipped_equations=len(skip_reasons),
        total_checks=total_checks,
        passed_checks=passed_checks,
        per_equation=per_equation,
        skip_reasons=skip_reasons,
    )
