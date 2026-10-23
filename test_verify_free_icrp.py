"""Tests for verify_free_icrp.py.

Tests basic functionality with small known algebras and deliberately wrong candidates.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from verify_free_icrp import (
    EquationResult,
    generate_verification_equations,
    load_algebra_from_json,
    save_checkpoint,
    load_checkpoint,
    verify_equation,
)


def create_test_algebra_json(cardinality: int, ops: dict, rep_terms: list[str]) -> dict:
    """Helper to create a test algebra JSON structure."""
    return {
        "name": "Test Algebra",
        "cardinality": cardinality,
        "operations": ops,
        "isFree": True,
        "representativeTerms": rep_terms,
    }


def test_load_algebra_from_json_valid():
    """Test loading a valid free algebra from JSON."""
    # Create a simple 2-element algebra: {e, x}
    algebra_data = create_test_algebra_json(
        cardinality=2,
        ops={
            "*": {"arity": 2, "table": [[0, 1], [1, 1]]},
            "\\": {"arity": 2, "table": [[0, 1], [0, 0]]},
            "e": {"arity": 0, "table": 0},
        },
        rep_terms=["e", "x"],
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(algebra_data, f)
        temp_path = Path(f.name)

    try:
        operations, rep_terms, cardinality = load_algebra_from_json(temp_path)

        assert cardinality == 2
        assert len(rep_terms) == 2
        assert rep_terms == ["e", "x"]
        assert "*" in operations
        assert "\\" in operations
        assert "e" in operations
    finally:
        temp_path.unlink()


def test_load_algebra_from_json_missing_terms():
    """Test that loading algebra without representative terms computes them via BFS."""
    algebra_data = {
        "name": "Test",
        "cardinality": 2,
        "operations": {
            "*": {"arity": 2, "table": [[0, 1], [1, 1]]},
            "\\": {"arity": 2, "table": [[0, 1], [0, 0]]},
            "e": {"arity": 0, "table": 0},
        },
        "generatorIndex": 1,
        # Missing representativeTerms - should compute them
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(algebra_data, f)
        temp_path = Path(f.name)

    try:
        operations, rep_terms, cardinality = load_algebra_from_json(temp_path)
        
        # Should have computed terms via BFS
        assert cardinality == 2
        assert len(rep_terms) == 2
        assert "e" in rep_terms
        assert "x" in rep_terms
    finally:
        temp_path.unlink()


def test_generate_verification_equations_constants():
    """Test equation generation for constants."""
    operations = {
        "e": {"arity": 0, "table": 0},
    }
    rep_terms = ["e", "x"]

    equations = generate_verification_equations(operations, rep_terms, 2)

    assert len(equations) == 1
    eq, desc = equations[0]
    assert eq == "e = e"
    assert "constant" in desc


def test_generate_verification_equations_binary():
    """Test equation generation for binary operations."""
    operations = {
        "*": {"arity": 2, "table": [[0, 1], [1, 1]]},
    }
    rep_terms = ["e", "x"]

    equations = generate_verification_equations(operations, rep_terms, 2)

    # Should have 2x2 = 4 equations for the binary operation
    assert len(equations) == 4

    # Check a few specific equations
    equations_dict = {desc: eq for eq, desc in equations}

    assert "*(0, 0) = 0" in equations_dict
    assert equations_dict["*(0, 0) = 0"] == "(e * e) = e"

    assert "*(0, 1) = 1" in equations_dict
    assert equations_dict["*(0, 1) = 1"] == "(e * x) = x"

    assert "*(1, 1) = 1" in equations_dict
    assert equations_dict["*(1, 1) = 1"] == "(x * x) = x"


def test_generate_verification_equations_arrow():
    """Test equation generation for arrow operation."""
    operations = {
        "\\": {"arity": 2, "table": [[0, 1], [0, 0]]},
    }
    rep_terms = ["e", "x"]

    equations = generate_verification_equations(operations, rep_terms, 2)

    assert len(equations) == 4

    # Check arrow syntax
    equations_dict = {desc: eq for eq, desc in equations}

    assert "\\(0, 0) = 0" in equations_dict
    assert equations_dict["\\(0, 0) = 0"] == "(e \\ e) = e"

    assert "\\(1, 0) = 0" in equations_dict
    assert equations_dict["\\(1, 0) = 0"] == "(x \\ e) = e"


def test_checkpoint_save_load():
    """Test checkpoint saving and loading."""
    results = [
        EquationResult(equation="e = e", status="proved", prover="prover9", time_s=0.5),
        EquationResult(equation="x = x", status="proved", prover="vampire", time_s=1.2),
    ]
    proven_lemmas = ["e = e.", "x = x."]
    next_index = 2

    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_path = Path(tmpdir) / "checkpoint.json"

        # Save checkpoint
        save_checkpoint(checkpoint_path, results, proven_lemmas, next_index)
        assert checkpoint_path.exists()

        # Load checkpoint
        checkpoint = load_checkpoint(checkpoint_path)
        assert checkpoint is not None
        assert len(checkpoint.results) == 2
        assert checkpoint.results[0].equation == "e = e"
        assert checkpoint.results[0].status == "proved"
        assert checkpoint.proven_lemmas == proven_lemmas
        assert checkpoint.next_index == 2


def test_checkpoint_load_nonexistent():
    """Test loading checkpoint that doesn't exist."""
    checkpoint = load_checkpoint(Path("/nonexistent/checkpoint.json"))
    assert checkpoint is None


@pytest.mark.asyncio
async def test_try_prove_equation_uses_prover_outcome():
    """Prover9 success is ProverOutcome.proved, not the string 'success'."""
    from pyp9m4 import Prover9
    from pyp9m4.options import Prover9CliOptions
    from axioms import icrp_axioms
    from verify_free_icrp import try_prove_equation

    axioms = [line.strip() for line in icrp_axioms.strip().split("\n") if line.strip()]
    prover9 = Prover9(
        options=Prover9CliOptions(max_seconds=10),
        timeout_s=10.0,
    )
    proved, name, _elapsed = await try_prove_equation(
        "(x * x) = x", axioms, prover9, [], 10.0
    )
    assert proved is True
    assert name == "prover9"


@pytest.mark.asyncio
async def test_verify_equation_proved_mock():
    """Test verify_equation with mocked prover that succeeds."""
    # Mock provers
    mock_prover9 = MagicMock()
    mock_mace4 = MagicMock()
    
    # Patch the try_prove_equation function to return success
    with patch("verify_free_icrp.try_prove_equation", new_callable=AsyncMock) as mock_prove:
        mock_prove.return_value = (True, "prover9", 0.5)

        result = await verify_equation(
            equation="e = e",
            description="constant e = 0",
            axioms=["x = x."],
            prover9=mock_prover9,
            mace4=mock_mace4,
            tptp_provers=[],
            proof_timeout_s=10.0,
            counterexample_min_size=2,
            counterexample_max_size=5,
            counterexample_timeout_s=10.0,
        )

        assert result.status == "proved"
        assert result.prover == "prover9"
        assert result.time_s == 0.5
        assert result.counterexample is None


@pytest.mark.asyncio
async def test_verify_equation_refuted_mock():
    """Test verify_equation with mocked counterexample."""
    mock_prover9 = MagicMock()
    mock_mace4 = MagicMock()

    # Mock proof failure and counterexample found
    with patch("verify_free_icrp.try_prove_equation", new_callable=AsyncMock) as mock_prove, \
         patch("verify_free_icrp.search_counterexample", new_callable=AsyncMock) as mock_counter:
        
        mock_prove.return_value = (False, None, 1.0)
        mock_counter.return_value = (True, "interpretation(...)")

        result = await verify_equation(
            equation="x * x = e",  # Wrong equation
            description="wrong equation",
            axioms=["x = x."],
            prover9=mock_prover9,
            mace4=mock_mace4,
            tptp_provers=[],
            proof_timeout_s=10.0,
            counterexample_min_size=2,
            counterexample_max_size=5,
            counterexample_timeout_s=10.0,
        )

        assert result.status == "refuted"
        assert result.counterexample == "interpretation(...)"


@pytest.mark.asyncio
async def test_verify_equation_unknown_mock():
    """Test verify_equation when neither proof nor counterexample is found."""
    mock_prover9 = MagicMock()
    mock_mace4 = MagicMock()

    # Mock both proof and counterexample failures
    with patch("verify_free_icrp.try_prove_equation", new_callable=AsyncMock) as mock_prove, \
         patch("verify_free_icrp.search_counterexample", new_callable=AsyncMock) as mock_counter:
        
        mock_prove.return_value = (False, None, 5.0)
        mock_counter.return_value = (False, None)

        result = await verify_equation(
            equation="(x \\ e) * x = x",  # Hard equation
            description="difficult equation",
            axioms=["x = x."],
            prover9=mock_prover9,
            mace4=mock_mace4,
            tptp_provers=[],
            proof_timeout_s=10.0,
            counterexample_min_size=2,
            counterexample_max_size=5,
            counterexample_timeout_s=10.0,
        )

        assert result.status == "unknown"
        assert result.counterexample is None


def test_generate_equations_full_algebra():
    """Test equation generation for a complete small algebra."""
    # 3-element algebra
    operations = {
        "*": {"arity": 2, "table": [[0, 1, 2], [1, 1, 2], [2, 2, 2]]},
        "\\": {"arity": 2, "table": [[0, 1, 2], [0, 0, 2], [0, 0, 0]]},
        "e": {"arity": 0, "table": 0},
    }
    rep_terms = ["e", "x", "x * x"]

    equations = generate_verification_equations(operations, rep_terms, 3)

    # Should have: 1 constant + 3*3 binary ops * 2 = 1 + 18 = 19 equations
    assert len(equations) == 1 + 9 + 9
    assert len(equations) == 19


@pytest.mark.skipif(
    not Path("model_outputs/rsi_icrp-2_one_generated.model").exists(),
    reason="Test model file not available"
)
def test_load_real_model_file():
    """Test loading a real model file (if available).
    
    This test is skipped if the model file doesn't exist.
    Now computes representative terms via BFS if not in comments.
    """
    from verify_free_icrp import load_algebra_from_model

    model_path = Path("model_outputs/rsi_icrp-2_one_generated.model")
    
    # Should successfully load and compute terms via BFS
    operations, rep_terms, cardinality = load_algebra_from_model(model_path)
    
    assert cardinality > 0
    assert len(rep_terms) == cardinality
    assert "e" in rep_terms or "elem_0" in rep_terms[0]  # Either e or computed elem_N


def test_generate_equations_respects_term_order():
    """Test that generated equations use the correct representative terms."""
    operations = {
        "*": {"arity": 2, "table": [[0, 1], [1, 0]]},  # Unusual table
    }
    rep_terms = ["e", "x"]

    equations = generate_verification_equations(operations, rep_terms, 2)
    equations_dict = {desc: eq for eq, desc in equations}

    # Check that table[1,1] = 0 gives equation (x * x) = e
    assert "*(1, 1) = 0" in equations_dict
    assert equations_dict["*(1, 1) = 0"] == "(x * x) = e"


if __name__ == "__main__":
    # Run with: python -m pytest test_verify_free_icrp.py -v
    pytest.main([__file__, "-v"])
