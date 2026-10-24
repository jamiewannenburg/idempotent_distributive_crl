"""Generate example HTML viewers from algebras in the repository."""

import sys
from pathlib import Path

from algebra_viewer import (
    generate_html_viewer,
    load_algebra_from_mace4,
)


def main():
    """Generate example HTML files."""
    examples_dir = Path("examples")
    examples_dir.mkdir(exist_ok=True)
    
    # Example 1: Small iCRP from Mace4
    model_path = Path("model_outputs/rsi_icrp-2_one_generated.model")
    if model_path.exists():
        print(f"Generating example from {model_path}...")
        try:
            data = load_algebra_from_mace4(model_path)
            html_path = examples_dir / "rsi_icrp-2_one_generated.html"
            generate_html_viewer(data, html_path, title="RSI iCRP (2 elements, 1-generated)")
            print(f"  ✓ Generated: {html_path}")
        except Exception as e:
            print(f"  ✗ Error: {e}", file=sys.stderr)
    
    # Example 2: Another small iCRP
    model_path = Path("model_outputs/rsi_icrp-3_one_generated.model")
    if model_path.exists():
        print(f"Generating example from {model_path}...")
        try:
            data = load_algebra_from_mace4(model_path)
            html_path = examples_dir / "rsi_icrp-3_one_generated.html"
            generate_html_viewer(data, html_path, title="RSI iCRP (3 elements, 1-generated)")
            print(f"  ✓ Generated: {html_path}")
        except Exception as e:
            print(f"  ✗ Error: {e}", file=sys.stderr)
    
    # Example 3: Larger algebra if available
    model_path = Path("model_outputs/rsi_icrp-5_one_generated.model")
    if model_path.exists():
        print(f"Generating example from {model_path}...")
        try:
            data = load_algebra_from_mace4(model_path)
            html_path = examples_dir / "rsi_icrp-5_one_generated.html"
            generate_html_viewer(data, html_path, title="RSI iCRP (5 elements, 1-generated)")
            print(f"  ✓ Generated: {html_path}")
        except Exception as e:
            print(f"  ✗ Error: {e}", file=sys.stderr)
    
    # Check for free algebra output (if it exists)
    free_json = Path("output/free_icrp.json")
    if free_json.exists():
        print(f"Generating free algebra example from {free_json}...")
        try:
            from algebra_viewer import load_algebra_from_json
            data = load_algebra_from_json(free_json)
            html_path = examples_dir / "free_icrp.html"
            generate_html_viewer(data, html_path, title="Free 1-generated iCRP")
            print(f"  ✓ Generated: {html_path}")
            print(f"     Cardinality: {data.cardinality}")
            if data.is_free:
                print(f"     Free algebra with generator at index {data.generator_index}")
        except Exception as e:
            print(f"  ✗ Error: {e}", file=sys.stderr)
    
    print(f"\nExample HTML files saved to {examples_dir}/")


if __name__ == "__main__":
    main()
