import pytest

from magma_explorer.query import (
    App,
    BoolAnd,
    BoolOr,
    EqAtom,
    QuantifierCall,
    Query,
    QueryParseError,
    SizeFilter,
    Var,
    parse,
)

# --- size queries -------------------------------------------------------


def test_empty_query_returns_none():
    assert parse("") is None
    assert parse("   ") is None


def test_single_size():
    q = parse("size=5")
    assert isinstance(q, Query)
    assert q.size == SizeFilter(frozenset({5}))
    assert q.logic == ()


def test_multiple_sizes():
    assert parse("size=1,2,3").size.sizes == frozenset({1, 2, 3})


def test_simple_range():
    assert parse("size=5..7").size.sizes == frozenset({5, 6, 7})


def test_mixed_terms():
    expected = frozenset({1, 5, 6, 7, 11, *range(100, 111)})
    assert parse("size=1,5..7,11,100..110").size.sizes == expected


def test_deduplication():
    assert parse("size=5,5,5..6").size.sizes == frozenset({5, 6})


def test_filter_matches():
    f = parse("size=5..7").size
    assert f.matches(5)
    assert f.matches(6)
    assert f.matches(7)
    assert not f.matches(4)
    assert not f.matches(8)


@pytest.mark.parametrize(
    "query",
    [
        "size=,1,2",
        "size=1,2,",
        "size=1,,2",
        "size=5..5",
        "size=7..5",
        "size=..5",
        "size=5..",
        "size=1..2..3",
        "size=-5",
        "size=+5",
        "size=0",
        "size= 1",
        "size=1 2",
        "size=1.5",
        "size=abc",
        "size=",
        "rank=5",
        "5",
    ],
)
def test_invalid_size_queries(query):
    with pytest.raises(QueryParseError):
        parse(query)


# --- logic queries: quantifier chains ----------------------------------


def test_simple_all_equation():
    q = parse("all(x):x=x")
    assert q.size is None
    assert len(q.logic) == 1
    c = q.logic[0]
    assert c.chain == (QuantifierCall(quantifier="all", variables=("x",)),)
    assert c.expr == EqAtom(lhs=Var("x"), op="=", rhs=Var("x"))


def test_exists_with_neq():
    c = parse("exists(a,b):a!=b").logic[0]
    assert c.chain == (QuantifierCall(quantifier="exists", variables=("a", "b")),)
    assert c.expr == EqAtom(lhs=Var("a"), op="!=", rhs=Var("b"))


@pytest.mark.parametrize("quant", ["all", "exists", "notall", "notexists"])
def test_all_quantifier_names(quant):
    c = parse(f"{quant}(x):x=x").logic[0]
    assert c.chain[0].quantifier == quant


def test_multi_variable_in_one_call():
    c = parse("all(x,y):x=y").logic[0]
    assert c.chain == (QuantifierCall(quantifier="all", variables=("x", "y")),)


def test_chained_quantifiers():
    c = parse("all(x):exists(y):x=y").logic[0]
    assert c.chain == (
        QuantifierCall(quantifier="all", variables=("x",)),
        QuantifierCall(quantifier="exists", variables=("y",)),
    )
    assert c.expr == EqAtom(lhs=Var("x"), op="=", rhs=Var("y"))


def test_three_chained_quantifiers():
    c = parse("all(x):exists(y):notall(z):x=yz").logic[0]
    assert tuple(qc.quantifier for qc in c.chain) == ("all", "exists", "notall")


# --- term grammar (unchanged from v2) -----------------------------------


def test_juxtaposition():
    c = parse("all(x):x=xx").logic[0]
    assert c.expr.rhs == App(Var("x"), Var("x"))


def test_juxtaposition_vs_explicit_star_equivalent():
    a = parse("all(x):x=xx").logic[0].expr.rhs
    b = parse("all(x):x=x*x").logic[0].expr.rhs
    assert a == b


def test_paren_grouping_left():
    rhs = parse("all(a,b,c,y):y=(ab)c").logic[0].expr.rhs
    assert rhs == App(App(Var("a"), Var("b")), Var("c"))


def test_paren_grouping_right():
    rhs = parse("all(a,b,c,y):y=a(bc)").logic[0].expr.rhs
    assert rhs == App(Var("a"), App(Var("b"), Var("c")))


def test_paren_groupings_differ():
    left = parse("all(a,b,c,y):y=(ab)c").logic[0].expr.rhs
    right = parse("all(a,b,c,y):y=a(bc)").logic[0].expr.rhs
    assert left != right


def test_two_paren_groups_juxtaposed():
    rhs = parse("all(a,b,c,d,y):y=(ab)(cd)").logic[0].expr.rhs
    assert rhs == App(App(Var("a"), Var("b")), App(Var("c"), Var("d")))


def test_parens_change_associativity():
    rhs = parse("all(x,y):y=x(xx)").logic[0].expr.rhs
    assert rhs == App(Var("x"), App(Var("x"), Var("x")))


def test_complex_nested_parens():
    rhs = parse("all(x,y):y=((xx)x)x").logic[0].expr.rhs
    assert rhs == App(App(App(Var("x"), Var("x")), Var("x")), Var("x"))


@pytest.mark.parametrize(
    "query",
    [
        "all(x,y):y=abc",  # chained letters → must use parens
        "all(x,y):y=a(bc)d",  # mixed chain
        "all(x,y):y=(ab)cd",  # chain after paren group
        "all(x,y):y=ab(cd)",  # chain before paren group
        "all(x,y,z):y=x*y*z",  # chained *
    ],
)
def test_chained_juxtaposition_rejected(query):
    with pytest.raises(QueryParseError):
        parse(query)


# --- boolean composition: & and | -------------------------------------


def test_simple_and():
    c = parse("all(x,y):x=y&y=x").logic[0]
    assert c.expr == BoolAnd(
        EqAtom(Var("x"), "=", Var("y")),
        EqAtom(Var("y"), "=", Var("x")),
    )


def test_simple_or():
    c = parse("all(x,y):x=y|y=x").logic[0]
    assert c.expr == BoolOr(
        EqAtom(Var("x"), "=", Var("y")),
        EqAtom(Var("y"), "=", Var("x")),
    )


def test_and_binds_tighter_than_or():
    # x=y | z=w & u=v  →  (x=y) | ((z=w) & (u=v))
    c = parse("all(u,v,w,x,y,z):x=y|z=w&u=v").logic[0]
    assert c.expr == BoolOr(
        EqAtom(Var("x"), "=", Var("y")),
        BoolAnd(
            EqAtom(Var("z"), "=", Var("w")),
            EqAtom(Var("u"), "=", Var("v")),
        ),
    )


def test_and_chain_left_associative():
    # a=a & b=b & c=c  →  ((a=a) & (b=b)) & (c=c)
    c = parse("all(a,b,c):a=a&b=b&c=c").logic[0]
    assert c.expr == BoolAnd(
        BoolAnd(
            EqAtom(Var("a"), "=", Var("a")),
            EqAtom(Var("b"), "=", Var("b")),
        ),
        EqAtom(Var("c"), "=", Var("c")),
    )


def test_or_chain_left_associative():
    c = parse("all(a,b,c):a=a|b=b|c=c").logic[0]
    assert c.expr == BoolOr(
        BoolOr(
            EqAtom(Var("a"), "=", Var("a")),
            EqAtom(Var("b"), "=", Var("b")),
        ),
        EqAtom(Var("c"), "=", Var("c")),
    )


def test_paren_overrides_precedence():
    # (x=y | z=w) & u=v  →  bool group, then AND
    c = parse("all(u,v,w,x,y,z):(x=y|z=w)&u=v").logic[0]
    assert c.expr == BoolAnd(
        BoolOr(
            EqAtom(Var("x"), "=", Var("y")),
            EqAtom(Var("z"), "=", Var("w")),
        ),
        EqAtom(Var("u"), "=", Var("v")),
    )


def test_paren_disambiguation_term_vs_bool():
    # (xy)=z  →  term parens
    c1 = parse("all(x,y,z):(xy)=z").logic[0]
    assert c1.expr == EqAtom(App(Var("x"), Var("y")), "=", Var("z"))
    # (x=y)&z=w  →  bool parens (redundant but legal)
    c2 = parse("all(w,x,y,z):(x=y)&z=w").logic[0]
    assert c2.expr == BoolAnd(
        EqAtom(Var("x"), "=", Var("y")),
        EqAtom(Var("z"), "=", Var("w")),
    )


# --- user-supplied sample queries ---------------------------------------


def test_user_example_one():
    c = parse("all(x,y):x=yx&y!=(xx)x").logic[0]
    assert c.chain == (QuantifierCall(quantifier="all", variables=("x", "y")),)
    yx = App(Var("y"), Var("x"))
    xxx = App(App(Var("x"), Var("x")), Var("x"))
    assert c.expr == BoolAnd(
        EqAtom(Var("x"), "=", yx),
        EqAtom(Var("y"), "!=", xxx),
    )


def test_user_example_two():
    c = parse("notexists(x,y):(x!=yy|x!=y)&(xx!=y|((xx)x)x!=x)").logic[0]
    assert c.chain == (QuantifierCall(quantifier="notexists", variables=("x", "y")),)
    yy = App(Var("y"), Var("y"))
    xx = App(Var("x"), Var("x"))
    xxxx = App(App(App(Var("x"), Var("x")), Var("x")), Var("x"))
    assert c.expr == BoolAnd(
        BoolOr(
            EqAtom(Var("x"), "!=", yy),
            EqAtom(Var("x"), "!=", Var("y")),
        ),
        BoolOr(
            EqAtom(xx, "!=", Var("y")),
            EqAtom(xxxx, "!=", Var("x")),
        ),
    )


# --- combination with size= ---------------------------------------------


def test_size_and_logic_combined():
    q = parse("size=5;all(x):x=xx")
    assert q.size.sizes == frozenset({5})
    assert len(q.logic) == 1
    assert q.logic[0].chain[0].quantifier == "all"


def test_multiple_logic_clauses():
    q = parse("all(x):x=xx;exists(a,b):a!=b")
    assert q.size is None
    assert len(q.logic) == 2
    assert q.logic[0].chain[0].quantifier == "all"
    assert q.logic[1].chain[0].quantifier == "exists"


# --- error cases --------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        # missing-parens / old syntax
        "all:x=x",
        "exists:x=x",
        "notall:x=x",
        "notexists:x=x",
        # malformed quantifier
        "all(x:x=x",  # missing closing )
        "all():x=x",  # empty var list
        "all(x,):x=x",  # trailing comma
        "all(,x):x=x",  # leading comma
        "all(1):x=x",  # digit var
        "all(x_y):x=x",  # underscore in var
        "all(xy):xy=xy",  # multi-letter ident (not allowed)
        # duplicate vars
        "all(x,x):x=x",
        "all(x):all(x):x=x",
        "all(x):exists(x):x=x",
        # unbound vars
        "all(x):y=y",
        "all(x):x=y",
        "exists(a):b=c",
        # missing quantifier
        "x=y",
        ":x=y",
        # incomplete body
        "all(x):",
        "all(x):&x=x",
        "all(x):x=x&",
        "all(x):|x=x",
        "all(x):x=x|",
        "all(x):x=",
        "all(x):=x",
        "all(x,y):x=&y=y",
        # malformed bool grouping
        "all(x):(x=x",
        "all(x):x=x)",
        # ill-formed equation
        "all(x):x",  # missing equality
        "all(x):x==x",  # double = is illegal (= then another =)
        # combination errors
        "size=5;all:x=x",
        "size=5;size=6",
        "all(x):x=x;",
        ";all(x):x=x",
        "all(x):x=x;;exists(a):a=a",
        # illegal characters in body
        "all(x):x=x+x",
        "all(x):x=x-x",
        "all(x):x=x1",
        "all(x):x_y=x_y",
    ],
)
def test_invalid_logic_queries(query):
    with pytest.raises(QueryParseError):
        parse(query)
