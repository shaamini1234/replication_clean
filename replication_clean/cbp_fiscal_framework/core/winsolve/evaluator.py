"""
AST evaluator and equation solver for the Winsolve model.

ModelState holds time-series data for all variables.
evaluate() recursively evaluates an AST expression given a ModelState.
solve_equation() inverts the LHS form to compute the variable value.
"""

import math
from typing import Dict, List, Optional

from .parser import (
    ParsedEquation, LHSForm, Expr,
    Number, Variable, BinOp, UnaryMinus, FuncCall, AtFuncCall, StringLit,
)


class ModelState:
    """Time-series storage for all model variables."""

    def __init__(self, dates: List[str]):
        self.dates = dates
        self.date_index: Dict[str, int] = {d: i for i, d in enumerate(dates)}
        self.values: Dict[str, List[Optional[float]]] = {}
        self.current_t: int = 0

    def get(self, var: str, lag: int = 0) -> float:
        t = self.current_t + lag
        if var not in self.values:
            raise KeyError(f"Variable '{var}' not in state")
        series = self.values[var]
        if t < 0 or t >= len(series):
            raise IndexError(
                f"Variable '{var}' lag={lag} -> t={t} out of range [0, {len(series)-1}]"
            )
        val = series[t]
        if val is None:
            raise ValueError(
                f"Variable '{var}' at t={t} (lag={lag}) is None"
            )
        return val

    def set(self, var: str, value: float):
        if var not in self.values:
            self.values[var] = [None] * len(self.dates)
        self.values[var][self.current_t] = value

    def get_at_date(self, var: str, date_str: str) -> float:
        if date_str not in self.date_index:
            raise KeyError(f"Date '{date_str}' not in state dates")
        t = self.date_index[date_str]
        if var not in self.values:
            raise KeyError(f"Variable '{var}' not in state")
        val = self.values[var][t]
        if val is None:
            raise ValueError(f"Variable '{var}' at date '{date_str}' is None")
        return val

    def date_to_index(self, date_str: str) -> int:
        if date_str not in self.date_index:
            raise KeyError(f"Date '{date_str}' not in state dates")
        return self.date_index[date_str]

    def init_variable(self, var: str, series: List[Optional[float]]):
        self.values[var] = series


def evaluate(expr: Expr, state: ModelState) -> float:
    """Recursively evaluate an AST expression against the current state."""

    if isinstance(expr, Number):
        return expr.value

    if isinstance(expr, StringLit):
        return expr.value

    if isinstance(expr, Variable):
        return state.get(expr.name, expr.lag)

    if isinstance(expr, UnaryMinus):
        return -evaluate(expr.operand, state)

    if isinstance(expr, BinOp):
        left = evaluate(expr.left, state)
        right = evaluate(expr.right, state)
        op = expr.op
        if op == '+':
            return left + right
        if op == '-':
            return left - right
        if op == '*':
            return left * right
        if op == '/':
            if right == 0:
                raise ZeroDivisionError(f"Division by zero in expression")
            return left / right
        if op == '^':
            return left ** right
        # Comparison operators (inside @recode conditions)
        if op == '=':
            return 1.0 if left == right else 0.0
        if op == '<':
            return 1.0 if left < right else 0.0
        if op == '>':
            return 1.0 if left > right else 0.0
        if op == '<=':
            return 1.0 if left <= right else 0.0
        if op == '>=':
            return 1.0 if left >= right else 0.0
        raise ValueError(f"Unknown operator: {op}")

    if isinstance(expr, FuncCall):
        name = expr.name
        if name == 'log':
            arg = evaluate(expr.args[0], state)
            return math.log(arg)
        if name == 'exp':
            arg = evaluate(expr.args[0], state)
            return math.exp(arg)
        if name == 'dlog':
            # dlog(X) = log(X) - log(X(-1))
            # The arg is a Variable; evaluate at current t and t-1
            arg_expr = expr.args[0]
            current = evaluate(arg_expr, state)
            lagged = _evaluate_lagged(arg_expr, state, -1)
            return math.log(current) - math.log(lagged)
        if name == 'd':
            # d(X) = X - X(-1)
            arg_expr = expr.args[0]
            current = evaluate(arg_expr, state)
            lagged = _evaluate_lagged(arg_expr, state, -1)
            return current - lagged
        raise ValueError(f"Unknown function: {name}")

    if isinstance(expr, AtFuncCall):
        name = expr.name.lower()
        if name == '@recode':
            # @recode(condition, true_val, false_val)
            cond = evaluate(expr.args[0], state)
            if cond != 0.0:
                return evaluate(expr.args[1], state)
            else:
                return evaluate(expr.args[2], state)
        if name == '@elem':
            # @elem(VAR, "date_string") — returns VAR's value at a specific date.
            # If the date is outside the state range (e.g. a 1970Q1 base year
            # reference but state starts at 2004Q1), raise a ValueError with
            # "is None" in the message so the caller silently skips the block,
            # the same way it handles missing contemporaneous data.
            var_expr = expr.args[0]
            date_expr = expr.args[1]
            if not isinstance(var_expr, Variable):
                raise ValueError(f"@elem first arg must be a variable, got {type(var_expr)}")
            date_str = _resolve_date_string(date_expr, state)
            if date_str not in state.date_index:
                raise ValueError(
                    f"Variable '{var_expr.name}' at date '{date_str}' is None"
                    f" (@elem base date outside state range)"
                )
            return state.get_at_date(var_expr.name, date_str)
        if name == '@date':
            return float(state.current_t)
        if name == '@dateval':
            # @dateval("date_string") -> index
            # If the date is outside the state range (e.g. a pre-sample dummy
            # like @dateval("2005:02") in an @recode adjustment), return a
            # sentinel index (-9999) that can never equal @date, so the
            # @recode condition is always False. This avoids a hard error when
            # equations reference dates before the first observation.
            date_str = _resolve_date_string(expr.args[0], state)
            if date_str not in state.date_index:
                return -9999.0
            return float(state.date_to_index(date_str))
        if name == '@trend':
            # @TREND(start_date) -> number of quarters since start_date.
            # Computed arithmetically so it works even when start_date is
            # before the first date in state (e.g. @TREND('1979Q4')).
            date_str = _resolve_date_string(expr.args[0], state)
            def _q(d: str) -> int:
                return int(d[:4]) * 4 + int(d[5])
            current_q = state.dates[state.current_t]
            return float(_q(current_q) - _q(date_str))
        raise ValueError(f"Unknown @ function: {expr.name}")

    raise ValueError(f"Cannot evaluate AST node: {type(expr).__name__}")


def _evaluate_lagged(expr: Expr, state: ModelState, extra_lag: int) -> float:
    """Evaluate an expression with an additional lag offset."""
    if isinstance(expr, Variable):
        return state.get(expr.name, expr.lag + extra_lag)
    # For complex expressions inside dlog/d, shift current_t temporarily
    saved_t = state.current_t
    state.current_t += extra_lag
    try:
        return evaluate(expr, state)
    finally:
        state.current_t = saved_t


def _resolve_date_string(expr: Expr, state: ModelState) -> str:
    """Extract a date string from a StringLit or evaluate to find one."""
    if isinstance(expr, StringLit):
        # Winsolve dates use "YYYY:QQ" format, convert to "YYYYQQ"
        val = expr.value.replace(':', 'Q')
        return val
    raise ValueError(f"Expected date string, got {type(expr).__name__}")


def solve_equation(eq: ParsedEquation, state: ModelState) -> float:
    """Evaluate an equation and return the value for its LHS variable."""
    rhs_val = evaluate(eq.rhs, state)
    var = eq.lhs_variable

    if eq.lhs_form in (LHSForm.LEVEL, LHSForm.IDENTITY_TAG):
        return rhs_val

    if eq.lhs_form == LHSForm.LOG_LEVEL:
        # log(VAR) = RHS  =>  VAR = exp(RHS)
        # Used for HHTFA and NDIVHH which are defined in log-space.
        return math.exp(rhs_val)

    if eq.lhs_form == LHSForm.RATIO:
        # VAR / VAR(-1) = RHS  =>  VAR = VAR(-1) * RHS
        prev = state.get(var, -1)
        return prev * rhs_val

    if eq.lhs_form == LHSForm.DLOG:
        # dlog(VAR) = RHS  =>  VAR = VAR(-1) * exp(RHS)
        prev = state.get(var, -1)
        return prev * math.exp(rhs_val)

    if eq.lhs_form == LHSForm.D:
        # d(VAR) = RHS  =>  VAR = VAR(-1) + RHS
        prev = state.get(var, -1)
        return prev + rhs_val

    raise ValueError(f"Unknown LHS form: {eq.lhs_form}")
