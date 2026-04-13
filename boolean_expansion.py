from pyp9m4 import Model,parse_models_from_file
from axioms import to_p9m4, idcrl_axioms
import re
import itertools
from icrl import to_interpretation_text, get_leq_from_meet_operation
import numpy as np
from find_expansions import diagram

atoms = [3,4,5,6]
ba_universe = list(itertools.chain.from_iterable(itertools.combinations(atoms, r) for r in range(len(atoms)+1)))
def ba_meet(x,y):
    return tuple(sorted(set(x) & set(y)))
def ba_join(x,y):
    return tuple(sorted(set(x) | set(y)))
crp_to_ba = {
    0: (3,4,5,6),
    1: 1,
    2: (),
    3: (3,),
    4: (4,),
    5: (5,),
    6: (6,),
}
already_added = set(crp_to_ba.values())
for i,a in enumerate(ba_universe):
    if a not in already_added:
        crp_to_ba[i+2] = a
ba_to_crp = {v: k for k, v in crp_to_ba.items()}
extension_universe = list(range(len(crp_to_ba)))
extension_cardinality = len(extension_universe)

def meet(x,y):
    if x == 1:
        return 1
    elif y == 1:
        return 1
    else:
        return ba_to_crp[ba_join(crp_to_ba[x], crp_to_ba[y])]

def join(x,y):
    if x == 1:
        return y
    elif y == 1:
        return x
    else:
        return ba_to_crp[ba_meet(crp_to_ba[x], crp_to_ba[y])]
def dot(x,y):
    if x == 1:
        return 1
    elif y == 1:
        return 1
    else:
        return ba_to_crp[ba_meet(crp_to_ba[x], crp_to_ba[y])]

leq = get_leq_from_meet_operation(meet, extension_cardinality)

def arrow(x,y):
    # largest element whose dot with x is less than or equal to y
    best = None
    for i in range(len(crp_to_ba)):
        if leq[dot(i, x), y]:
            if best is None:
                best = i
            elif leq[best, i]:
                best = i
            elif leq[i, best]:
                best = best
            else:
                best = join(best, i)
                assert leq[dot(best, x), y], f"join of two elements that are not less than or equal to y: {best}, {i}, {x}, {y}"
    return best

embedding = to_interpretation_text("861", extension_cardinality, dot, arrow, leq, 0)

print(embedding)
with open("model_outputs/rsi_icrp-7-861-expansion.model", "w") as f:
    f.write(embedding)

with open("model_outputs/rsi_icrp-7-861.model") as f:
    for model in parse_models_from_file(f):
        name = re.search(r"number = (\d+)",model.raw).group(1)
        print(name)
        diagram_sentence = diagram(model)
        for i in range(7):
            assert dot(i,i) == i, f"dot({i},{i}) = {dot(i,i)} != {i}"
            for j in range(7):
                icrp_arrow = model.as_function("\\")
                icrp_dot = model.as_function("*")
                assert icrp_dot(i,j) == dot(i,j), f"dot({i},{j}) = {icrp_dot(i,j)} != {dot(i,j)}"
                assert icrp_arrow(i,j) == arrow(i,j), f"arrow({i},{j}) = {icrp_arrow(i,j)} != {arrow(i,j)}"
                assert dot(i,j) == dot(j,i), f"dot({i},{j}) = {dot(i,j)} != {dot(j,i)}"

