"""
Layer 0: Accounting Identity Enforcement

Pure validation — checks that OBR published data satisfies its own
accounting identities. No behavioral content.

Identities from OBR Group 12 (Public Sector Totals):
    PSCB  = PSCR - PSCE - DEP
    PSNI  = Gross Investment - DEP
    PSNB  = -PSCB + PSNI
    TME   = PSCE + DEP + PSNI  (equivalently: PSCR + PSNB)
"""

from dataclasses import dataclass
from typing import List

from cbp_fiscal_framework.inputs.schema import FiscalAggregates


@dataclass
class IdentityCheckResult:
    identity_name: str
    fiscal_year: str
    lhs: float
    rhs: float
    residual: float
    passes: bool
    tolerance: float


class AccountingIdentities:
    """Validates fiscal accounting identities on loaded OBR data."""

    def __init__(self, tolerance: float = 0.5):
        """
        Args:
            tolerance: max allowed residual in £bn (default 0.5 for rounding).
        """
        self.tolerance = tolerance
        self.results: List[IdentityCheckResult] = []

    def _check(self, name: str, fy: str, lhs: float, rhs: float) -> IdentityCheckResult:
        residual = abs(lhs - rhs)
        result = IdentityCheckResult(
            identity_name=name,
            fiscal_year=fy,
            lhs=lhs,
            rhs=rhs,
            residual=residual,
            passes=residual < self.tolerance,
            tolerance=self.tolerance,
        )
        self.results.append(result)
        return result

    def check_current_budget(self, fa: FiscalAggregates) -> IdentityCheckResult:
        """PSCB = PSCR - PSCE - DEP"""
        return self._check(
            'PSCB = PSCR - PSCE - DEP',
            fa.fiscal_year,
            lhs=fa.current_budget_surplus,
            rhs=fa.current_receipts - fa.current_expenditure - fa.depreciation,
        )

    def check_net_investment(self, fa: FiscalAggregates) -> IdentityCheckResult:
        """PSNI = Gross Investment - DEP"""
        return self._check(
            'PSNI = Gross Investment - DEP',
            fa.fiscal_year,
            lhs=fa.net_investment,
            rhs=fa.gross_investment - fa.depreciation,
        )

    def check_net_borrowing(self, fa: FiscalAggregates) -> IdentityCheckResult:
        """PSNB = -PSCB + PSNI"""
        return self._check(
            'PSNB = -PSCB + PSNI',
            fa.fiscal_year,
            lhs=fa.net_borrowing,
            rhs=-fa.current_budget_surplus + fa.net_investment,
        )

    def check_tme_consistency(self, fa: FiscalAggregates) -> IdentityCheckResult:
        """TME = PSCE + DEP + PSNI should equal PSCR + PSNB"""
        tme_expenditure = fa.current_expenditure + fa.depreciation + fa.net_investment
        tme_receipts = fa.current_receipts + fa.net_borrowing
        return self._check(
            'TME: PSCE+DEP+PSNI = PSCR+PSNB',
            fa.fiscal_year,
            lhs=tme_expenditure,
            rhs=tme_receipts,
        )

    def check_all(self, fa: FiscalAggregates) -> List[IdentityCheckResult]:
        return [
            self.check_current_budget(fa),
            self.check_net_investment(fa),
            self.check_net_borrowing(fa),
            self.check_tme_consistency(fa),
        ]

    def check_all_years(self, aggregates: List[FiscalAggregates]) -> List[IdentityCheckResult]:
        all_results = []
        for fa in aggregates:
            all_results.extend(self.check_all(fa))
        return all_results

    def summary_report(self) -> str:
        passed = sum(1 for r in self.results if r.passes)
        total = len(self.results)
        lines = [
            '=== Accounting Identity Validation ===',
            '',
            f'Results: {passed}/{total} passed (tolerance: {self.tolerance} bn)',
            '',
        ]
        for r in self.results:
            status = 'PASS' if r.passes else 'FAIL'
            lines.append(
                f'  [{status}] {r.fiscal_year}: {r.identity_name}'
                f'  (LHS={r.lhs:.3f}, RHS={r.rhs:.3f}, residual={r.residual:.6f})'
            )
        failures = [r for r in self.results if not r.passes]
        if failures:
            lines.append('')
            lines.append('FAILURES:')
            for r in failures:
                lines.append(
                    f'  {r.fiscal_year}: {r.identity_name}'
                    f' -- residual {r.residual:.6f} exceeds tolerance {r.tolerance}'
                )
        return '\n'.join(lines)
