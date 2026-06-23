"""
Models public expenditure by separating DEL and AME components.
Calculates debt interest dynamically from gilt yields when a yield shock is applied.

Key identity:
    TME = DEL_total + AME_total + debt_interest
    DEL_total = rdel_total + cdel_total
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from ..inputs.schema import DebtInterest, ExpenditureBreakdown, MarketAssumptions

logger = logging.getLogger(__name__)


class SpendingModel:
    """
    Public expenditure model built against live schema types.

    Debt interest can be:
        (a) taken from ExpenditureBreakdown.debt_interest_spending (OBR baseline), or
        (b) recalculated dynamically from DebtInterest detail + a yield shock.
    """

    def __init__(self) -> None:
        self._expenditure: Dict[str, ExpenditureBreakdown] = {}
        self._debt_interest: Dict[str, DebtInterest] = {}
        self._avg_gilt_yield: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_data_manager(cls, dm) -> SpendingModel:
        """Build from a loaded DataManager instance."""
        model = cls()

        expenditure_data = dm.get_data("expenditure_breakdown")
        if expenditure_data:
            model.load_expenditure(expenditure_data)
        else:
            logger.warning(
                "SpendingModel: 'expenditure_breakdown' not in DataManager. "
                "Call load_expenditure() manually or add loader."
            )

        debt_data = dm.get_data("debt_interest")
        if debt_data:
            model.load_debt_interest(debt_data)

        market_data = dm.get_data("market_assumptions")
        if market_data:
            model.load_market_assumptions(market_data)

        return model

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def load_expenditure(self, forecast: List[ExpenditureBreakdown]) -> None:
        for item in forecast:
            self._expenditure[item.fiscal_year] = item

    def load_debt_interest(self, breakdown: List[DebtInterest]) -> None:
        for item in breakdown:
            self._debt_interest[item.fiscal_year] = item

    def load_market_assumptions(self, market: List[MarketAssumptions]) -> None:
        """Average gilt_yield_20y by fiscal year (Q2-Q1 convention)."""
        by_fy: Dict[str, List[float]] = defaultdict(list)
        for m in market:
            year_int = int(m.date[:4])
            quarter = int(m.date[5])
            if quarter >= 2:
                fy = f"{year_int}-{str(year_int + 1)[-2:]}"
            else:
                fy = f"{year_int - 1}-{str(year_int)[-2:]}"
            by_fy[fy].append(m.gilt_yield_20y)

        for fy, yields in by_fy.items():
            self._avg_gilt_yield[fy] = sum(yields) / len(yields)

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def get_del_total(self, fiscal_year: str) -> float:
        item = self._expenditure.get(fiscal_year)
        if item is None:
            return 0.0
        return item.rdel_total + item.cdel_total

    def get_ame_excl_debt_interest(self, fiscal_year: str) -> float:
        item = self._expenditure.get(fiscal_year)
        if item is None:
            return 0.0
        return item.ame_total

    def get_debt_interest_baseline(self, fiscal_year: str) -> float:
        item = self._expenditure.get(fiscal_year)
        if item is None:
            return 0.0
        return item.debt_interest_spending

    def recalculate_debt_interest(
        self,
        fiscal_year: str,
        yield_shock_pct_pts: float = 0.0,
    ) -> float:
        """
        Recalculate debt interest with a yield shock.

        Scales the yield-sensitive portion (conventional + index-linked gilts)
        proportionally to the shock relative to the baseline yield.
        Falls back to baseline if DebtInterest detail is unavailable.
        """
        baseline_di = self._debt_interest.get(fiscal_year)
        if baseline_di is None:
            return self.get_debt_interest_baseline(fiscal_year)

        if yield_shock_pct_pts == 0.0:
            return baseline_di.total

        baseline_yield = self._avg_gilt_yield.get(fiscal_year, 4.0)
        if baseline_yield <= 0:
            baseline_yield = 4.0

        yield_sensitive = baseline_di.conventional_gilts + baseline_di.index_linked_gilts
        scaling = yield_shock_pct_pts / baseline_yield
        shock_impact = yield_sensitive * scaling

        return baseline_di.total + shock_impact

    def get_total_managed_expenditure(
        self,
        fiscal_year: str,
        yield_shock_pct_pts: float = 0.0,
    ) -> float:
        """
        TME = DEL_total + AME_total + debt_interest.

        If yield_shock_pct_pts != 0, recalculates debt interest dynamically.
        """
        del_total = self.get_del_total(fiscal_year)
        ame_total = self.get_ame_excl_debt_interest(fiscal_year)
        if yield_shock_pct_pts != 0.0:
            debt_interest = self.recalculate_debt_interest(fiscal_year, yield_shock_pct_pts)
        else:
            debt_interest = self.get_debt_interest_baseline(fiscal_year)
        return del_total + ame_total + debt_interest
