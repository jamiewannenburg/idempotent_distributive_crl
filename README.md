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

## Conjectures:

- There are so many simple algebras. Is there a construction that can take any (subdirectly irreducible?) IDCRL and make a simple one? Add a new identity element to the top of the fusion semilattice which corresponds to a new minimal element to the poset of join-irreducibles (at the bottom or incomparable with everything).