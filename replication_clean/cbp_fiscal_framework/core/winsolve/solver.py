"""
IdentitySolver — evaluates all identity equations in correct topological order.

Uses Tarjan's SCC algorithm on the contemporaneous dependency graph (with
behavioral variables treated as exogenous inputs) to find evaluation blocks.
Single-variable blocks are solved directly; multi-variable blocks use
Gauss-Seidel iteration.
"""

import logging
from typing import Dict, List, Set

from .parser import (
    Expr, Variable, Number, StringLit, BinOp, UnaryMinus,
    FuncCall, AtFuncCall, ParsedEquation,
)
from .model import WinsolveModel
from .evaluator import ModelState, solve_equation

logger = logging.getLogger(__name__)


def extract_contemporaneous(expr: Expr) -> Set[str]:
    """Extract variable names that appear at lag 0 (contemporaneous references only)."""
    if isinstance(expr, Variable):
        if expr.lag == 0:
            return {expr.name}
        return set()
    if isinstance(expr, (Number, StringLit)):
        return set()
    if isinstance(expr, UnaryMinus):
        return extract_contemporaneous(expr.operand)
    if isinstance(expr, BinOp):
        return extract_contemporaneous(expr.left) | extract_contemporaneous(expr.right)
    if isinstance(expr, (FuncCall, AtFuncCall)):
        result = set()
        for arg in expr.args:
            result |= extract_contemporaneous(arg)
        return result
    return set()


def _tarjan_scc(nodes: Set[str], adj: Dict[str, Set[str]]) -> List[List[str]]:
    """Tarjan's SCC algorithm. Returns SCCs in reverse topological order."""
    index_counter = [0]
    stack = []
    on_stack = set()
    index = {}
    lowlink = {}
    result = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, set()):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            result.append(scc)

    for v in sorted(nodes):
        if v not in index:
            strongconnect(v)

    return result


class IdentitySolver:
    """Evaluates identity equations in topological order with Gauss-Seidel
    for simultaneous blocks."""

    GAUSS_SEIDEL_TOL = 1e-8
    GAUSS_SEIDEL_MAX_ITER = 100

    def __init__(self, model: WinsolveModel):
        self.model = model
        self._behavioral = model.behavioral_variables()
        self._identity_eqs: Dict[str, ParsedEquation] = {}
        self._blocks: List[List[str]] = []
        self._build()

    def _build(self):
        """Build contemporaneous dependency graph and find evaluation order."""
        # Index identity equations by variable name
        for eq in self.model.identity_equations():
            self._identity_eqs[eq.lhs_variable] = eq

        identity_vars = set(self._identity_eqs.keys())
        exogenous = self.model.exogenous() | self._behavioral

        # Build contemporaneous-only adjacency (restricted to identity vars)
        adj: Dict[str, Set[str]] = {}
        for var in identity_vars:
            eq = self._identity_eqs[var]
            # Get contemporaneous deps from RHS and LHS
            rhs_deps = extract_contemporaneous(eq.rhs)
            lhs_deps = extract_contemporaneous(eq.lhs)
            all_deps = (rhs_deps | lhs_deps) - {var} - exogenous
            adj[var] = all_deps & identity_vars

        # Tarjan's SCC
        sccs = _tarjan_scc(identity_vars, adj)

        # _tarjan_scc visits nodes in alphabetical order and pushes each
        # completed SCC onto the result list as soon as it is finished.  In
        # Tarjan's algorithm, an SCC is only "finished" after all SCCs it
        # depends on (its successors in the dependency graph) have already
        # been pushed.  Consequently the raw output is already in
        # dependency-first (forward evaluation) order — no reversal needed.
        self._blocks = sccs

    @property
    def blocks(self) -> List[List[str]]:
        return self._blocks

    @property
    def identity_count(self) -> int:
        return len(self._identity_eqs)

    @property
    def behavioral_count(self) -> int:
        return len(self._behavioral)

    def topology_summary(self) -> str:
        """Human-readable topology report."""
        acyclic = [b for b in self._blocks if len(b) == 1]
        simultaneous = [b for b in self._blocks if len(b) > 1]
        sizes = sorted([len(b) for b in simultaneous])

        lines = [
            '--- Model Topology ---',
            f'  Identity equations: {self.identity_count}'
            f' ({sum(len(b) for b in self._blocks)} variables)',
            f'  Behavioral equations: {self.behavioral_count}'
            f' (treated as inputs)',
            f'  Evaluation blocks: {len(self._blocks)}',
            f'    Acyclic: {len(acyclic)}',
        ]
        if simultaneous:
            lines.append(
                f'    Simultaneous: {len(simultaneous)}'
                f' (sizes: {", ".join(str(s) for s in sizes)})'
            )
        lines.append(
            f'  Evaluation order: all'
            f' {sum(len(b) for b in self._blocks)} variables resolved'
        )
        return '\n'.join(lines)

    def solve_period(self, state: ModelState):
        """Solve all identity equations for the current period."""
        for block in self._blocks:
            if len(block) == 1:
                self._solve_single(block[0], state)
            else:
                self._solve_simultaneous(block, state)

    def _solve_single(self, var: str, state: ModelState):
        eq = self._identity_eqs[var]
        value = solve_equation(eq, state)
        state.set(var, value)

    def _solve_simultaneous(self, block: List[str], state: ModelState):
        """Gauss-Seidel iteration for a simultaneous block."""
        # Initialise block variables to 0 if not already set
        for var in block:
            try:
                state.get(var)
            except (KeyError, ValueError, IndexError):
                state.set(var, 0.0)

        for iteration in range(self.GAUSS_SEIDEL_MAX_ITER):
            max_residual = 0.0
            for var in block:
                old_val = state.get(var)
                eq = self._identity_eqs[var]
                new_val = solve_equation(eq, state)
                state.set(var, new_val)
                if old_val != 0.0:
                    residual = abs(new_val - old_val) / max(abs(old_val), 1e-15)
                else:
                    residual = abs(new_val)
                max_residual = max(max_residual, residual)

            if max_residual < self.GAUSS_SEIDEL_TOL:
                return

        logger.warning(
            "Gauss-Seidel did not converge for block %s after %d iterations"
            " (residual=%.2e)",
            block[:3], self.GAUSS_SEIDEL_MAX_ITER, max_residual,
        )
