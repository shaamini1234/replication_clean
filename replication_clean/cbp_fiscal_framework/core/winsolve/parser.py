"""
Winsolve model code parser.

Parses OBR macro model equations from Winsolve syntax into a structured
AST representation. Handles all OBR equation forms: simple identities,
dlog/d behavioral equations, ratio-form LHS, @IDENTITY tags, @recode
conditionals, @elem lookups, @TREND, and @ADD directives.
"""

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Union


# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Number:
    value: float

@dataclass(frozen=True)
class Variable:
    name: str
    lag: int = 0  # 0 = contemporaneous, -1 = one period back, etc.

@dataclass(frozen=True)
class BinOp:
    op: str  # '+', '-', '*', '/', '^'
    left: 'Expr'
    right: 'Expr'

@dataclass(frozen=True)
class UnaryMinus:
    operand: 'Expr'

@dataclass(frozen=True)
class FuncCall:
    name: str  # 'log', 'exp', 'dlog', 'd'
    args: tuple  # tuple of Expr

@dataclass(frozen=True)
class AtFuncCall:
    name: str  # '@recode', '@elem', '@TREND', '@dateval', '@date'
    args: tuple  # tuple of Expr

@dataclass(frozen=True)
class StringLit:
    value: str


Expr = Union[Number, Variable, BinOp, UnaryMinus, FuncCall, AtFuncCall, StringLit]


# ---------------------------------------------------------------------------
# Token types and Lexer
# ---------------------------------------------------------------------------

class TokenType(Enum):
    NUMBER = auto()
    VARIABLE = auto()
    FUNC = auto()       # log, exp, dlog, d
    AT_FUNC = auto()    # @recode, @elem, @TREND, @ADD, @dateval, @date
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    CARET = auto()
    EQUALS = auto()     # = (comparison inside @recode)
    LT = auto()         # <
    GT = auto()         # >
    LE = auto()         # <=
    GE = auto()         # >=
    STRING = auto()
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: str
    pos: int


# Functions recognised by the lexer — longest first to avoid prefix conflicts
_FUNCTIONS = ['dlog', 'log', 'exp']
# 'd' is special: only treat as function if followed by '('


class Lexer:
    """Single-pass character scanner that produces a token stream."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.tokens: List[Token] = []
        self._scan()

    def _scan(self):
        text = self.text
        n = len(text)
        i = 0

        while i < n:
            ch = text[i]

            # Skip whitespace
            if ch in ' \t':
                i += 1
                continue

            # Single-character tokens
            if ch == '(':
                self.tokens.append(Token(TokenType.LPAREN, '(', i))
                i += 1
            elif ch == ')':
                self.tokens.append(Token(TokenType.RPAREN, ')', i))
                i += 1
            elif ch == ',':
                self.tokens.append(Token(TokenType.COMMA, ',', i))
                i += 1
            elif ch == '+':
                self.tokens.append(Token(TokenType.PLUS, '+', i))
                i += 1
            elif ch == '-':
                self.tokens.append(Token(TokenType.MINUS, '-', i))
                i += 1
            elif ch == '*':
                self.tokens.append(Token(TokenType.STAR, '*', i))
                i += 1
            elif ch == '/':
                self.tokens.append(Token(TokenType.SLASH, '/', i))
                i += 1
            elif ch == '^':
                self.tokens.append(Token(TokenType.CARET, '^', i))
                i += 1
            elif ch == '=':
                self.tokens.append(Token(TokenType.EQUALS, '=', i))
                i += 1
            elif ch == '<':
                if i + 1 < n and text[i+1] == '=':
                    self.tokens.append(Token(TokenType.LE, '<=', i))
                    i += 2
                else:
                    self.tokens.append(Token(TokenType.LT, '<', i))
                    i += 1
            elif ch == '>':
                if i + 1 < n and text[i+1] == '=':
                    self.tokens.append(Token(TokenType.GE, '>=', i))
                    i += 2
                else:
                    self.tokens.append(Token(TokenType.GT, '>', i))
                    i += 1

            # String literal
            elif ch == '"':
                j = text.index('"', i + 1)
                self.tokens.append(Token(TokenType.STRING, text[i+1:j], i))
                i = j + 1

            # Number (digits and decimal point), or date-like token (1979Q4)
            elif ch.isdigit() or (ch == '.' and i + 1 < n and text[i+1].isdigit()):
                j = i
                while j < n and (text[j].isdigit() or text[j] == '.'):
                    j += 1
                # Check for date-like tokens: 1979Q4, 1986Q4 etc.
                if j < n and text[j].isalpha():
                    while j < n and (text[j].isalnum() or text[j] == '_'):
                        j += 1
                    self.tokens.append(Token(TokenType.STRING, text[i:j], i))
                else:
                    self.tokens.append(Token(TokenType.NUMBER, text[i:j], i))
                i = j

            # @ function
            elif ch == '@':
                j = i + 1
                while j < n and (text[j].isalnum() or text[j] == '_'):
                    j += 1
                name = text[i:j]
                self.tokens.append(Token(TokenType.AT_FUNC, name, i))
                i = j

            # Identifier (variable or function)
            elif ch.isalpha() or ch == '_':
                j = i
                while j < n and (text[j].isalnum() or text[j] == '_'):
                    j += 1
                word = text[i:j]

                # Check for known functions (longest first)
                matched_func = False
                for func in _FUNCTIONS:
                    if word == func:
                        self.tokens.append(Token(TokenType.FUNC, func, i))
                        matched_func = True
                        break

                if not matched_func:
                    # 'd' is a function only if followed by '('
                    if word == 'd':
                        # Look ahead past whitespace for '('
                        k = j
                        while k < n and text[k] in ' \t':
                            k += 1
                        if k < n and text[k] == '(':
                            self.tokens.append(Token(TokenType.FUNC, 'd', i))
                        else:
                            self.tokens.append(Token(TokenType.VARIABLE, word, i))
                    else:
                        self.tokens.append(Token(TokenType.VARIABLE, word, i))
                i = j
            else:
                raise ValueError(f"Unexpected character '{ch}' at position {i} in: {text}")

        self.tokens.append(Token(TokenType.EOF, '', n))


# ---------------------------------------------------------------------------
# Recursive descent expression parser
# ---------------------------------------------------------------------------

class ExprParser:
    """Parses a token stream into an AST using recursive descent."""

    def __init__(self, tokens: List[Token], source: str = ''):
        self.tokens = tokens
        self.pos = 0
        self.source = source

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, tt: TokenType) -> Token:
        tok = self.advance()
        if tok.type != tt:
            raise ValueError(
                f"Expected {tt.name}, got {tok.type.name} '{tok.value}' "
                f"at pos {tok.pos} in: {self.source}"
            )
        return tok

    _COMPARE_TOKENS = {
        TokenType.EQUALS, TokenType.LT, TokenType.GT,
        TokenType.LE, TokenType.GE,
    }

    def parse(self) -> Expr:
        expr = self.comparison()
        return expr

    # comparison → expr ((= | < | > | <= | >=) expr)?
    def comparison(self) -> Expr:
        left = self.expr()
        if self.peek().type in self._COMPARE_TOKENS:
            op = self.advance().value
            right = self.expr()
            left = BinOp(op, left, right)
        return left

    # expr → term ((+|-) term)*
    def expr(self) -> Expr:
        left = self.term()
        while self.peek().type in (TokenType.PLUS, TokenType.MINUS):
            op = self.advance().value
            right = self.term()
            left = BinOp(op, left, right)
        return left

    # term → power ((*|/) power)*
    def term(self) -> Expr:
        left = self.power()
        while self.peek().type in (TokenType.STAR, TokenType.SLASH):
            op = self.advance().value
            right = self.power()
            left = BinOp(op, left, right)
        return left

    # power → unary (^ unary)?
    def power(self) -> Expr:
        base = self.unary()
        if self.peek().type == TokenType.CARET:
            self.advance()
            exp = self.unary()
            base = BinOp('^', base, exp)
        return base

    # unary → -? call
    def unary(self) -> Expr:
        if self.peek().type == TokenType.MINUS:
            self.advance()
            operand = self.call()
            # Optimise: -Number → Number(-value)
            if isinstance(operand, Number):
                return Number(-operand.value)
            return UnaryMinus(operand)
        return self.call()

    # call → FUNC(args) | AT_FUNC(args) | AT_FUNC (no parens) | atom
    def call(self) -> Expr:
        tok = self.peek()

        if tok.type == TokenType.FUNC:
            name = self.advance().value
            self.expect(TokenType.LPAREN)
            args = self._parse_args()
            self.expect(TokenType.RPAREN)
            return FuncCall(name, tuple(args))

        if tok.type == TokenType.AT_FUNC:
            name = self.advance().value
            # @date has no parentheses — it's a bare reference
            if self.peek().type != TokenType.LPAREN:
                return AtFuncCall(name, ())
            self.expect(TokenType.LPAREN)
            args = self._parse_args()
            self.expect(TokenType.RPAREN)
            return AtFuncCall(name, tuple(args))

        return self.atom()

    def _parse_args(self) -> List[Expr]:
        """Parse comma-separated argument list (may include comparisons)."""
        if self.peek().type == TokenType.RPAREN:
            return []
        args = [self.comparison()]
        while self.peek().type == TokenType.COMMA:
            self.advance()
            args.append(self.comparison())
        return args

    # atom → NUMBER | VARIABLE(lag?) | (expr) | STRING
    def atom(self) -> Expr:
        tok = self.peek()

        if tok.type == TokenType.NUMBER:
            self.advance()
            return Number(float(tok.value))

        if tok.type == TokenType.STRING:
            self.advance()
            return StringLit(tok.value)

        if tok.type == TokenType.VARIABLE:
            self.advance()
            name = tok.value
            # Check for lag: VAR(-n) or VAR(- n)
            if self.peek().type == TokenType.LPAREN:
                lag = self._try_parse_lag()
                if lag is not None:
                    return Variable(name, lag)
            return Variable(name)

        if tok.type == TokenType.LPAREN:
            self.advance()
            inner = self.expr()
            self.expect(TokenType.RPAREN)
            return inner

        raise ValueError(
            f"Unexpected token {tok.type.name} '{tok.value}' "
            f"at pos {tok.pos} in: {self.source}"
        )

    def _try_parse_lag(self) -> Optional[int]:
        """
        Try to parse a lag like (-1), (-2), etc. after a variable name.
        Returns the lag value (negative int) if successful, None if not a lag.
        Restores position if the parenthesised expression is not a lag.
        """
        save = self.pos
        self.advance()  # consume '('

        # Expect '-' then NUMBER then ')'
        if self.peek().type == TokenType.MINUS:
            self.advance()
            if self.peek().type == TokenType.NUMBER:
                num_tok = self.advance()
                if self.peek().type == TokenType.RPAREN:
                    self.advance()
                    return -int(float(num_tok.value))

        # Not a lag — restore position
        self.pos = save
        return None


# ---------------------------------------------------------------------------
# Parsed equation types
# ---------------------------------------------------------------------------

class LHSForm(Enum):
    LEVEL = auto()          # VAR = ...
    DLOG = auto()           # dlog(VAR) = ...
    D = auto()              # d(VAR) = ...
    RATIO = auto()          # VAR / VAR(-1) = ...
    IDENTITY_TAG = auto()   # @IDENTITY VAR = ...
    LOG_LEVEL = auto()      # log(VAR) = ... means VAR = exp(RHS)


@dataclass
class ParsedEquation:
    lhs: Expr
    rhs: Expr
    raw: str
    group: str
    line_number: int
    lhs_form: LHSForm
    lhs_variable: str  # primary variable being defined


@dataclass
class AddFactorDirective:
    variable: str
    add_factor: str
    line_number: int
    group: str


# ---------------------------------------------------------------------------
# Top-level model parser
# ---------------------------------------------------------------------------

class WinsolveParser:
    """Parses a complete Winsolve model file into structured equations."""

    # Pattern for group headers: ' Group N: Name
    _GROUP_RE = re.compile(r"^'\s*Group\s+\d+", re.IGNORECASE)
    # Pattern for section headers: ' SECTION NAME (all-caps or mixed)
    _SECTION_RE = re.compile(r"^'\s*[A-Z][A-Z ,:]+\s*$")

    @classmethod
    def parse_model(cls, text: str) -> List[ParsedEquation]:
        """Parse full model text into a list of ParsedEquation objects."""
        lines = text.split('\n')
        equations: List[ParsedEquation] = []
        add_factors: List[AddFactorDirective] = []
        current_group = ''
        errors: List[str] = []

        for line_num, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()

            # Blank line
            if not line:
                continue

            # Comment line — check for group/section header
            if line.startswith("'"):
                content = line[1:].strip()
                if cls._GROUP_RE.match(line):
                    current_group = content
                elif cls._SECTION_RE.match(line) and len(content) > 3:
                    current_group = content
                continue

            # @ADD directive (no = sign)
            if line.upper().startswith('@ADD'):
                parts = line.split()
                if len(parts) >= 3:
                    add_factors.append(AddFactorDirective(
                        variable=parts[1],
                        add_factor=parts[2],
                        line_number=line_num,
                        group=current_group,
                    ))
                continue

            # Must contain '=' to be an equation
            if '=' not in line:
                continue

            # @IDENTITY prefix
            is_identity = False
            eq_line = line
            if eq_line.upper().startswith('@IDENTITY'):
                is_identity = True
                eq_line = eq_line[len('@IDENTITY'):].strip()

            # Split on first '=' that is the equation separator
            # We need to find the top-level '=' (not inside parentheses)
            eq_idx = cls._find_equals(eq_line)
            if eq_idx is None:
                continue

            lhs_text = eq_line[:eq_idx].strip()
            rhs_text = eq_line[eq_idx+1:].strip()

            if not lhs_text or not rhs_text:
                continue

            try:
                lhs_tokens = Lexer(lhs_text).tokens
                rhs_tokens = Lexer(rhs_text).tokens

                lhs_ast = ExprParser(lhs_tokens, lhs_text).parse()
                rhs_ast = ExprParser(rhs_tokens, rhs_text).parse()

                lhs_form = cls._detect_lhs_form(lhs_ast, is_identity)
                lhs_var = cls._extract_lhs_variable(lhs_ast)

                equations.append(ParsedEquation(
                    lhs=lhs_ast,
                    rhs=rhs_ast,
                    raw=line,
                    group=current_group,
                    line_number=line_num,
                    lhs_form=lhs_form,
                    lhs_variable=lhs_var,
                ))
            except Exception as e:
                errors.append(f"Line {line_num}: {e}\n  → {line}")

        if errors:
            import logging
            logger = logging.getLogger(__name__)
            for err in errors:
                logger.warning("Parse error: %s", err)

        return equations

    @staticmethod
    def _find_equals(text: str) -> Optional[int]:
        """Find the index of the top-level '=' in an equation string."""
        depth = 0
        for i, ch in enumerate(text):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == '=' and depth == 0:
                # Check it's not part of >=, <=
                if i > 0 and text[i-1] in '<>!':
                    continue
                if i + 1 < len(text) and text[i+1] == '=':
                    continue
                return i
        return None

    @staticmethod
    def _detect_lhs_form(lhs: Expr, is_identity: bool) -> LHSForm:
        if is_identity:
            return LHSForm.IDENTITY_TAG
        if isinstance(lhs, FuncCall):
            if lhs.name == 'dlog':
                return LHSForm.DLOG
            if lhs.name == 'd':
                return LHSForm.D
            if lhs.name == 'log':
                # log(VAR) = RHS  means  VAR = exp(RHS)
                # Two OBR equations use this form: HHTFA and NDIVHH.
                return LHSForm.LOG_LEVEL
        if isinstance(lhs, BinOp) and lhs.op == '/':
            return LHSForm.RATIO
        return LHSForm.LEVEL

    @staticmethod
    def _extract_lhs_variable(lhs: Expr) -> str:
        """Extract the primary variable name from the LHS."""
        if isinstance(lhs, Variable):
            return lhs.name
        if isinstance(lhs, FuncCall) and lhs.args:
            # dlog(VAR) or d(VAR)
            inner = lhs.args[0]
            if isinstance(inner, Variable):
                return inner.name
        if isinstance(lhs, BinOp) and lhs.op == '/':
            # VAR / VAR(-1) — take the left side
            if isinstance(lhs.left, Variable):
                return lhs.left.name
        return '?'
