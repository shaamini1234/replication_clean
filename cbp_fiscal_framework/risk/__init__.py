"""
Risk and credibility analysis for the CBP fiscal framework.

PLANNED LAYER -- to be wired in. CredibilityAssessment / HeadroomDecomposition /
SensitivityAnalysis are scaffolding for an analysis that run_analysis.py does not
yet call (the live pipeline is inputs/ + core/). Intended work to be resumed, not
dead code; the roadmap is in replication_todo.md. Complete and importable, just
not yet run.
"""

from .credibility import CredibilityAssessment
from .headroom import HeadroomChange, HeadroomDecomposition
from .sensitivity import SensitivityAnalysis

__all__ = [
    "CredibilityAssessment",
    "HeadroomDecomposition",
    "HeadroomChange",
    "SensitivityAnalysis",
]
