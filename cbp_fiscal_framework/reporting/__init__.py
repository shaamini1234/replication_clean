"""
Fiscal-feasibility reporting for the CBP fiscal framework.

PLANNED LAYER -- to be wired in. FiscalFeasibilityReport / FeasibilityGap are
scaffolding for an analysis that run_analysis.py does not yet call (the live
pipeline is inputs/ + core/). Intended work to be resumed, not dead code; the
roadmap is in replication_todo.md. Complete and importable, just not yet run.
"""

from .fiscal_feasibility import FeasibilityGap, FiscalFeasibilityReport

__all__ = ["FiscalFeasibilityReport", "FeasibilityGap"]
