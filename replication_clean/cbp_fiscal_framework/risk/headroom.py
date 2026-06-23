"""
Decomposes changes in the fiscal position between two OBR forecast vintages.
Separates economic factors from policy decisions and debt interest movements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List

from ..inputs.schema import FiscalAggregates

logger = logging.getLogger(__name__)


@dataclass
class HeadroomChange:
    """A single labelled component of headroom change between forecasts."""

    category: str  # "Economic", "Policy", "Debt_Interest", "Other"
    amount_bn: float  # Negative = deterioration
    description: str


class HeadroomDecomposition:
    """
    Decomposes the 'fiscal hole' between two OBR vintages by category.

    Integrates with run_comparison() in run_analysis.py:
        old_aggs = managers[old_vintage].get_data("fiscal_aggregates")
        new_aggs = managers[new_vintage].get_data("fiscal_aggregates")
        decomp = HeadroomDecomposition.from_vintage_comparison(old_aggs, new_aggs, "2029-30")
    """

    def __init__(self) -> None:
        self.changes: List[HeadroomChange] = []

    # ------------------------------------------------------------------
    # Construction from live schema
    # ------------------------------------------------------------------

    @classmethod
    def from_vintage_comparison(
        cls,
        old: List[FiscalAggregates],
        new: List[FiscalAggregates],
        target_year: str,
    ) -> HeadroomDecomposition:
        """
        Decompose PSNB change between two OBR vintages for target_year.

        Components:
            Economic    = change in current_receipts (revenue moves with GDP/tax base)
            Policy      = change in current_expenditure (spending decisions)
            Debt_Interest = change in net_investment (capital/depreciation)
            Other       = residual/rounding

        Sign convention: positive amount_bn = headroom improved (PSNB fell).
        """
        decomp = cls()

        old_row = next((fa for fa in old if fa.fiscal_year == target_year), None)
        new_row = next((fa for fa in new if fa.fiscal_year == target_year), None)

        if old_row is None or new_row is None:
            logger.warning(
                "target_year '%s' not found in one or both vintages. "
                "Returning empty decomposition.",
                target_year,
            )
            return decomp

        delta_receipts = new_row.current_receipts - old_row.current_receipts
        delta_expenditure = new_row.current_expenditure - old_row.current_expenditure
        delta_net_investment = new_row.net_investment - old_row.net_investment
        delta_psnb = new_row.net_borrowing - old_row.net_borrowing

        # Economic: higher receipts = lower PSNB = headroom gain
        decomp.add_change(
            "Economic",
            amount_bn=delta_receipts,
            description=f"Change in current_receipts ({target_year})",
        )

        # Policy: higher expenditure = higher PSNB = headroom loss (sign-flip)
        decomp.add_change(
            "Policy",
            amount_bn=-delta_expenditure,
            description=f"Change in current_expenditure ({target_year})",
        )

        # Net investment: higher net_investment = higher PSNB = headroom loss (sign-flip)
        decomp.add_change(
            "Debt_Interest",
            amount_bn=-delta_net_investment,
            description=f"Change in net_investment ({target_year})",
        )

        # Residual
        attributed = delta_receipts - delta_expenditure - delta_net_investment
        residual = -delta_psnb - attributed
        if abs(residual) > 0.1:
            decomp.add_change(
                "Other",
                amount_bn=residual,
                description=f"Residual/rounding ({target_year})",
            )

        return decomp

    # ------------------------------------------------------------------
    # Manual construction
    # ------------------------------------------------------------------

    def add_change(self, category: str, amount_bn: float, description: str) -> None:
        self.changes.append(HeadroomChange(category, amount_bn, description))

    def get_total_change(self) -> float:
        return sum(c.amount_bn for c in self.changes)

    def get_breakdown(self) -> Dict[str, float]:
        breakdown: Dict[str, float] = {}
        for c in self.changes:
            breakdown[c.category] = breakdown.get(c.category, 0.0) + c.amount_bn
        return breakdown

    def summary_report(self) -> str:
        lines = ["=== Headroom Decomposition ===", ""]
        for c in self.changes:
            sign = "+" if c.amount_bn >= 0 else ""
            lines.append(
                f"  [{c.category:<15}] {sign}{c.amount_bn:.1f}bn  {c.description}"
            )
        lines.append("")
        total = self.get_total_change()
        sign = "+" if total >= 0 else ""
        lines.append(f"  {'TOTAL':<17} {sign}{total:.1f}bn")
        return "\n".join(lines)
