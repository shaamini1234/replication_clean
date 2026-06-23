"""
Risk-adjusted fiscal feasibility assessment.

Computes headroom after risk adjustments, converts to a compliance probability
via a Z-score model, and generates CSV/Markdown reports.

Thresholds:
    compliance > 0.60  => ROBUST
    compliance > 0.40  => PRECARIOUS
    else               => UNFEASIBLE
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..inputs.schema import FiscalAggregates

logger = logging.getLogger(__name__)


@dataclass
class FeasibilityGap:
    forecast_headroom_bn: float
    risk_adjusted_headroom_bn: float
    probability_of_compliance: float  # 0.0 to 1.0


class FiscalFeasibilityReport:
    """Aggregates risk adjustments and computes compliance probability."""

    def __init__(self) -> None:
        self.baseline_headroom_bn: float = 0.0
        self.risk_adjustments_bn: float = 0.0
        self.final_headroom_bn: float = 0.0
        self.compliance_probability: float = 0.0
        self.narrative: List[str] = []

    # ------------------------------------------------------------------
    # Construction from live schema
    # ------------------------------------------------------------------

    @classmethod
    def from_fiscal_aggregates(
        cls,
        aggregates: List[FiscalAggregates],
        target_year: str,
    ) -> FiscalFeasibilityReport:
        """
        Build from OBR fiscal aggregates.

        Headroom = current_budget_surplus in the target_year row.
        Positive current_budget_surplus means the budget rule is met.
        """
        report = cls()
        target_row = next(
            (fa for fa in aggregates if fa.fiscal_year == target_year), None
        )
        if target_row is None:
            logger.warning(
                "target_year '%s' not found in aggregates. "
                "Setting baseline_headroom_bn = 0.",
                target_year,
            )
            report.set_baseline(0.0)
        else:
            report.set_baseline(target_row.current_budget_surplus)
            report.narrative.append(
                f"Baseline from current_budget_surplus ({target_year}): "
                f"£{target_row.current_budget_surplus:.1f}bn"
            )
        return report

    # ------------------------------------------------------------------
    # Manual construction
    # ------------------------------------------------------------------

    def set_baseline(self, headroom_bn: float) -> None:
        self.baseline_headroom_bn = headroom_bn

    def add_risk_adjustment(self, name: str, amount_bn: float) -> None:
        """Negative amount_bn = reduces headroom."""
        self.risk_adjustments_bn += amount_bn
        self.narrative.append(f"Risk Adjustment ({name}): £{amount_bn:.1f}bn")

    # ------------------------------------------------------------------
    # Compliance calculation
    # ------------------------------------------------------------------

    def calculate_gap(self, volatility_std: float = 2.0) -> FeasibilityGap:
        """
        Z-score compliance model.

        sigma_bn = volatility_std * 25.0   (1% GDP ~ £25bn)
        P(compliance) = Phi(headroom / sigma)
        """
        from scipy import stats

        self.final_headroom_bn = self.baseline_headroom_bn + self.risk_adjustments_bn
        sigma_bn = volatility_std * 25.0
        z_score = self.final_headroom_bn / sigma_bn if sigma_bn > 0 else 0.0
        self.compliance_probability = float(stats.norm.cdf(z_score))

        return FeasibilityGap(
            forecast_headroom_bn=self.baseline_headroom_bn,
            risk_adjusted_headroom_bn=self.final_headroom_bn,
            probability_of_compliance=self.compliance_probability,
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    @property
    def status(self) -> str:
        if self.compliance_probability > 0.60:
            return "ROBUST"
        if self.compliance_probability > 0.40:
            return "PRECARIOUS"
        return "UNFEASIBLE"

    def generate_summary(self) -> str:
        lines = [
            "=== FISCAL FEASIBILITY REPORT ===",
            f"Baseline Forecast Headroom:  £{self.baseline_headroom_bn:.1f}bn",
            "--- Risk Adjustments ---",
        ]
        lines.extend(self.narrative)
        lines.append("-" * 30)
        lines.append(f"Risk-Adjusted Headroom:      £{self.final_headroom_bn:.1f}bn")
        lines.append(f"Probability of Compliance:   {self.compliance_probability:.1%}")
        lines.append(f"Overall Assessment:          {self.status}")
        return "\n".join(lines)

    def generate_csv_output(
        self,
        output_path: str,
        baseline_data: Dict[int, float],
        counterfactual_data: Dict[int, float],
    ) -> None:
        """Write year-by-year baseline vs counterfactual comparison CSV."""
        years = sorted(set(baseline_data) | set(counterfactual_data))
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["Year", "Baseline_Metric", "Counterfactual_Metric", "Gap"],
            )
            writer.writeheader()
            for year in years:
                base = baseline_data.get(year, 0.0)
                count = counterfactual_data.get(year, 0.0)
                writer.writerow({
                    "Year": year,
                    "Baseline_Metric": base,
                    "Counterfactual_Metric": count,
                    "Gap": count - base,
                })
        logger.info("CSV output saved to %s", output_path)

    def generate_markdown_report(self, output_path: str) -> None:
        adjustments_block = "\n".join(f"- {line}" for line in self.narrative)
        content = f"""# Budget Analysis Report

## Executive Summary

{self.generate_summary()}

## Fiscal Feasibility Gap Analysis

The analysis identifies a risk-adjusted headroom of £{self.final_headroom_bn:.1f}bn.
This includes the following adjustments:

{adjustments_block}

## Risk Assessment

Probability of compliance with fiscal rules: {self.compliance_probability:.1%}.
Overall assessment: **{self.status}**

## Detailed Policy Impact

(See accompanying CSV for year-by-year breakdown)
"""
        with open(output_path, "w") as f:
            f.write(content)
        logger.info("Markdown report saved to %s", output_path)
