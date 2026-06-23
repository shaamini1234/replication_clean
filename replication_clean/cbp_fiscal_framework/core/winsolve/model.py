"""
WinsolveModel — structured equation database built from parsed equations.

Provides variable lookup, dependency graph, equation classification,
and exogenous/endogenous variable identification.
"""

from collections import defaultdict
from typing import Dict, List, Set

from .parser import (
    ParsedEquation, LHSForm, Expr,
    Number, Variable, BinOp, UnaryMinus, FuncCall, AtFuncCall, StringLit,
)


def extract_variables(expr: Expr) -> Set[str]:
    """Recursively extract all variable names from an AST expression."""
    if isinstance(expr, Variable):
        return {expr.name}
    if isinstance(expr, Number) or isinstance(expr, StringLit):
        return set()
    if isinstance(expr, UnaryMinus):
        return extract_variables(expr.operand)
    if isinstance(expr, BinOp):
        return extract_variables(expr.left) | extract_variables(expr.right)
    if isinstance(expr, (FuncCall, AtFuncCall)):
        result = set()
        for arg in expr.args:
            result |= extract_variables(arg)
        return result
    return set()


class WinsolveModel:
    """Holds the complete parsed equation database with dependency analysis."""

    def __init__(self, equations: List[ParsedEquation]):
        self.equations = equations
        self._by_name: Dict[str, ParsedEquation] = {}
        self._deps: Dict[str, Set[str]] = {}
        self._groups: Dict[str, List[ParsedEquation]] = defaultdict(list)
        self._build_index()

    def _build_index(self):
        for eq in self.equations:
            var = eq.lhs_variable
            if var != '?':
                self._by_name[var] = eq
                # Dependencies: all variables on the RHS (plus LHS for ratio forms)
                rhs_vars = extract_variables(eq.rhs)
                lhs_vars = extract_variables(eq.lhs)
                # For ratio LHS like A/A(-1) = ..., the LHS also references A
                # But the variable being defined is A, so exclude it from deps
                all_vars = rhs_vars | lhs_vars
                all_vars.discard(var)
                self._deps[var] = all_vars
            self._groups[eq.group].append(eq)

    def get_equation(self, var: str) -> ParsedEquation:
        return self._by_name[var]

    def dependencies(self, var: str) -> Set[str]:
        return self._deps.get(var, set())

    def all_endogenous(self) -> Set[str]:
        return set(self._by_name.keys())

    def exogenous(self) -> Set[str]:
        """Variables that appear on RHS but are never defined on any LHS."""
        endogenous = self.all_endogenous()
        all_rhs = set()
        for deps in self._deps.values():
            all_rhs |= deps
        return all_rhs - endogenous

    def groups(self) -> Dict[str, List[ParsedEquation]]:
        return dict(self._groups)

    def classify(self) -> Dict[str, List[ParsedEquation]]:
        """Group equations by LHS form."""
        result: Dict[str, List[ParsedEquation]] = defaultdict(list)
        for eq in self.equations:
            result[eq.lhs_form.name].append(eq)
        return dict(result)

    def identity_equations(self) -> List[ParsedEquation]:
        """Return equations that are identities (LEVEL, RATIO, IDENTITY_TAG)."""
        return [eq for eq in self.equations
                if eq.lhs_form in (LHSForm.LEVEL, LHSForm.RATIO, LHSForm.IDENTITY_TAG)
                and eq.lhs_variable != '?']

    def behavioral_variables(self) -> Set[str]:
        """Variables defined by behavioral (DLOG/D) equations."""
        return {eq.lhs_variable for eq in self.equations
                if eq.lhs_form in (LHSForm.DLOG, LHSForm.D)
                and eq.lhs_variable != '?'}

    def summary(self) -> str:
        """Human-readable summary of the model."""
        classified = self.classify()
        endo = self.all_endogenous()
        exo = self.exogenous()
        groups = self.groups()

        lines = [
            '--- OBR Macro Model ---',
            f'  Equations parsed: {len(self.equations)}',
        ]

        type_parts = []
        for form in LHSForm:
            eqs = classified.get(form.name, [])
            if eqs:
                type_parts.append(f'{len(eqs)} {form.name.lower()}')
        lines.append(f'  By type: {", ".join(type_parts)}')
        lines.append(f'  Groups: {len(groups)}')
        lines.append(f'  Variables: {len(endo)} endogenous, {len(exo)} exogenous')

        # Sample equations
        samples = ['CONS', 'CONSPS', 'WB', 'PRODH', 'PSCR', 'PSNBNSA']
        shown = []
        for name in samples:
            if name in self._by_name:
                eq = self._by_name[name]
                raw = eq.raw
                if len(raw) > 70:
                    raw = raw[:67] + '...'
                shown.append(f'    {name}: {raw}  [{eq.group}]')
        if shown:
            lines.append('')
            lines.append('  Sample equations:')
            lines.extend(shown)

        return '\n'.join(lines)
