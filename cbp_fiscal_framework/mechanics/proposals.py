"""
Wraps PolicyMeasure into CBPProposal objects that split fiscal impact
into revenue and spending components with consistent sign conventions.

Sign convention:
    revenue_impact_bn  > 0 = revenue gain
    spending_impact_bn < 0 = cost (increase in spending)
    net_impact_bn      > 0 = net fiscal improvement
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..inputs.schema import PolicyMeasure


@dataclass
class ProposalImpact:
    """Fiscal impact of a CBP proposal for a single year."""

    year: int
    revenue_impact_bn: float
    spending_impact_bn: float
    net_impact_bn: float


class CBPProposal:
    """
    Wrapper for CBP policy proposals.

    Resolves a PolicyMeasure's year-keyed fiscal_impact_bn into separate
    revenue and spending components.
    """

    def __init__(self, measure: PolicyMeasure, proposal_type: str = "Revenue") -> None:
        if proposal_type not in ("Revenue", "Spending"):
            raise ValueError(
                f"proposal_type must be 'Revenue' or 'Spending', got {proposal_type!r}"
            )
        self.measure = measure
        self.proposal_type = proposal_type

    def cost_proposal(self, year: int) -> ProposalImpact:
        """
        Calculate fiscal impact for a specific year.

        For fiscal year "2024-25", pass year=2024.
        """
        impact_val = self.measure.fiscal_impact_bn.get(year, 0.0)

        if self.proposal_type == "Revenue":
            revenue_impact = impact_val
            spending_impact = 0.0
        else:
            revenue_impact = 0.0
            spending_impact = -impact_val

        return ProposalImpact(
            year=year,
            revenue_impact_bn=revenue_impact,
            spending_impact_bn=spending_impact,
            net_impact_bn=revenue_impact - spending_impact,
        )

    def multi_year_impact(self, years: List[int]) -> List[ProposalImpact]:
        """Return ProposalImpact for each year in the list."""
        return [self.cost_proposal(y) for y in years]
