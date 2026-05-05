from pyp9m4 import Model, parse_models_from_file, InterpFilter
import tempfile
import os
import re
import numpy as np
import itertools
from icrp import get_leq_from_idempotent_residual, leq_arrows
from icrl import get_leq_from_meet_operation
from icrl import to_interpretation_text as to_crl_interpretation_text
from conic_icrp import principal_upset
from axioms import idcrl_axioms
from find_expansions import _terminal_status, diagram
from typing import Callable



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

def upsemigroup_generator(leq: np.ndarray, dot: Callable[[int, int], int], domain_size: int, i: int):
    upsemigroup = set(principal_upset(leq, i))
    while True:
        new_elements = set()
        # close under dot, one pass
        for j,k in itertools.product(upsemigroup, repeat=2):
            v = dot(j, k)
            if v not in upsemigroup:
                new_elements.add(v)
        if len(new_elements) == 0:
            break # closed under dot
        # add upward closure of new elements
        for v in new_elements:
            if v not in upsemigroup:
                upv = principal_upset(leq, v)
                for w in upv:
                    upsemigroup.add(w)
    # return upsemigroup as a sorted tuple
    return tuple(sorted(upsemigroup))
    

def get_upsemigroups(leq: np.ndarray, dot: Callable[[int, int], int], domain_size: int):
    upsemigroups = []
    universe = list(range(domain_size))
    for subset in itertools.chain.from_iterable(itertools.combinations(universe, r) for r in range(len(universe)+1)):
        if len(subset) == 0:
            continue
        closed = True
        for i in subset:
            if len(set(principal_upset(leq, i))-set(subset)) != 0:
                closed = False # not upward closed
                break
        if closed:
            for i,j in itertools.product(subset, repeat=2):
                if dot(i, j) not in subset:
                    closed = False # not closed under the semigroup operation
                    break
        if closed:
            upsemigroups.append(subset)
    return upsemigroups

def get_extension_operations(model: Model):
    crp_leq = get_leq_from_idempotent_residual(model)
    crp_dot = model.as_function("*")
    crp_arrow = model.as_function("\\")
    e = model.get_value("e")
    upsemigroups = get_upsemigroups(crp_leq, crp_dot, model.domain_size)
    
    # get distributive lattice operations on the upsets
    def dl_meet(x,y): # intersection
        return tuple(sorted(set(x) & set(y)))
    def dl_join(x,y): # closure of union

        result_set = set(x) | set(y)
        while True:
            new_elements = set()
            for i,j in itertools.product(result_set, repeat=2):
                v = crp_dot(i, j)
                if v not in result_set:
                    new_elements.add(v)
            if len(new_elements) == 0:
                break
            # add upward closure of new elements
            for v in new_elements:
                if v not in result_set:
                    upv = principal_upset(crp_leq, v)
                    for w in upv:
                        result_set.add(w)

        return tuple(sorted(result_set))

    # create map to new algebra that agrees on elements from the original algebra
    crp_to_dl = {}
    dl_to_crp = {}
    for i in range(model.domain_size):
        # map positive elements to their generated upsemigroup
        crp_to_dl[i] = upsemigroup_generator(crp_leq, crp_dot, model.domain_size, i)
        dl_to_crp[crp_to_dl[i]] = i
    # add new elements
    i = model.domain_size
    for a in upsemigroups:
        if a not in dl_to_crp:
            dl_to_crp[a] = i
            crp_to_dl[i] = a
            i += 1

    new_domain_size = len(crp_to_dl)
    # make operations on the new algebra (distributive lattice upside down)
    def meet(x,y):
        return dl_to_crp[dl_join(crp_to_dl[x], crp_to_dl[y])]
    def join(x,y):
        return dl_to_crp[dl_meet(crp_to_dl[x], crp_to_dl[y])]
        
    def dot(x,y):
        # pointwise multiplication
        xs = crp_to_dl[x]
        ys = crp_to_dl[y]
        result_set = set()
        for i,j in itertools.product(xs, ys):
            # union of result_set with principal_upset(leq, crp_dot(i, j))
            result_set.update(principal_upset(crp_leq, crp_dot(i, j)))
        return dl_to_crp[tuple(sorted(result_set))]

    leq = get_leq_from_meet_operation(meet, new_domain_size)

    def arrow(x,y):
        # largest element whose dot with x is less than or equal to y
        best = None
        for i in range(new_domain_size):
            if leq[dot(i, x), y]:
                if best is None:
                    best = i
                elif leq[best, i]:
                    best = i
                elif leq[i, best]:
                    best = best
                else:
                    new_best = join(best, i)
                    assert leq[dot(new_best, x), y], f"{crp_to_dl[x]} * {crp_to_dl[i]} = {crp_to_dl[dot(i, x)]} <= {crp_to_dl[y]} and \n{crp_to_dl[x]} * {crp_to_dl[best]} = {crp_to_dl[dot(best, x)]} <= {crp_to_dl[y]} but the join\n {crp_to_dl[x]} * {crp_to_dl[new_best]} = {crp_to_dl[dot(new_best, x)]} not <= {crp_to_dl[y]}"
                    best = new_best
        return best

    return new_domain_size, meet, join, dot, arrow, leq, e

def get_extension_interpretation_text(number: str, model: Model):
    new_domain_size, meet, join, dot, arrow, leq, e = get_extension_operations(model)
    return to_crl_interpretation_text(number, new_domain_size, meet, join, dot, arrow, leq, e)

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str)
    args = parser.parse_args()
    model_filename = Path(args.input)
    models = parse_models_from_file(model_filename)
    for model in models:
        name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
        try:
            extension = get_extension_interpretation_text(name, model)
            if not check_formulas(idcrl_axioms+diagram(model), extension, print_output=True):
                print(f"model {name}: extension does not work")
                print(extension)
        except Exception as e:
            print(f"model {name}: error in extension generation: {e}")
            print(model)