"""
IFS-style assessment of spending plan credibility and welfare savings realism.

Flags implausibly large cuts to unprotected departments and applies
optimism bias discounts to welfare reform savings.
"""

from __future__ import annotations

from typing import Dict

from ..inputs.schema import ExpenditureBreakdown


class CredibilityAssessment:
    """
    Configurable parameters:
        cut_threshold_pct: Cuts above this % are flagged as not credible (default 5.0).
        welfare_haircut: Maximum discount for complex welfare savings (default 0.50).
    """

    def __init__(
        self,
        cut_threshold_pct: float = 5.0,
        welfare_haircut: float = 0.50,
    ) -> None:
        self.cut_threshold_pct = cut_threshold_pct
        self.welfare_haircut = welfare_haircut

    # ------------------------------------------------------------------
    # Construction from live schema
    # ------------------------------------------------------------------

    @classmethod
    def from_expenditure_breakdown(
        cls,
        baseline_row: ExpenditureBreakdown,
        proposed_total_spending_bn: float,
        protected_fraction: float = 0.60,
        cut_threshold_pct: float = 5.0,
        welfare_haircut: float = 0.50,
    ) -> Dict:
        """
        Auto-derive protected/unprotected split from ExpenditureBreakdown.

        Convention:
            protected_spending = total_baseline * protected_fraction
            unprotected_baseline = total_baseline * (1 - protected_fraction)

        NOTE: True departmental protection schedules require spending review
        detail not available in OBR aggregate tables. This is a modelling
        approximation.
        """
        instance = cls(
            cut_threshold_pct=cut_threshold_pct,
            welfare_haircut=welfare_haircut,
        )
        total_baseline = (
            baseline_row.rdel_total
            + baseline_row.cdel_total
            + baseline_row.ame_total
        )
        protected_bn = total_baseline * protected_fraction
        unprotected_bn = total_baseline * (1.0 - protected_fraction)

        return instance.assess_unallocated_spending(
            total_spending_bn=proposed_total_spending_bn,
            protected_spending_bn=protected_bn,
            unprotected_baseline_bn=unprotected_bn,
        )

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def assess_unallocated_spending(
        self,
        total_spending_bn: float,
        protected_spending_bn: float,
        unprotected_baseline_bn: float,
    ) -> Dict:
        """
        Flag where implied cuts to unprotected departments may be undeliverable.

        Returns dict with: implied_unprotected_spending_bn, real_cut_bn,
        real_cut_pct, is_credible, risk_flag.
        """
        implied_unprotected = total_spending_bn - protected_spending_bn
        cut_bn = unprotected_baseline_bn - implied_unprotected
        cut_pct = (
            (cut_bn / unprotected_baseline_bn * 100.0)
            if unprotected_baseline_bn
            else 0.0
        )
        is_credible = cut_pct < self.cut_threshold_pct
        return {
            "implied_unprotected_spending_bn": implied_unprotected,
            "real_cut_bn": cut_bn,
            "real_cut_pct": cut_pct,
            "is_credible": is_credible,
            "risk_flag": "Low" if is_credible else "High",
        }

    def scrutinize_welfare_savings(
        self,
        claimed_saving_bn: float,
        complexity_score: float = 1.0,
    ) -> float:
        """
        Apply optimism bias discount to welfare reform savings.

        At complexity_score=1.0, applies the full welfare_haircut (default 50%).
        At complexity_score=0.0, no discount.
        """
        discount_factor = 1.0 - (self.welfare_haircut * complexity_score)
        return claimed_saving_bn * discount_factor
