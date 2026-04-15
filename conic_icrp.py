from pyp9m4 import Model, parse_models_from_file, InterpFilter
import tempfile
import os
import re
import numpy as np
import itertools
from icrp import get_leq_from_idempotent_residual, leq_arrows
from icrl import get_leq_from_meet_operation
from icrl import to_interpretation_text as to_crl_interpretation_text
from axioms import rsi_conic_icrp_axioms

def is_conic(model: Model, print_output: bool = False):
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    # -> version of x<=e | e<=x
    temp_file.write(f"({leq_arrows('e','x')})|({leq_arrows('x','e')}).\n".encode('utf-8'))
    temp_file.close()
    result = InterpFilter().run(input=model.raw,formulas_file=temp_file.name,test='all_true')
    os.unlink(temp_file.name)
    m = re.search("checked 1, passed 1", result.stdout)
    if m:
        return True
    else:
        if print_output:
            print(result.stdout)
        return False

def is_rsi_conic_icrp(model: Model, print_output: bool = False):
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.write(rsi_conic_icrp_axioms.encode('utf-8'))
    temp_file.close()
    result = InterpFilter().run(input=model.raw,formulas_file=temp_file.name,test='all_true')
    os.unlink(temp_file.name)
    m = re.search("checked 1, passed 1", result.stdout)
    if m:
        return True
    else:
        if print_output:
            print(result.stdout)
        return False

def get_positive_elements_from_leq(leq: np.ndarray, e: int):
    positive_elements = []
    for i in range(leq.shape[0]):
        if leq[e, i]:
            positive_elements.append(i)
    return positive_elements

def principal_upset(leq: np.ndarray, element: int):
    return tuple(int(i) for i in np.nonzero(leq[element, :])[0])

def get_upsets(leq: np.ndarray, positive_elements: list):
    upsets = []
    for subset in itertools.chain.from_iterable(itertools.combinations(positive_elements, r) for r in range(len(positive_elements)+1)):
        if len(subset) == 0:
            continue
        upwards_closed = True
        for i in subset:
            if len(set(principal_upset(leq, i))-set(subset)) != 0:
                upwards_closed = False
                break
        if upwards_closed:
            upsets.append(subset)
    return upsets

def get_meet_from_leq(leq: np.ndarray):
    def meet(x,y):
        best = None
        for i in range(leq.shape[0]):
            if leq[i, x] and leq[i, y]:
                if best is None:
                    best = i
                elif leq[best, i]:
                    best = i
                # ignore other cases, this assumes leq is a lattice order
        if best is None:
            raise ValueError(f"no lower bound for {x} and {y}")
        return best
    return meet


def get_join_from_leq(leq: np.ndarray):
    def join(x,y):
        best = None
        for i in range(leq.shape[0]):
            if leq[x, i] and leq[y, i]:
                if best is None:
                    best = i
                elif leq[i, best]:
                    best = i
                # ignore other cases, this assumes leq is a lattice order
        if best is None:
            raise ValueError(f"no upper bound for {x} and {y}")
        return best
    return join

def get_extension_operations(model: Model):
    crp_leq = get_leq_from_idempotent_residual(model)
    crp_dot = model.as_function("*")
    crp_arrow = model.as_function("\\")
    # TODO: this is a lattice order, so it should work
    crp_meet = get_meet_from_leq(crp_leq)
    crp_join = get_join_from_leq(crp_leq)
    e = model.get_value("e")
    positive_elements = get_positive_elements_from_leq(crp_leq, e)
    upsets = get_upsets(crp_leq, positive_elements)
    
    # get distributive lattice operations on the upsets
    def dl_meet(x,y):
        return tuple(sorted(set(x) & set(y)))
    def dl_join(x,y):
        return tuple(sorted(set(x) | set(y)))

    # create map to new algebra that agrees on elements from the original algebra
    crp_to_dl = {}
    dl_to_crp = {}
    for i in range(model.domain_size):
        if i in positive_elements:
            # map positive elements to their principal upset
            crp_to_dl[i] = principal_upset(crp_leq, i)
            dl_to_crp[principal_upset(crp_leq, i)] = i
        else:
            # map negative elements to themselves
            crp_to_dl[i] = i
            dl_to_crp[i] = i
    i = model.domain_size
    for a in upsets:
        if a not in dl_to_crp:
            dl_to_crp[a] = i
            crp_to_dl[i] = a
            i += 1
    new_domain_size = len(crp_to_dl)
    # make operations on the new algebra
    def pos(x):
        return x>=model.domain_size or x in positive_elements
    
    def meet(x,y):
        if pos(x) and pos(y):
            return dl_to_crp[dl_join(crp_to_dl[x], crp_to_dl[y])]
        elif pos(x): # y is neg
            return y
        elif pos(y): # x is neg
            return x
        else: # x and y are neg
            return crp_meet(x, y)
    
    def join(x,y):
        if pos(x) and pos(y):
            return dl_to_crp[dl_meet(crp_to_dl[x], crp_to_dl[y])]
        elif pos(x): # y is neg
            return x
        elif pos(y): # x is neg
            return y
        else: # x and y are neg
            return crp_join(x, y)

    def dot(x,y):
        if pos(x) and pos(y):
            return dl_to_crp[dl_meet(crp_to_dl[x], crp_to_dl[y])]
        elif pos(x): # y is neg
            if leq[x, crp_arrow(y, y)]:
                return y
            else:
                return x
        elif pos(y): # x is neg
            if leq[y, crp_arrow(x, x)]:
                return x
            else:
                return y
        else: # x and y are neg
            return crp_dot(x, y)

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
                    best = join(best, i)
                    assert leq[dot(best, x), y], f"join of two elements that are not less than or equal to y: {best}, {i}, {x}, {y}"
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
        if is_conic(model):
            print(f"model {name} is conic")
        # else:
        #     print(f"model {name} is not conic")