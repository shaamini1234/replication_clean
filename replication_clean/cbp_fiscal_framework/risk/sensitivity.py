"""
Reverse stress tests and stochastic simulations for fiscal headroom analysis.
"""

from __future__ import annotations

from typing import Dict, List


class SensitivityAnalysis:
    """
    Static methods:
        reverse_stress_test()         - break-even for a single variable
        run_stochastic_simulation()   - fan chart (10/50/90 percentile bands)

    Instance methods:
        obr_sensitivity()             - multi-variable reverse stress using OBR ready reckoners
    """

    @staticmethod
    def reverse_stress_test(
        current_headroom_bn: float,
        sensitivity_factor: float,
    ) -> float:
        """
        Calculate the change in a variable required to wipe out headroom.

        Args:
            current_headroom_bn: Fiscal headroom in bn.
            sensitivity_factor: Impact of +1 unit change on headroom in bn.

        Returns:
            Units of change to reach zero headroom. inf if sensitivity_factor == 0.
        """
        if sensitivity_factor == 0:
            return float("inf")
        return current_headroom_bn / sensitivity_factor

    @staticmethod
    def run_stochastic_simulation(
        baseline_forecast: List[float],
        volatility_std: float,
        num_simulations: int = 1000,
    ) -> Dict[str, List[float]]:
        """
        Generate fan chart data via random-walk error accumulation.

        Args:
            baseline_forecast: Forecasted values for years 1-N.
            volatility_std: Std of annual forecast error.
            num_simulations: Number of Monte Carlo paths.

        Returns:
            Dict with keys "p10", "p50", "p90".
        """
        import numpy as np

        years = len(baseline_forecast)
        paths = np.zeros((num_simulations, years))

        for i in range(num_simulations):
            error = 0.0
            for t in range(years):
                shock = np.random.normal(0.0, volatility_std)
                error += shock
                paths[i, t] = baseline_forecast[t] + error

        return {
            "p10": np.percentile(paths, 10, axis=0).tolist(),
            "p50": np.percentile(paths, 50, axis=0).tolist(),
            "p90": np.percentile(paths, 90, axis=0).tolist(),
        }

    def obr_sensitivity(
        self,
        headroom_bn: float,
        ready_reckoners: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Multi-variable reverse stress test using OBR ready reckoner factors.

        Args:
            headroom_bn: Current fiscal headroom in bn.
            ready_reckoners: Variable name -> bn impact per unit shock.
                Example:
                    {
                        "gilt_yield_1pp":    9.0,
                        "gdp_growth_1pp":   -7.0,
                        "cpi_inflation_1pp": 4.5,
                        "unemployment_1pp":  5.0,
                    }

        Returns:
            Variable name -> break-even shock magnitude.
        """
        return {
            variable: self.reverse_stress_test(headroom_bn, factor)
            for variable, factor in ready_reckoners.items()
        }
