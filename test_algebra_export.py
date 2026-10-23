"""Tests for algebra export and viewing functionality."""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
from pyp9m4 import parse_models_from_file

from algebra_export import (
    AlgebraExportData,
    export_to_json,
    export_to_mace4,
    model_to_export_data,
)
from algebra_viewer import (
    compute_order_for_icrp,
    generate_html_viewer,
    load_algebra_from_json,
    load_algebra_from_mace4,
)


def test_model_to_export_data():
    """Test converting a Mace4 model to export data."""
    model_path = Path("model_outputs/rsi_icrp-2_one_generated.model")
    if not model_path.exists():
        pytest.skip(f"Test model not found: {model_path}")
    
    models = list(parse_models_from_file(model_path))
    assert len(models) > 0
    
    model = models[0]
    data = model_to_export_data(model)
    
    assert data.cardinality == 2
    assert "*" in data.operations
    assert "\\" in data.operations
    assert "e" in data.operations


def test_export_import_json():
    """Test round-trip export and import via JSON."""
    # Create simple test algebra (2-element Boolean algebra as iCRP)
    data = AlgebraExportData(
        name="test_2",
        cardinality=2,
        operations={
            "*": {"arity": 2, "table": np.array([[0, 1], [1, 1]])},
            "\\": {"arity": 2, "table": np.array([[0, 1], [0, 0]])},
            "e": {"arity": 0, "table": 0},
        },
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test.json"
        export_to_json(data, json_path)
        
        assert json_path.exists()
        
        # Load back
        loaded = load_algebra_from_json(json_path)
        assert loaded.name == "test_2"
        assert loaded.cardinality == 2
        assert "*" in loaded.operations
        assert "\\" in loaded.operations
        assert "e" in loaded.operations


def test_export_mace4():
    """Test export to Mace4 format."""
    data = AlgebraExportData(
        name="test_2",
        cardinality=2,
        operations={
            "*": {"arity": 2, "table": np.array([[0, 1], [1, 1]])},
            "\\": {"arity": 2, "table": np.array([[0, 1], [0, 0]])},
            "e": {"arity": 0, "table": 0},
        },
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / "test.model"
        export_to_mace4(data, model_path)
        
        assert model_path.exists()
        content = model_path.read_text()
        assert "interpretation(" in content
        assert "function(*(_,_)" in content
        assert "function(\\(_,_)" in content
        assert "function(e," in content


def test_compute_order_for_icrp():
    """Test order computation for iCRP."""
    # Simple 2-element iCRP
    data = AlgebraExportData(
        name="test_2",
        cardinality=2,
        operations={
            "*": {"arity": 2, "table": np.array([[0, 1], [1, 1]])},
            "\\": {"arity": 2, "table": np.array([[0, 1], [0, 0]])},
            "e": {"arity": 0, "table": 0},
        },
    )
    
    leq, covers = compute_order_for_icrp(data)
    
    assert leq.shape == (2, 2)
    assert leq[0, 0]  # reflexive
    assert leq[1, 1]  # reflexive
    assert len(covers) > 0  # Should have at least one cover


def test_generate_html_viewer():
    """Test HTML viewer generation."""
    model_path = Path("model_outputs/rsi_icrp-2_one_generated.model")
    if not model_path.exists():
        pytest.skip(f"Test model not found: {model_path}")
    
    data = load_algebra_from_mace4(model_path)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = Path(tmpdir) / "test.html"
        generate_html_viewer(data, html_path)
        
        assert html_path.exists()
        content = html_path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "algebraData" in content
        assert "Hasse Diagram" in content
        assert "Operation Tables" in content


def test_html_viewer_with_free_algebra():
    """Test HTML viewer generation with free algebra metadata."""
    data = AlgebraExportData(
        name="Free_test",
        cardinality=3,
        operations={
            "*": {"arity": 2, "table": np.array([[0, 1, 2], [1, 1, 2], [2, 2, 2]])},
            "\\": {"arity": 2, "table": np.array([[0, 1, 2], [0, 0, 1], [0, 0, 0]])},
            "e": {"arity": 0, "table": 0},
        },
        is_free=True,
        generator_index=1,
        representative_terms=["e", "x", "x * x"],
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = Path(tmpdir) / "test_free.html"
        generate_html_viewer(data, html_path)
        
        assert html_path.exists()
        content = html_path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "isFree" in content
        assert "generatorIndex" in content
        assert "representativeTerms" in content
        assert "term-eval-section" in content


def test_round_trip_all_formats():
    """Test round-trip through JSON and Mace4 formats."""
    model_path = Path("model_outputs/rsi_icrp-2_one_generated.model")
    if not model_path.exists():
        pytest.skip(f"Test model not found: {model_path}")
    
    # Load from Mace4
    data = load_algebra_from_mace4(model_path)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Export to formats
        json_path = tmpdir / "test.json"
        export_to_json(data, json_path)
        
        model_out_path = tmpdir / "test.model"
        export_to_mace4(data, model_out_path)
        
        # Load back from each format
        data_from_json = load_algebra_from_json(json_path)
        data_from_model = load_algebra_from_mace4(model_out_path)
        
        # Check cardinality matches
        assert data_from_json.cardinality == data.cardinality
        assert data_from_model.cardinality == data.cardinality
        
        # Check operations exist
        for fmt_data in [data_from_json, data_from_model]:
            assert "*" in fmt_data.operations
            assert "\\" in fmt_data.operations


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
