"""Regression: classify_term_order must return True when the algebra closes.

A prior bug placed ``return False`` inside the ``finally`` of classify_term_order,
which overrode the ``return True`` from the closed-level path (Python semantics:
a return in finally replaces any try return value).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from free_algebra import (
    Operation,
    OperationType,
    TermPartialOrder,
    classify_term_order,
)


MODELS = Path("model_outputs/rsi_icrp_one_generated.model")


@pytest.mark.skipif(not MODELS.is_file(), reason="RSI model file not available")
def test_classify_term_order_returns_true_when_closed():
    """Closed run (297 elements by level 9) must return True, not False."""
    operations = [
        Operation(2, OperationType.INFIX, "*", commutative=True, idempotent=True),
        Operation(2, OperationType.INFIX, "\\"),
        Operation(0, OperationType.PREFIX, "e"),
    ]
    order = TermPartialOrder()

    closed = asyncio.run(
        classify_term_order(
            operations,
            ["x"],
            max_level=10,
            axioms=[],
            equivalence_classes=order,
            mace4=None,
            prover9=None,
            save_axiom=lambda _f: None,
            save_unknown=lambda _f: None,
            progress=False,
            algebras=MODELS,
        )
    )

    assert closed is True
    assert len(order.representatives()) == 297


@pytest.mark.skipif(not MODELS.is_file(), reason="RSI model file not available")
def test_classify_term_order_returns_false_before_closure():
    """Stopping before the closed level must return False."""
    operations = [
        Operation(2, OperationType.INFIX, "*", commutative=True, idempotent=True),
        Operation(2, OperationType.INFIX, "\\"),
        Operation(0, OperationType.PREFIX, "e"),
    ]
    order = TermPartialOrder()

    closed = asyncio.run(
        classify_term_order(
            operations,
            ["x"],
            max_level=3,
            axioms=[],
            equivalence_classes=order,
            mace4=None,
            prover9=None,
            save_axiom=lambda _f: None,
            save_unknown=lambda _f: None,
            progress=False,
            algebras=MODELS,
        )
    )

    assert closed is False
    assert len(order.representatives()) < 297
