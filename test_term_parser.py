"""Test term parsing and evaluation logic.

Since the term parser is in JavaScript embedded in HTML, we test by:
1. Generating an HTML viewer with a small known algebra
2. Extracting and checking the JS term evaluation logic structure
3. Running a simple Node.js script if available to test the parser
"""

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

from algebra_export import AlgebraExportData
from algebra_viewer import generate_html_viewer


def test_term_parser_structure():
    """Test that the HTML contains the term parsing functions."""
    data = AlgebraExportData(
        name="Test_Free_3",
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
        html_path = Path(tmpdir) / "test.html"
        generate_html_viewer(data, html_path)
        
        content = html_path.read_text()
        
        # Check for essential parsing functions
        assert "function tokenize(" in content
        assert "function parseExpression(" in content
        assert "function parseArrow(" in content
        assert "function parseFusion(" in content
        assert "function parsePrimary(" in content
        assert "function applyOp(" in content
        assert "function evaluateTerm(" in content
        
        # Check for operator handling
        assert "tokens[newPos].value === '\\\\'" in content  # Arrow operator (backslash in JS)
        assert "tokens[newPos].value === '*'" in content
        
        # Check for generator handling
        assert "token.value === 'x'" in content
        assert "algebraData.generatorIndex" in content


def test_term_evaluation_manual():
    """Manually test term evaluation logic.
    
    We create a small algebra and verify the embedded operation tables
    would evaluate correctly.
    """
    # Simple 3-element free algebra: {e, x, x*x}
    # where e is identity-ish, x*x > x > e in the order
    data = AlgebraExportData(
        name="Test_Free_3",
        cardinality=3,
        operations={
            # Fusion: e*a=a, x*x=x*x, x*x*x=x*x
            "*": {"arity": 2, "table": np.array([
                [0, 1, 2],  # e * {e, x, x*x}
                [1, 2, 2],  # x * {e, x, x*x}
                [2, 2, 2],  # x*x * {e, x, x*x}
            ])},
            # Arrow (residual)
            "\\": {"arity": 2, "table": np.array([
                [0, 1, 2],  # e \ {e, x, x*x}
                [0, 1, 2],  # x \ {e, x, x*x}
                [0, 0, 2],  # x*x \ {e, x, x*x}
            ])},
            "e": {"arity": 0, "table": 0},
        },
        is_free=True,
        generator_index=1,  # x is element 1
        representative_terms=["e", "x", "x * x"],
    )
    
    # Manual evaluation tests (what the JS should compute)
    ops = data.operations
    
    # x * x should evaluate to element 2
    x_idx = 1
    result = ops["*"]["table"][x_idx][x_idx]
    assert result == 2
    assert data.representative_terms[result] == "x * x"
    
    # e should evaluate to element 0
    e_idx = ops["e"]["table"]
    assert e_idx == 0
    assert data.representative_terms[e_idx] == "e"
    
    # x \ (x * x) should evaluate to element 2
    x_times_x = ops["*"]["table"][x_idx][x_idx]  # = 2
    x_arrow_result = ops["\\"]["table"][x_idx][x_times_x]  # = 2
    assert x_arrow_result == 2


def create_test_node_script(html_path: Path, test_cases: list[tuple[str, int]]) -> str:
    """Create a Node.js script to test term evaluation.
    
    Args:
        html_path: Path to the HTML file
        test_cases: List of (term_string, expected_element) tuples
    
    Returns:
        Node.js script as a string
    """
    test_js = []
    for term, expected in test_cases:
        term_escaped = term.replace("\\", "\\\\")
        test_js.append(f'''
    try {{
        const result = parseAndEvaluate("{term_escaped}");
        if (result === {expected}) {{
            console.log("PASS: {term_escaped} = " + result);
        }} else {{
            console.log("FAIL: {term_escaped} expected {expected}, got " + result);
            process.exit(1);
        }}
    }} catch (e) {{
        console.log("ERROR: {term_escaped} - " + e.message);
        process.exit(1);
    }}
''')
    
    return f'''
const fs = require('fs');
const {{ JSDOM }} = require('jsdom');

// Load and parse the HTML
const html = fs.readFileSync('{html_path}', 'utf8');
const dom = new JSDOM(html, {{ runScripts: "outside-only" }});
const window = dom.window;
const document = window.document;

// Extract the embedded script and evaluate it
const scripts = document.querySelectorAll('script');
let algebraData = null;
let parseAndEvaluate = null;

for (const script of scripts) {{
    if (script.textContent.includes('algebraData')) {{
        // Evaluate in our context
        eval(script.textContent);
        break;
    }}
}}

if (!algebraData) {{
    console.log("ERROR: algebraData not found");
    process.exit(1);
}}

if (!parseAndEvaluate) {{
    console.log("ERROR: parseAndEvaluate not found");
    process.exit(1);
}}

console.log("Algebra cardinality:", algebraData.cardinality);
console.log("Generator index:", algebraData.generatorIndex);

// Run tests
{''.join(test_js)}

console.log("All tests passed!");
'''


def test_term_evaluation_with_node():
    """Test term evaluation using Node.js if available."""
    # Check if node is available
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            pytest.skip("Node.js not available")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("Node.js not available")
    
    # Check if jsdom is available
    try:
        result = subprocess.run(
            ["node", "-e", "require('jsdom')"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            pytest.skip("jsdom not installed (npm install jsdom)")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("jsdom not available")
    
    # Create test algebra
    data = AlgebraExportData(
        name="Test_Free_3",
        cardinality=3,
        operations={
            "*": {"arity": 2, "table": np.array([
                [0, 1, 2],
                [1, 2, 2],
                [2, 2, 2],
            ])},
            "\\": {"arity": 2, "table": np.array([
                [0, 1, 2],
                [0, 1, 2],
                [0, 0, 2],
            ])},
            "e": {"arity": 0, "table": 0},
        },
        is_free=True,
        generator_index=1,
        representative_terms=["e", "x", "x * x"],
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        html_path = tmpdir / "test.html"
        generate_html_viewer(data, html_path)
        
        # Test cases: (term, expected_element)
        test_cases = [
            ("e", 0),
            ("x", 1),
            ("x * x", 2),
            ("x * e", 1),
            ("e * x", 1),
            ("x \\ x", 1),
            ("x \\ (x * x)", 2),
            ("(x * x) * x", 2),
        ]
        
        script_path = tmpdir / "test.js"
        script_content = create_test_node_script(html_path, test_cases)
        script_path.write_text(script_content)
        
        # Run the Node.js test
        result = subprocess.run(
            ["node", str(script_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        
        assert result.returncode == 0, f"Node.js tests failed:\n{result.stdout}\n{result.stderr}"
        assert "All tests passed!" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
