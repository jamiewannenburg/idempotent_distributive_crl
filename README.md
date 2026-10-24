Investigating idemopotent distributive commutative residuated lattices
--------------

Create a virtual environment in this folder and activate it:

**On Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

**On Linux/Mac:**
```bash
python -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
# Install pyp9m4 directly from git repository (object oriented version)
pip install matplotlib
pip install networkx
pip install "pyp9m4 @ git+https://github.com/jamiewannenburg/pyp9m4.git@oo"
```

Open `simple_idempotent_distributive_crl.in` with Prover9/mace4 and run mace4.
This generates simple IDCRLs with up to 7 elements. Filter out isomorphic copies. Save the result to `simple_idempotent_distributive_crl.model`.

Then run `python draw_orders.py`.

## Algebra Viewer: Interactive HTML Visualization

The repository includes tools to export and visualize algebras as standalone, self-contained HTML files. These HTML files work offline and can be shared via email.

### Exporting Algebras

The `free_icrp.py` script now automatically exports the computed free algebra in two formats:

- **Mace4 format** (`.model`): Prover9/Mace4 interpretation format
- **Common JSON format** (`.json`): Includes algebra structure, order information, layout positions, and free-algebra metadata

Example:
```bash
python free_icrp.py --max-level 2 -o output/free_icrp.pdf
# Also creates: output/free_icrp.model, output/free_icrp.json
```

### Generating HTML Viewers

Use `algebra_viewer.py` to create interactive HTML visualizations from any supported format:

```bash
python algebra_viewer.py <input-file> -o <output.html>

# Examples:
python algebra_viewer.py model_outputs/rsi_icrp-3_one_generated.model -o viewer.html
python algebra_viewer.py output/free_icrp.json -o free_viewer.html
```

Supported input formats: `.model` (Mace4), `.json` (common format)

### HTML Viewer Features

The generated HTML viewers include:

1. **Interactive Hasse Diagram**
   - Zoomable and pannable (mouse wheel, drag, or +/- buttons)
   - Computed using the existing Python `hasse_layout` algorithm for consistency with PDFs
   - The order displayed depends on the algebra type:
     - For iCRPs: the partial order defined from the arrow operation `(x \\ y) = (x \\ y) \\ (x \\ y)`
     - For CRLs: the lattice order from the meet operation
   - Click nodes to highlight them throughout the viewer

2. **Operation Tables**
   - Binary operations shown as Cayley tables
   - Unary operations and constants displayed appropriately
   - Tables virtualized for large algebras (>50 elements show a placeholder)
   - Highlighting: when an element is selected, all occurrences in tables are highlighted

3. **Element Search**
   - Enter an element number to highlight it in the diagram and tables

4. **Free Algebra Term Evaluation** (when viewing free algebras)
   - Hover over nodes in the Hasse diagram to see their representative terms
   - **Term Search Box**: Enter terms using Mace4/Prover9 syntax to evaluate them:
     - `x` : the generator
     - `e` : the identity constant
     - `*` : fusion (binary operation, left-associative, higher precedence)
     - `\\` : arrow/residual (binary operation, left-associative, lower precedence)
     - Parentheses for grouping: `(x * x) \\ e`
   - **Operator Precedence**: `*` (fusion) has higher precedence than `\\` (arrow), both left-associative
   - Examples: `x * x`, `x \\ e`, `(x \\ e) * x`, `x \\ (x \\ e)`
   - The evaluator computes the result using the algebra's operation tables and displays both the element number and its representative term

5. **Self-Contained**
   - All JavaScript, CSS, and data embedded in a single HTML file
   - No external dependencies, CDN, or server required
   - Works offline and can be opened in any modern browser

### Generating Examples

Run `generate_examples.py` to create HTML viewers for sample algebras in the repository:

```bash
python generate_examples.py
# Creates HTML files in examples/ directory
```

### Common JSON Format

The JSON format stores:
```json
{
  "name": "Algebra name",
  "cardinality": 5,
  "operations": {
    "*": {"arity": 2, "table": [[0,1,...], ...]},
    "\\": {"arity": 2, "table": [[0,1,...], ...]},
    "e": {"arity": 0, "table": 0}
  },
  "orderType": "icrp",
  "orderRelation": [[true, false, ...], ...],
  "orderCovers": [[0,1], [1,2], ...],
  "isFree": true,
  "generatorIndex": 1,
  "representativeTerms": ["e", "x", "x * x", ...],
  "layoutPositions": {"0": [0.0, 0.0], "1": [0.75, 1.0], ...}
}
```

### Tests

Run the test suite:
```bash
pip install pytest
python -m pytest test_algebra_export.py -v   # Export/import tests
python -m pytest test_term_parser.py -v      # Term parser tests (requires Node.js + jsdom)
```

## Verifying candidate free algebras

`verify_free_icrp.py` verifies that a candidate free 1-generated iCRP (computed by `free_icrp.py`) is actually free by proving all operation table equations from the iCRP axioms.

### Why verification is cheaper than enumeration

The standard approach (`free_icrp.py`) enumerates terms level-by-level and uses Prover9/Mace4 to decide equalities. For the free 1-generated iCRP, this is expensive. Once a candidate is computed, we can verify it more efficiently:

1. **Closure is automatic**: The candidate is constructed by term generation, so closure under operations is guaranteed.
2. **Only table equations need proving**: For each operation table entry (e.g., `a * b = c`), we prove `rep(a) * rep(b) = rep(a*b)` from the iCRP axioms.
3. **Lemma reuse speeds proofs**: Earlier proven equations help prove later ones.

### Usage

The primary input is the JSON export from `free_icrp.py`:

```bash
# Step 1: Compute the candidate free algebra
python free_icrp.py --max-level 2 -o output/free_icrp.pdf
# This creates: output/free_icrp.json (with representative terms)

# Step 2: Verify it
python verify_free_icrp.py output/free_icrp.json

# With custom output directory and timeouts
python verify_free_icrp.py output/free_icrp.json -o verification_output/ \
    --proof-timeout 60 --counter-timeout 120

# Resume from checkpoint (for long-running verifications)
python verify_free_icrp.py output/free_icrp.json --resume

# Parallel verification (4 equations at a time)
python verify_free_icrp.py output/free_icrp.json --parallel 4

# Disable TPTP provers (Prover9 + Mace4 only)
python verify_free_icrp.py output/free_icrp.json --no-tptp

# Disable lemma reuse (prove each equation independently)
python verify_free_icrp.py output/free_icrp.json --no-lemmas
```

### Input formats

The script accepts:
- **JSON** (`.json`): Preferred format, exported by `free_icrp.py`. Includes representative terms automatically.
- **Mace4 model** (`.model`): Secondary format. If representative terms are not in comments, they are computed via BFS from the generator `x` and constant `e`.

To specify a non-default generator element for `.model` files:
```bash
python verify_free_icrp.py output.model --generator-index 1
```

### Verification process

For each operation table entry:
1. **Prove** the equation using Prover9 and TPTP provers (Vampire, Zipperposition) with a configurable timeout.
2. **Reuse lemmas**: Previously proven equations are added to the theory (configurable via `--max-lemmas`).
3. **Search for counterexamples**: If no proof is found, use Mace4 to search for a counterexample in domain sizes 2–10 (configurable).
4. **Checkpoint progress**: Results are saved after each equation (or batch in parallel mode), so long verifications can be resumed with `--resume`.

### Parallel verification

When `--parallel N` is specified with N > 1, equations are verified in batches of size N:
- **Sound lemma sharing**: Only lemmas proven BEFORE a batch starts are used in that batch
- **Batch processing**: Each batch is verified in parallel using N worker processes
- **Incremental lemmas**: Proven equations from batch K become available as lemmas for batch K+1

Example:
```bash
# Verify with 8 parallel workers
python verify_free_icrp.py output/free_icrp.json --parallel 8
```

### Output

The script produces:
- **`verification_summary.json`**: Overall results (proved/refuted/unknown counts) and per-equation details.
- **`verification_checkpoint.json`**: Resumable checkpoint (updated after each equation or batch).
- **`counterexamples/counter_*.model`**: Mace4 models for refuted equations (if any).

### Interpreting results

- **All equations proved** → The candidate is a valid free 1-generated iCRP.
- **Some equations refuted** → The candidate is NOT free (counterexamples saved).
- **Some equations unknown** → Verification incomplete (increase timeouts or use stronger provers).

### Tests

Run the test suite (uses mocks; does not require provers):
```bash
pip install pytest pytest-asyncio
python -m pytest test_verify_free_icrp.py -v
```

Standalone tests (no dependencies):
```bash
python3 test_verify_simple.py
```

For integration tests with real provers:
```bash
# Create a small test algebra
python free_icrp.py --max-level 1 -o test_output/small_free.pdf
# Verify it
python verify_free_icrp.py test_output/small_free.json --proof-timeout 10
```

## Free-algebra search (Prover9 / Mace4 / Vampire / Zipperposition)

`free_bciwme.py` and `free_icrp.py` classify the free-algebra order by racing solvers in `free_algebra.decide`:

| Role | Solver | Input |
|------|--------|--------|
| Counterexamples | **Mace4** | LADR (Prover9 format) |
| Proofs | **Prover9** | LADR |
| Proofs | **Vampire**, **Zipperposition** (if on `PATH`) | TPTP (converted from LADR) |

The first solver that returns a decisive answer wins; the others are cancelled.

### Optional ATP binaries

Install [Vampire](https://vprover.github.io/) and/or [Zipperposition](https://github.com/sneeuwballen/zipperposition) and put them on your `PATH` (e.g. `C:\vampire\vampire.exe`, `C:\zipperposition\zipperposition.exe`). Discovery is automatic:

```powershell
python free_bciwme.py --max-level 2 --timeout 120
# prints: Racing solvers: mace4, prover9, vampire, zipperposition
```

Useful flags:

- `--no-tptp` — Prover9 + Mace4 only
- `--tptp-provers auto` — default; every supported binary on `PATH`
- `--tptp-provers vampire` or `--tptp-provers vampire,zipperposition` — restrict the portfolio

LADR→TPTP conversion uses the LADR `ladr_to_tptp` binary (located with `pyp9m4.BinaryResolver`, invoked with ordinary `subprocess` pipes — not `LadrToTptp.run`, whose asyncio pipes can drop stdin/stdout on Windows). Symbols illegal in TPTP (such as `\` and often `<=`) are renamed (e.g. to `tptp0`, `tptp1`). This repo also post-processes leftover infix `<=` in FOF formulas so Vampire/Zipperposition see a consistent `tptp1/2` predicate. See `tptp_provers.py`.

**Windows notes:**

- Zipperposition’s `--timeout` uses Unix signals and crashes (`Sys.signal: unavailable signal`). The runner omits that flag and enforces the limit in Python instead.
- The Windows Vampire build is **Cygwin** (`cygwin1.dll` next to `vampire.exe`). Cygwin mishandles Windows 8.3 temp paths (`C:\Users\U28409~1\...`). Problem, proof, and Vampire’s own temp files go in gitignored `.tptp_tmp/` with long paths and forward slashes, and `TMP`/`TEMP`/`TMPDIR` are pointed there.
- A Python `asyncio` pipe is fine on Linux/macOS, and Zipperposition on Windows is a native binary so file-backed stdout works. It is the wrong approach for Cygwin Vampire casc, and for `ladr_to_tptp` while Vampire is leaking Cygwin forks.

### Related Python libraries (optional)

These are **not** required by this project; the integration uses `asyncio` subprocesses + SZS status lines, with conversion via **pyp9m4**.

| Need | Library / tool | Notes |
|------|----------------|-------|
| LADR ↔ TPTP | **pyp9m4** (`BinaryResolver` → `ladr_to_tptp`) | Locates the LADR binary; this repo runs it with `subprocess` |
| Call Vampire from pip | [pyvampire](https://github.com/philzook58/pyvampire) | Bundles a Linux x86_64 Vampire; not useful on Windows |
| Uniform ATP/SMT runner | [solverpy](https://github.com/cbboyan/solverpy) | Wrappers for Vampire, E, Prover9, cvc5, Z3, …; binaries still separate |
| Parse / check TPTP | [tptp-lark-parser](https://pypi.org/project/tptp-lark-parser/) (CNF), [unicode-fol-kit](https://pypi.org/project/unicode-fol-kit/) (FOF/CNF import + `validate`) | Useful for debugging converted problems; not used in the race loop |
| Competition-style SZS harness | [TobiasScholl/tptp](https://github.com/TobiasScholl/tptp) | Benchmarks solvers by SZS status |

SMT-LIB conversion (cvc5 / Z3 / veriT) is intentionally not used here.

## Conjectures:

- There are so many simple algebras. Is there a construction that can take any (subdirectly irreducible?) IDCRL and make a simple one? Add a new identity element to the top of the fusion semilattice which corresponds to a new minimal element to the poset of join-irreducibles (at the bottom or incomparable with everything).
