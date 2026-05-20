import pytest

from magma_explorer.magma import satisfies_677
from magma_explorer.query import (
    App,
    EqAtom,
    LogicClause,
    QuantifierCall,
    Var,
    evaluate_all_clauses,
    evaluate_clause,
    parse,
)


def _free_vars(term):
    if isinstance(term, Var):
        return {term.letter}
    return _free_vars(term.left) | _free_vars(term.right)


def _clause(quantifier, op, lhs, rhs, variables=None):
    """Build a single-quantifier-single-equation clause for tests.

    If `variables` is omitted, every free variable in lhs/rhs is bound by
    the given quantifier (in sorted order).
    """
    if variables is None:
        variables = tuple(sorted(_free_vars(lhs) | _free_vars(rhs)))
    return LogicClause(
        chain=(QuantifierCall(quantifier=quantifier, variables=variables),),
        expr=EqAtom(lhs=lhs, op=op, rhs=rhs),
    )


# Term aliases reused below
X = Var("x")
Y = Var("y")
XX = App(X, X)
YX = App(Y, X)
XY = App(X, Y)


def test_size_one_satisfies_all_equations():
    assert evaluate_clause(_clause("all", "=", X, XX), [[0]])


def test_not_idempotent_table_fails_all_idempotent():
    assert not evaluate_clause(_clause("all", "=", X, XX), [[0, 1], [1, 0]])


def test_idempotent_table_satisfies_all_idempotent():
    assert evaluate_clause(_clause("all", "=", X, XX), [[0, 0], [1, 1]])


def test_exists_idempotent():
    assert evaluate_clause(_clause("exists", "=", X, XX), [[0, 1], [1, 1]])


def test_exists_neq_xx_false_when_all_idempotent():
    assert not evaluate_clause(_clause("exists", "!=", X, XX), [[0, 0], [1, 1]])


def test_notall_equiv_exists_neg():
    table = [[0, 1], [1, 0]]
    assert evaluate_clause(_clause("notall", "=", X, XX), table)
    assert evaluate_clause(_clause("exists", "!=", X, XX), table)


def test_notexists_equiv_all_neg():
    table = [[0, 0], [1, 1]]
    assert evaluate_clause(_clause("notexists", "!=", X, XX), table)
    assert evaluate_clause(_clause("all", "=", X, XX), table)


def test_commutative_all_xy_eq_yx():
    assert evaluate_clause(_clause("all", "=", XY, YX), [[0, 1], [1, 0]])


def test_noncommutative_exists_xy_neq_yx():
    assert evaluate_clause(_clause("exists", "!=", XY, YX), [[0, 1], [0, 0]])


def test_evaluate_all_clauses_all_pass():
    table = [[0, 0], [1, 1]]
    c1 = _clause("all", "=", X, XX)
    c2 = _clause("exists", "=", Y, Y)
    assert evaluate_all_clauses((c1, c2), table)


def test_evaluate_all_clauses_one_fails():
    table = [[0, 1], [1, 0]]
    c1 = _clause("all", "=", X, XX)
    c2 = _clause("exists", "=", Y, Y)
    assert not evaluate_all_clauses((c1, c2), table)


def test_eq677_form_for_known_size_one():
    yx = App(Y, X)
    yxy = App(yx, Y)
    inner = App(X, yxy)
    rhs = App(Y, inner)
    c = _clause("all", "=", X, rhs)
    assert evaluate_clause(c, [[0]])


@pytest.mark.parametrize(
    "quantifier,table,expected",
    [
        ("all", [], True),
        ("notexists", [], True),
        ("exists", [], False),
        ("notall", [], False),
    ],
)
def test_empty_domain_vacuous(quantifier, table, expected):
    c = _clause(quantifier, "=", X, XX)
    assert evaluate_clause(c, table) is expected


# --- Cross-validation: parser + evaluator vs. reference oracles ---------

TABLES = [
    ([[0]], "size1", True, True),
    ([[0, 0], [1, 1]], "size2_all_idem", True, True),
    ([[0, 1], [0, 0]], "size2_partial_idem", False, True),
    ([[1, 0], [0, 0]], "size2_zero_idem", False, False),
    ([[0, 1, 2], [0, 1, 2], [0, 1, 2]], "size3_all_idem", True, True),
    ([[1, 2, 0], [2, 0, 1], [0, 1, 2]], "size3_mixed", False, True),
]
TABLE_PARAMS = [pytest.param(t, all_i, any_i, id=name) for t, name, all_i, any_i in TABLES]


def _clause_of(query_str):
    parsed = parse(query_str)
    assert parsed is not None
    return parsed.logic[0]


@pytest.mark.parametrize("table,all_idem,any_idem", TABLE_PARAMS)
def test_quantifier_truth_table_x_eq_xx(table, all_idem, any_idem):
    assert evaluate_clause(_clause_of("all(x):x=xx"), table) is all_idem
    assert evaluate_clause(_clause_of("exists(x):x=xx"), table) is any_idem
    assert evaluate_clause(_clause_of("notall(x):x=xx"), table) is (not all_idem)
    assert evaluate_clause(_clause_of("notexists(x):x=xx"), table) is (not any_idem)

    assert evaluate_clause(_clause_of("all(x):x!=xx"), table) is (not any_idem)
    assert evaluate_clause(_clause_of("exists(x):x!=xx"), table) is (not all_idem)
    assert evaluate_clause(_clause_of("notall(x):x!=xx"), table) is any_idem
    assert evaluate_clause(_clause_of("notexists(x):x!=xx"), table) is all_idem


@pytest.mark.parametrize("table,all_idem,any_idem", TABLE_PARAMS)
def test_swapped_side_form_equivalent(table, all_idem, any_idem):
    for quant in ("all", "exists", "notall", "notexists"):
        for op in ("=", "!="):
            normal = evaluate_clause(_clause_of(f"{quant}(x):x{op}xx"), table)
            swapped = evaluate_clause(_clause_of(f"{quant}(x):xx{op}x"), table)
            assert normal == swapped, f"{quant}(x):x{op}xx vs xx{op}x on {table}"


@pytest.mark.parametrize("table,all_idem,any_idem", TABLE_PARAMS)
def test_de_morgan_equivalences(table, all_idem, any_idem):
    cases = [
        ("notall(x):x=xx", "exists(x):x!=xx"),
        ("notexists(x):x=xx", "all(x):x!=xx"),
        ("notall(x):x!=xx", "exists(x):x=xx"),
        ("notexists(x):x!=xx", "all(x):x=xx"),
    ]
    for a, b in cases:
        va = evaluate_clause(_clause_of(a), table)
        vb = evaluate_clause(_clause_of(b), table)
        assert va == vb, f"{a} = {va} but {b} = {vb} on {table}"


EQ677_TERM = "y(x((yx)y))"


@pytest.mark.parametrize("table,all_idem,any_idem", TABLE_PARAMS)
def test_eq677_cross_check_against_satisfies_677(table, all_idem, any_idem):
    expected = satisfies_677(table)
    assert evaluate_clause(_clause_of(f"all(x,y):x={EQ677_TERM}"), table) is expected
    assert evaluate_clause(_clause_of(f"notexists(x,y):x!={EQ677_TERM}"), table) is expected
    assert evaluate_clause(_clause_of(f"exists(x,y):x!={EQ677_TERM}"), table) is (not expected)
    assert evaluate_clause(_clause_of(f"notall(x,y):x={EQ677_TERM}"), table) is (not expected)


# --- &/| and mixed-quantifier semantics --------------------------------


def test_and_short_circuits_to_false():
    # all(x): x=xx & x!=x  →  False (right side always false)
    assert not evaluate_clause(_clause_of("all(x):x=xx&x!=x"), [[0]])


def test_or_short_circuits_to_true():
    # exists(x): x=x | x!=x  →  True (left always true)
    assert evaluate_clause(_clause_of("exists(x):x=x|x!=x"), [[0]])


def test_and_filters_both_conditions():
    # exists(x,y): x=xx & y!=yy  →  needs SOME (x,y) where both hold.
    # size2_partial_idem t = [[0,1],[0,0]]: x=0 idem, y=1 non-idem.
    table = [[0, 1], [0, 0]]
    assert evaluate_clause(_clause_of("exists(x,y):x=xx&y!=yy"), table)
    # size2_all_idem t = [[0,0],[1,1]] — no non-idem y, so should be False.
    assert not evaluate_clause(_clause_of("exists(x,y):x=xx&y!=yy"), [[0, 0], [1, 1]])


def test_mixed_quantifier_left_identity():
    # `all(x): exists(y): x=yx` — does every x have a left identity partner?
    # Table with 0 acting as left identity (t[0][k] = k): 0,1,2 row 0 = identity
    left_id_table = [[0, 1, 2], [0, 1, 2], [0, 1, 2]]
    assert evaluate_clause(_clause_of("all(x):exists(y):x=yx"), left_id_table)

    # Table without a left identity element. [[1,0],[0,1]]:
    #   x=0: need y so yx=0. row y values at col 0: t[0][0]=1, t[1][0]=0. So y=1 works.
    #   x=1: need y so yx=1. col 1: t[0][1]=0, t[1][1]=1. So y=1 works.
    # Actually 1 acts as left identity here. Use a different table.
    no_left_id_table = [[0, 0], [0, 0]]  # both rows are zero
    # x=0: yx=0 for any y. ✓.  x=1: yx=t[y][1]=0, never 1. ✗.
    assert not evaluate_clause(_clause_of("all(x):exists(y):x=yx"), no_left_id_table)


def test_user_example_one_evaluates():
    # all(x,y): x=yx & y!=(xx)x
    # On any size-1 table [[0]]:
    #   x=y=0: yx=0=x ✓, (xx)x=0, y=0, so y!=(xx)x is 0!=0 = False.
    # So the AND fails for this assignment, and `all` returns False.
    assert not evaluate_clause(_clause_of("all(x,y):x=yx&y!=(xx)x"), [[0]])


def test_user_example_two_evaluates_on_size_one():
    # notexists(x,y): (x!=yy | x!=y) & (xx!=y | ((xx)x)x!=x)
    # On [[0]]:
    #   x=y=0: yy=0, x=0 → x!=yy is False. x!=y is False. (False|False)=False.
    #   AND with anything → False.
    #   So `notexists` = NOT ∃ ... = NOT (False) = True.
    assert evaluate_clause(
        _clause_of("notexists(x,y):(x!=yy|x!=y)&(xx!=y|((xx)x)x!=x)"),
        [[0]],
    )
