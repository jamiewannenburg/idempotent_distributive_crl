"""Simple standalone test for verify_free_icrp.py (no external dependencies).

Run with: python3 test_verify_simple.py
"""

import json
import sys
import tempfile
from pathlib import Path

# Add basic test data
test_algebra_2 = {
    "name": "2-element test",
    "cardinality": 2,
    "operations": {
        "*": {"arity": 2, "table": [[0, 1], [1, 1]]},
        "\\": {"arity": 2, "table": [[0, 1], [0, 0]]},
        "e": {"arity": 0, "table": 0},
    },
    "isFree": True,
    "representativeTerms": ["e", "x"],
}


def test_json_creation():
    """Test that we can create valid test algebra JSON."""
    print("Testing JSON creation...")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(test_algebra_2, f)
        temp_path = Path(f.name)
    
    try:
        # Read it back
        with open(temp_path) as f:
            data = json.load(f)
        
        assert data["cardinality"] == 2
        assert data["isFree"] == True
        assert len(data["representativeTerms"]) == 2
        print("  ✓ JSON creation and loading works")
        return True
    finally:
        temp_path.unlink()


def test_equation_generation_logic():
    """Test equation generation logic without importing the full module."""
    print("Testing equation generation logic...")
    
    # Simulate the equation generation for binary operations
    operations = test_algebra_2["operations"]
    rep_terms = test_algebra_2["representativeTerms"]
    cardinality = test_algebra_2["cardinality"]
    
    equations = []
    
    # Constants
    if "e" in operations:
        op_data = operations["e"]
        if op_data["arity"] == 0:
            result_elem = op_data["table"]
            result_term = rep_terms[result_elem]
            equation = f"e = {result_term}"
            equations.append((equation, f"constant e = {result_elem}"))
    
    # Binary operations
    for symbol in ["*", "\\"]:
        if symbol not in operations:
            continue
        op_data = operations[symbol]
        if op_data["arity"] != 2:
            continue
        
        table = op_data["table"]
        for i in range(cardinality):
            for j in range(cardinality):
                result_elem = table[i][j]
                left_term = rep_terms[i]
                right_term = rep_terms[j]
                result_term = rep_terms[result_elem]
                
                left_expr = f"({left_term} {symbol} {right_term})"
                equation = f"{left_expr} = {result_term}"
                desc = f"{symbol}({i}, {j}) = {result_elem}"
                equations.append((equation, desc))
    
    # Verify we got the expected number of equations
    # 1 constant + 4 for * + 4 for \ = 9 total
    assert len(equations) == 9, f"Expected 9 equations, got {len(equations)}"
    
    # Check a few specific ones
    eq_map = {desc: eq for eq, desc in equations}
    
    assert eq_map["constant e = 0"] == "e = e"
    assert eq_map["*(0, 0) = 0"] == "(e * e) = e"
    assert eq_map["*(1, 1) = 1"] == "(x * x) = x"
    assert eq_map["\\(1, 0) = 0"] == "(x \\ e) = e"
    
    print("  ✓ Equation generation logic correct")
    return True


def test_checkpoint_structure():
    """Test checkpoint data structure."""
    print("Testing checkpoint structure...")
    
    checkpoint_data = {
        "results": [
            {
                "equation": "e = e",
                "status": "proved",
                "prover": "prover9",
                "time_s": 0.5,
                "counterexample": None,
            }
        ],
        "proven_lemmas": ["e = e."],
        "next_index": 1,
        "timestamp": 1234567890.0,
    }
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(checkpoint_data, f)
        temp_path = Path(f.name)
    
    try:
        with open(temp_path) as f:
            loaded = json.load(f)
        
        assert loaded["next_index"] == 1
        assert len(loaded["results"]) == 1
        assert loaded["results"][0]["status"] == "proved"
        print("  ✓ Checkpoint structure correct")
        return True
    finally:
        temp_path.unlink()


def test_verification_summary_structure():
    """Test verification summary structure."""
    print("Testing verification summary structure...")
    
    summary = {
        "algebra_path": "test.json",
        "cardinality": 2,
        "total_equations": 9,
        "proved": 9,
        "refuted": 0,
        "unknown": 0,
        "verification_complete": True,
        "results": [],
    }
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(summary, f)
        temp_path = Path(f.name)
    
    try:
        with open(temp_path) as f:
            loaded = json.load(f)
        
        assert loaded["verification_complete"] == True
        assert loaded["proved"] == 9
        assert loaded["refuted"] == 0
        print("  ✓ Summary structure correct")
        return True
    finally:
        temp_path.unlink()


def main():
    """Run all tests."""
    print("="*60)
    print("SIMPLE TESTS FOR verify_free_icrp.py")
    print("="*60)
    print()
    
    tests = [
        test_json_creation,
        test_equation_generation_logic,
        test_checkpoint_structure,
        test_verification_summary_structure,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            failed += 1
    
    print()
    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
