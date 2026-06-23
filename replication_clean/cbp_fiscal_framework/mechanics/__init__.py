"""
Spending and proposal mechanics for the CBP fiscal framework.

PLANNED LAYER -- to be wired in. SpendingModel / CBPProposal / ProposalImpact
are scaffolding for a fiscal-feasibility analysis that run_analysis.py does not
yet call (the live pipeline is inputs/ + core/). This is intended work to be
resumed, not dead code: the roadmap for wiring it in is in replication_todo.md.
The package is complete and importable; it simply is not part of the run yet.
"""

from .expenditure import SpendingModel
from .proposals import CBPProposal, ProposalImpact

__all__ = ["SpendingModel", "CBPProposal", "ProposalImpact"]
