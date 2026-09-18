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

LADR→TPTP conversion uses `pyp9m4.LadrToTptp` (the LADR `ladr_to_tptp` tool shipped with Prover9). Symbols illegal in TPTP (such as `\` and often `<=`) are renamed (e.g. to `tptp0`, `tptp1`). This repo also post-processes leftover infix `<=` in FOF formulas so Vampire/Zipperposition see a consistent `tptp1/2` predicate. See `tptp_provers.py`.

**Windows notes:**

- Zipperposition’s `--timeout` uses Unix signals and crashes (`Sys.signal: unavailable signal`). The runner omits that flag and enforces the limit in Python instead.
- The Windows Vampire build is **Cygwin** (`cygwin1.dll` next to `vampire.exe`). Cygwin mishandles Windows 8.3 temp paths (`C:\Users\U28409~1\...`). Problem, proof, and Vampire’s own temp files go in gitignored `.tptp_tmp/` with long paths and forward slashes, and `TMP`/`TEMP`/`TMPDIR` are pointed there.
- A Python `asyncio` pipe is fine on Linux/macOS, and Zipperposition on Windows is a native binary so file-backed stdout works. It is the wrong approach for Cygwin Vampire casc.

### Related Python libraries (optional)

These are **not** required by this project; the integration uses `asyncio` subprocesses + SZS status lines, with conversion via **pyp9m4**.

| Need | Library / tool | Notes |
|------|----------------|-------|
| LADR ↔ TPTP | **pyp9m4** (`LadrToTptp`, `TptpToLadr`) | Already a dependency; wraps LADR binaries |
| Call Vampire from pip | [pyvampire](https://github.com/philzook58/pyvampire) | Bundles a Linux x86_64 Vampire; not useful on Windows |
| Uniform ATP/SMT runner | [solverpy](https://github.com/cbboyan/solverpy) | Wrappers for Vampire, E, Prover9, cvc5, Z3, …; binaries still separate |
| Parse / check TPTP | [tptp-lark-parser](https://pypi.org/project/tptp-lark-parser/) (CNF), [unicode-fol-kit](https://pypi.org/project/unicode-fol-kit/) (FOF/CNF import + `validate`) | Useful for debugging converted problems; not used in the race loop |
| Competition-style SZS harness | [TobiasScholl/tptp](https://github.com/TobiasScholl/tptp) | Benchmarks solvers by SZS status |

SMT-LIB conversion (cvc5 / Z3 / veriT) is intentionally not used here.

## Conjectures:

- There are so many simple algebras. Is there a construction that can take any (subdirectly irreducible?) IDCRL and make a simple one? Add a new identity element to the top of the fusion semilattice which corresponds to a new minimal element to the poset of join-irreducibles (at the bottom or incomparable with everything).
