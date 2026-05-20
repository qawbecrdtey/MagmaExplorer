"""Query-language parser and evaluator.

Grammar (v3)::

    query            := clause (';' clause)*
    clause           := size_clause | logic_clause
    size_clause      := 'size=' size_terms
    size_terms       := size_term (',' size_term)*
    size_term        := INT | INT '..' INT
    logic_clause     := quantifier_chain bool_expr
    quantifier_chain := quantifier_call (quantifier_call)*       -- >= 1
    quantifier_call  := quant_name '(' var_list ')' ':'
    quant_name       := 'all' | 'exists' | 'notall' | 'notexists'
    var_list         := variable (',' variable)*                 -- no dups
    variable         := single ASCII letter [a-zA-Z]
    bool_expr        := bool_or
    bool_or          := bool_and ('|' bool_and)*                 -- L-assoc chain
    bool_and         := bool_atom ('&' bool_atom)*               -- L-assoc chain
    bool_atom        := equation | '(' bool_expr ')'
    equation         := term ('=' | '!=') term
    term             := atom | atom ('*' | ε) atom               -- strict binary
    atom             := variable | '(' term ')'
    INT              := positive decimal integer (>= 1)

Whitespace is forbidden anywhere. Empty query → ``None``.

Disambiguation: at any '(' inside a logic-clause body, if the matching ')'
group contains a top-level '&', '|', '=', or '!=', it is a `(bool_expr)`;
otherwise it is a term-grouping paren inside an equation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import product
from typing import Literal

Quantifier = Literal["all", "exists", "notall", "notexists"]
EqOp = Literal["=", "!="]

_QUANTIFIER_NAMES: frozenset[str] = frozenset({"all", "exists", "notall", "notexists"})
_QUANTIFIER_RE = re.compile(r"(all|exists|notall|notexists)\(([a-zA-Z](?:,[a-zA-Z])*)\):")
_TERM_STOP: frozenset[str] = frozenset({")", "=", "!=", "&", "|"})


class QueryParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Var:
    letter: str


@dataclass(frozen=True, slots=True)
class App:
    left: Term
    right: Term


Term = Var | App


@dataclass(frozen=True, slots=True)
class EqAtom:
    lhs: Term
    op: EqOp
    rhs: Term


@dataclass(frozen=True, slots=True)
class BoolAnd:
    left: BoolExpr
    right: BoolExpr


@dataclass(frozen=True, slots=True)
class BoolOr:
    left: BoolExpr
    right: BoolExpr


BoolExpr = EqAtom | BoolAnd | BoolOr


@dataclass(frozen=True, slots=True)
class QuantifierCall:
    quantifier: Quantifier
    variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogicClause:
    chain: tuple[QuantifierCall, ...]
    expr: BoolExpr


@dataclass(frozen=True, slots=True)
class SizeFilter:
    sizes: frozenset[int]

    def matches(self, size: int) -> bool:
        return size in self.sizes


@dataclass(frozen=True, slots=True)
class Query:
    size: SizeFilter | None = None
    logic: tuple[LogicClause, ...] = field(default_factory=tuple)


def parse(query: str) -> Query | None:
    if not query or not query.strip():
        return None

    if any(ch.isspace() for ch in query):
        raise QueryParseError("query must not contain whitespace")

    if query.startswith(";"):
        raise QueryParseError("leading `;` not allowed")
    if query.endswith(";"):
        raise QueryParseError("trailing `;` not allowed")

    clauses = query.split(";")
    if any(c == "" for c in clauses):
        raise QueryParseError("empty clause between semicolons")

    size_filter: SizeFilter | None = None
    logic_clauses: list[LogicClause] = []
    for clause in clauses:
        if clause.startswith("size="):
            if size_filter is not None:
                raise QueryParseError("duplicate `size=` clause")
            size_filter = _parse_size_terms(clause[len("size=") :])
        else:
            logic_clauses.append(_parse_logic_clause(clause))

    return Query(size=size_filter, logic=tuple(logic_clauses))


# --- size clause --------------------------------------------------------


def _parse_size_terms(value: str) -> SizeFilter:
    if not value:
        raise QueryParseError("`size=` requires at least one term")
    if value.startswith(",") or value.endswith(","):
        raise QueryParseError("leading or trailing comma not allowed")

    tokens = value.split(",")
    if any(tok == "" for tok in tokens):
        raise QueryParseError("empty term between commas")

    sizes: set[int] = set()
    for tok in tokens:
        sizes |= _parse_size_token(tok)
    return SizeFilter(frozenset(sizes))


def _parse_size_token(tok: str) -> set[int]:
    if ".." in tok:
        return _parse_size_range(tok)
    return {_parse_size_int(tok)}


def _parse_size_range(tok: str) -> set[int]:
    left, _, right = tok.partition("..")
    if not left or not right:
        raise QueryParseError(f"range {tok!r} must have endpoints on both sides")
    if ".." in right:
        raise QueryParseError(f"range {tok!r} has too many `..` separators")
    a = _parse_size_int(left)
    b = _parse_size_int(right)
    if not a < b:
        raise QueryParseError(
            f"range {tok!r} requires left < right; use a single number for equal endpoints"
        )
    return set(range(a, b + 1))


def _parse_size_int(tok: str) -> int:
    if not tok.isdigit():
        raise QueryParseError(f"invalid integer {tok!r}")
    n = int(tok)
    if n < 1:
        raise QueryParseError(f"size must be >= 1; got {n}")
    return n


# --- logic clause -------------------------------------------------------


def _parse_logic_clause(clause: str) -> LogicClause:
    chain: list[QuantifierCall] = []
    bound: set[str] = set()
    s = clause

    # Reject the old `all:eqn` form clearly.
    short_quant_match = re.match(r"(all|exists|notall|notexists):", s)
    if short_quant_match and not _QUANTIFIER_RE.match(s):
        raise QueryParseError(
            f"quantifier {short_quant_match.group(1)!r} must take a "
            "parenthesized variable list, e.g. `all(x):...`"
        )

    while m := _QUANTIFIER_RE.match(s):
        quant_name = m.group(1)
        vars_list = m.group(2).split(",")
        if len(set(vars_list)) != len(vars_list):
            raise QueryParseError(f"duplicate variable in {m.group(0)!r}")
        for v in vars_list:
            if v in bound:
                raise QueryParseError(f"variable {v!r} bound more than once in quantifier chain")
            bound.add(v)
        chain.append(
            QuantifierCall(
                quantifier=quant_name,  # type: ignore[arg-type]
                variables=tuple(vars_list),
            )
        )
        s = s[m.end() :]

    if not chain:
        # Either no quantifier at all, or malformed (`all():`, `all(1):`, …).
        if s.startswith(("all(", "exists(", "notall(", "notexists(")):
            raise QueryParseError(
                f"malformed quantifier call in {clause!r}; expected `<name>(<letter>(,<letter>)*):`"
            )
        raise QueryParseError(
            f"clause {clause!r} must start with `all(...)`, `exists(...)`, "
            "`notall(...)`, or `notexists(...)`"
        )

    if not s:
        raise QueryParseError("quantifier chain requires a body equation")

    tokens = _tokenize_logic_body(s)
    stream = _TokenStream(tokens)
    expr = _parse_bool_or(stream)
    if not stream.at_end():
        raise QueryParseError(f"unexpected token in body: {stream.peek()!r}")

    free = _collect_vars_in_expr(expr) - bound
    if free:
        raise QueryParseError(
            f"unbound variable(s) in body: {sorted(free)!r}; bind them via the quantifier chain"
        )

    return LogicClause(chain=tuple(chain), expr=expr)


def _tokenize_logic_body(s: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "!":
            if i + 1 >= len(s) or s[i + 1] != "=":
                raise QueryParseError("`!` must be followed by `=`")
            tokens.append("!=")
            i += 2
            continue
        if ch.isascii() and ch.isalpha():
            tokens.append(ch)
            i += 1
            continue
        if ch in "*()=&|":
            tokens.append(ch)
            i += 1
            continue
        raise QueryParseError(f"illegal character {ch!r} in equation body")
    return tokens


class _TokenStream:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self._idx = 0

    def peek(self) -> str | None:
        return self._tokens[self._idx] if self._idx < len(self._tokens) else None

    def advance(self) -> str:
        tok = self._tokens[self._idx]
        self._idx += 1
        return tok

    def at_end(self) -> bool:
        return self._idx >= len(self._tokens)

    def is_bool_paren_group(self) -> bool:
        """At `(`, decide if its matching `)` content contains a top-level
        boolean or equality token. If yes, this `(` opens a `(bool_expr)`;
        otherwise it's a term-grouping paren inside an equation.
        """
        if self.peek() != "(":
            return False
        depth = 0
        for i in range(self._idx, len(self._tokens)):
            tok = self._tokens[i]
            if tok == "(":
                depth += 1
                continue
            if tok == ")":
                depth -= 1
                if depth == 0:
                    return False
                continue
            if depth == 1 and tok in ("&", "|", "=", "!="):
                return True
        return False


def _parse_bool_or(stream: _TokenStream) -> BoolExpr:
    left = _parse_bool_and(stream)
    while stream.peek() == "|":
        stream.advance()
        if stream.at_end() or stream.peek() == ")":
            raise QueryParseError("trailing `|`")
        right = _parse_bool_and(stream)
        left = BoolOr(left=left, right=right)
    return left


def _parse_bool_and(stream: _TokenStream) -> BoolExpr:
    left = _parse_bool_atom(stream)
    while stream.peek() == "&":
        stream.advance()
        if stream.at_end() or stream.peek() == ")":
            raise QueryParseError("trailing `&`")
        right = _parse_bool_atom(stream)
        left = BoolAnd(left=left, right=right)
    return left


def _parse_bool_atom(stream: _TokenStream) -> BoolExpr:
    if stream.is_bool_paren_group():
        stream.advance()  # consume '('
        inner = _parse_bool_or(stream)
        if stream.peek() != ")":
            raise QueryParseError("missing `)`")
        stream.advance()
        return inner
    return _parse_equation_node(stream)


def _parse_equation_node(stream: _TokenStream) -> EqAtom:
    lhs = _parse_term_chain(stream)
    op = stream.peek()
    if op not in ("=", "!="):
        raise QueryParseError(f"expected `=` or `!=` between equation sides, got {op!r}")
    stream.advance()
    if stream.at_end() or stream.peek() == ")":
        raise QueryParseError("equation has empty right-hand side")
    rhs = _parse_term_chain(stream)
    return EqAtom(lhs=lhs, op=op, rhs=rhs)  # type: ignore[arg-type]


def _parse_term_chain(stream: _TokenStream) -> Term:
    left = _parse_atom(stream)
    nxt = stream.peek()
    if nxt is None or nxt in _TERM_STOP:
        return left

    if nxt == "*":
        stream.advance()
        if stream.at_end() or stream.peek() in _TERM_STOP:
            raise QueryParseError("trailing `*`")
        right = _parse_atom(stream)
    elif nxt.isalpha() or nxt == "(":
        right = _parse_atom(stream)
    else:
        raise QueryParseError(f"unexpected token {nxt!r} in term")

    after = stream.peek()
    if after is not None and after not in _TERM_STOP:
        raise QueryParseError(
            "chained juxtaposition/`*` not allowed; use parentheses, e.g. `(ab)c` or `a(bc)`"
        )
    return App(left=left, right=right)


def _parse_atom(stream: _TokenStream) -> Term:
    if stream.at_end():
        raise QueryParseError("unexpected end of term")
    tok = stream.advance()
    if tok.isalpha():
        return Var(letter=tok)
    if tok == "(":
        inner = _parse_term_chain(stream)
        if stream.peek() != ")":
            raise QueryParseError("missing `)`")
        stream.advance()
        return inner
    raise QueryParseError(f"expected variable or `(`, got {tok!r}")


# --- evaluator ----------------------------------------------------------


def evaluate_clause(clause: LogicClause, table: list[list[int]]) -> bool:
    """Evaluate a `LogicClause` against a Cayley table."""
    return _evaluate_chain(clause.chain, clause.expr, table, env={})


def _evaluate_chain(
    chain: tuple[QuantifierCall, ...],
    expr: BoolExpr,
    table: list[list[int]],
    env: dict[str, int],
) -> bool:
    if not chain:
        return _eval_bool_expr(expr, env, table)
    qc, rest = chain[0], chain[1:]
    n = len(table)
    for assignment in product(range(n), repeat=len(qc.variables)):
        new_env = {**env, **dict(zip(qc.variables, assignment, strict=True))}
        holds = _evaluate_chain(rest, expr, table, new_env)
        if qc.quantifier == "all" and not holds:
            return False
        if qc.quantifier == "exists" and holds:
            return True
        if qc.quantifier == "notall" and not holds:
            return True
        if qc.quantifier == "notexists" and holds:
            return False
    return qc.quantifier in ("all", "notexists")


def _eval_bool_expr(expr: BoolExpr, env: dict[str, int], table: list[list[int]]) -> bool:
    if isinstance(expr, EqAtom):
        lhs_val = _eval_term(expr.lhs, env, table)
        rhs_val = _eval_term(expr.rhs, env, table)
        equal = lhs_val == rhs_val
        return equal if expr.op == "=" else not equal
    if isinstance(expr, BoolAnd):
        return _eval_bool_expr(expr.left, env, table) and _eval_bool_expr(expr.right, env, table)
    if isinstance(expr, BoolOr):
        return _eval_bool_expr(expr.left, env, table) or _eval_bool_expr(expr.right, env, table)
    raise TypeError(f"unknown BoolExpr node: {expr!r}")


def evaluate_all_clauses(clauses: tuple[LogicClause, ...], table: list[list[int]]) -> bool:
    return all(evaluate_clause(c, table) for c in clauses)


def _collect_vars(term: Term) -> set[str]:
    if isinstance(term, Var):
        return {term.letter}
    return _collect_vars(term.left) | _collect_vars(term.right)


def _collect_vars_in_expr(expr: BoolExpr) -> set[str]:
    if isinstance(expr, EqAtom):
        return _collect_vars(expr.lhs) | _collect_vars(expr.rhs)
    return _collect_vars_in_expr(expr.left) | _collect_vars_in_expr(expr.right)


def _eval_term(term: Term, env: dict[str, int], table: list[list[int]]) -> int:
    if isinstance(term, Var):
        return env[term.letter]
    a = _eval_term(term.left, env, table)
    b = _eval_term(term.right, env, table)
    return table[a][b]
