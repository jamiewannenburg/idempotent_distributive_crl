from pyp9m4 import InterpFilter
import tempfile
import os
import re

def to_p9m4(axioms,goals=""):
    return f"""formulas(assumptions).
{axioms}
end_of_list.

formulas(goals).
{goals}
end_of_list.
"""

# axioms

lattice_axioms = """
x^x=x.
x^y=y^x.
x^(y^z)=(x^y)^z.
x v x=x.
x v y=y v x.
x v (y v z)=(x v y) v z.
x ^ (x v y) = x.
x v (x ^ y) = x.
(x<=y)<->(x v y=y).
"""

po_axioms = """
x<=x.
(x<=y & y<=z) -> x<=z.
(x<=y & y<=x) -> x=y.
"""

commutative_monoid_axioms = """
x*(y*z)=(x*y)*z.
x*y = y*x.
e*x=x.
"""

commutative_po_monoid_axioms = po_axioms + commutative_monoid_axioms + """
x<=y -> z*x <= z*y.
"""

crp_axioms = commutative_po_monoid_axioms + """
(x*y<=z)<->(y<=x\z).
"""

icrp_axioms = crp_axioms + """
x=x*x.
"""

rsi_crp_axioms = crp_axioms + """
exists x (-(e <= x) & all y (e<=y | y<=x)).
"""

rsi_icrp_axioms = icrp_axioms + """
exists x (-(e <= x) & all y (e<=y | y<=x)).
"""

rsi_conic_icrp_axioms = rsi_icrp_axioms + """
#(x=x\\x)|( (x\\e) = (x\\e)\\(x\\e) ).
x<=e | e<=x.
"""

crl_axioms = lattice_axioms + commutative_monoid_axioms + """
x<=y\(y*x).
x*(x\y) <= y.
x*(y^z)<= (x*y)^(x*z).
(x\y)^(x\z) = x\(y^z).
"""

idcrl_axioms = crl_axioms + """
x=x*x.
x^(y v z)=(x^y)v(x^z).
% helps speed up mace4 searches
(x <= e & y <= e) -> (x * y = x ^ y).
(e <= x & e <= y) -> (x * y = x v y).
"""

si_idcrl_axioms = idcrl_axioms + """
exists x all y (x<=e & x!=e & (y<=e -> (y=e | y<=x))).
"""

si_conic_idcrl_axioms = si_idcrl_axioms + """
x<=e | e<=x.
"""

simple_idcrl_axioms = idcrl_axioms + """
(x<=e & x != e)->(x<= y).
"""

simple_conic_idcrl_axioms = simple_idcrl_axioms + """
x<=e | e<=x.
"""


def check_formulas(formulas: str, model_string: str, print_output: bool = False):
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.write(formulas.encode('utf-8'))
    temp_file.close()
    result = InterpFilter().run(input=model_string,formulas_file=temp_file.name,test='all_true')
    os.unlink(temp_file.name)
    m = re.search("checked 1, passed 1", result.stdout)
    if m:
        return True
    else:
        if print_output:
            print(result.stdout)
        return False


if __name__=="__main__":
    print(to_p9m4(rsi_icrp_axioms))