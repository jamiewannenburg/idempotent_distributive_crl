"""Tests for term_congruence.py and the TPTP <= predicate fix."""

import pytest

from term_congruence import CongruenceClosure, TermParseError, parse_formula


def test_parse_formula():
    rel, lhs, rhs = parse_formula(r"((x \ e) * x) <= (x \ x).")
    assert rel == "<="
    assert lhs == ("*", ("\\", ("x",), ("e",)), ("x",))
    assert rhs == ("\\", ("x",), ("x",))
    with pytest.raises(TermParseError):
        parse_formula(r"x \ e * x = x.")  # not fully parenthesised


def test_congruence_and_instances():
    cc = CongruenceClosure()
    cc.add_formula(r"(x \ e) = ((x \ x) \ e).")
    # congruence: substitute inside a larger term
    assert cc.equation_holds(r"((x \ e) \ x) = (((x \ x) \ e) \ x)")
    # commutativity / unit / idempotence instances of *
    assert cc.equation_holds(r"(x * (x \ e)) = ((x \ e) * x)")
    assert cc.equation_holds(r"(e * (x \ x)) = (x \ x)")
    assert cc.equation_holds(r"((x \ e) * (x \ e)) = (x \ e)")
    assert not cc.equation_holds(r"(x \ e) = x")


def test_order_cycle_collapses():
    cc = CongruenceClosure()
    cc.add_formula(r"x <= (x \ x).")
    cc.add_formula(r"(x \ x) <= ((x \ e) \ e).")
    cc.add_formula(r"((x \ e) \ e) <= x.")
    assert not cc.equation_holds(r"x = (x \ x)")
    assert cc.saturate_order() > 0
    assert cc.equation_holds(r"x = (x \ x)")


def test_tptp_le_predicate_does_not_collide_with_arrow():
    from tptp_provers import _le_predicate_name, replace_infix_le

    text = (
        "%   (arity 2)        *    tptp0\n"
        "%   (arity 2)        \\    tptp1\n"
        "%   (arity 2)       <=    tptp2\n"
        "fof(a,axiom,! [X] : (X <= tptp1(X,X))).\n"
    )
    pred = _le_predicate_name(text)
    assert pred == "tptp2"
    out = replace_infix_le(text, pred)
    assert "tptp2(X,tptp1(X,X))" in out
    assert "%   (arity 2)       <=    tptp2" in out  # comments untouched
