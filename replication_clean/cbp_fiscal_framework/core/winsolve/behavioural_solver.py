"""
BehaviouralSolver — evaluates DLOG and D (behavioural) equations.

These are the econometric equations where the OBR estimated coefficients
(e.g. how consumption responds to income). They are separate from identity
equations, which are pure accounting definitions.

How it works:
  - Indexes all DLOG and D equations from the model.
  - Builds a dependency graph among those equations (some reference each
    other contemporaneously, e.g. CDUR depends on CONS in the same quarter).
  - Uses Tarjan's SCC to find a safe evaluation order, exactly as
    IdentitySolver does for identity equations.
  - solve_equation() in evaluator.py already knows how to invert each form:
      DLOG: VAR = VAR(-1) * exp(RHS)
      D:    VAR = VAR(-1) + RHS
  - Simultaneous blocks (circular deps) are resolved with Gauss-Seidel.

Nothing in this file modifies the original solver or evaluator — it just
calls the same solve_equation() with the appropriate equations.
"""

import logging
from typing import Dict, List, Set

from .parser import LHSForm, ParsedEquation
from .model import WinsolveModel
from .evaluator import ModelState, solve_equation

# Borrow the two helpers from solver.py — no need to duplicate them.
from .solver import extract_contemporaneous, _tarjan_scc

logger = logging.getLogger(__name__)


class BehaviouralSolver:
    """
    Evaluates all DLOG and D equations in dependency order.

    Usage mirrors IdentitySolver:
        solver = BehaviouralSolver(model)
        state.current_t = i
        solver.solve_period(state)
    """

    # Same convergence settings as IdentitySolver
    GAUSS_SEIDEL_TOL = 1e-8
    GAUSS_SEIDEL_MAX_ITER = 100

    def __init__(self, model: WinsolveModel):
        self.model = model
        self._behavioural_eqs: Dict[str, ParsedEquation] = {}
        self._blocks: List[List[str]] = []
        self._build()

    def _build(self):
        """Index behavioural equations and find a safe evaluation order."""

        # Collect all DLOG and D equations, keyed by the variable they define.
        for eq in self.model.equations:
            if eq.lhs_form in (LHSForm.DLOG, LHSForm.D) and eq.lhs_variable != '?':
                self._behavioural_eqs[eq.lhs_variable] = eq

        behav_vars = set(self._behavioural_eqs.keys())

        # Build contemporaneous dependency graph — only edges between
        # behavioural variables matter here. Deps on identity or exogenous
        # vars are fine; those values are already in state when we run.
        adj: Dict[str, Set[str]] = {}
        for var in behav_vars:
            eq = self._behavioural_eqs[var]
            rhs_deps = extract_contemporaneous(eq.rhs)
            # Only keep deps on other behavioural vars (not self)
            adj[var] = (rhs_deps & behav_vars) - {var}

        # Tarjan's SCC gives blocks in dependency-first order (same as
        # IdentitySolver — no reversal needed, see solver.py comment).
        self._blocks = _tarjan_scc(behav_vars, adj)

    @property
    def blocks(self) -> List[List[str]]:
        return self._blocks

    @property
    def equation_count(self) -> int:
        return len(self._behavioural_eqs)

    def topology_summary(self) -> str:
        """Human-readable breakdown of evaluation order."""
        acyclic = [b for b in self._blocks if len(b) == 1]
        simultaneous = [b for b in self._blocks if len(b) > 1]
        sizes = sorted(len(b) for b in simultaneous)
        lines = [
            '--- BehaviouralSolver Topology ---',
            f'  Behavioural equations : {self.equation_count}',
            f'  Evaluation blocks     : {len(self._blocks)}',
            f'    Acyclic (solo)      : {len(acyclic)}',
        ]
        if simultaneous:
            lines.append(
                f'    Simultaneous blocks : {len(simultaneous)}'
                f' (sizes: {", ".join(str(s) for s in sizes)})'
            )
        return '\n'.join(lines)

    def solve_period(self, state: ModelState):
        """Solve all behavioural equations for state.current_t."""
        for block in self._blocks:
            if len(block) == 1:
                self._solve_single(block[0], state)
            else:
                self._solve_simultaneous(block, state)

    def _solve_single(self, var: str, state: ModelState):
        """Solve one equation and write the result into state."""
        eq = self._behavioural_eqs[var]
        value = solve_equation(eq, state)
        state.set(var, value)

    def _solve_simultaneous(self, block: List[str], state: ModelState):
        """
        Gauss-Seidel for a circular block of behavioural equations.
        Identical approach to IdentitySolver._solve_simultaneous.
        """
        # Seed any uninitialised variables to avoid a KeyError on first pass.
        for var in block:
            try:
                state.get(var)
            except (KeyError, ValueError, IndexError):
                state.set(var, 0.0)

        for _ in range(self.GAUSS_SEIDEL_MAX_ITER):
            max_residual = 0.0
            for var in block:
                old_val = state.get(var)
                eq = self._behavioural_eqs[var]
                new_val = solve_equation(eq, state)
                state.set(var, new_val)
                denom = max(abs(old_val), 1e-15)
                residual = abs(new_val - old_val) / denom if old_val != 0.0 else abs(new_val)
                max_residual = max(max_residual, residual)

            if max_residual < self.GAUSS_SEIDEL_TOL:
                return

        logger.warning(
            "Gauss-Seidel did not converge for behavioural block %s "
            "after %d iterations (residual=%.2e)",
            block[:3], self.GAUSS_SEIDEL_MAX_ITER, max_residual,
        )
