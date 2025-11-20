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
# Install uacalc directly from git repository (latest version)
pip install git+https://github.com/jamiewannenburg/uacalcsrc.git
pip install networkx
pip install uacalc[drawing]
pip install matplotlib
```

Alternatively, you can install from a GitHub Release wheel file. Copy the link to the latest release for your platform and python version from [uacalc GitHub Releases](https://github.com/jamiewannenburg/uacalcsrc/releases) and install it:

```bash
# Install from GitHub Release (replace version and wheel filename with latest)
pip install https://github.com/jamiewannenburg/uacalcsrc/releases/download/v0.0.4/uacalc-0.0.4-cp310-cp310-win_amd64.whl
pip install networkx
pip install uacalc[drawing]
pip install matplotlib
```

Open `idempotent_distributive_crl.in` with Prover9/mace4 and run mace4.
This generates simple IDCRLs with up to 7 elements. Filter out isomorphic copies. Save the result to `idempotent_distributive_crl.model`.

Then run `python draw_orders.py`.

## Conjectures:

- There are so many simple algebras. Is there a construction that can take any (subdirectly irreducible?) IDCRL and make a simple one? Add a new identity element to the top of the fusion semilattice which corresponds to a new minimal element to the poset of join-irreducibles (at the bottom or incomparable with everything).