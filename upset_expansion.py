from pyp9m4 import Model, parse_models_from_file
from pyp9m4.parsers.mace4 import parse_mace4_output
import re
import numpy as np
import itertools
from icrp import get_leq_from_idempotent_residual, leq_arrows
from icrl import get_leq_from_meet_operation
from icrl import to_interpretation_text as to_crl_interpretation_text

def principal_upset(leq: np.ndarray, element: int):
    return tuple(int(i) for i in np.nonzero(leq[element, :])[0])

def get_upsets(leq: np.ndarray, domain_size: int):
    upsets = []
    universe = list(range(domain_size))
    for subset in itertools.chain.from_iterable(itertools.combinations(universe, r) for r in range(len(universe)+1)):
        # if len(subset) == 0:
        #     continue
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

def get_expansion_operations(model: Model):
    crp_leq = get_leq_from_idempotent_residual(model)
    crp_dot = model.as_function("*")
    crp_arrow = model.as_function("\\")
    e = model.get_value("e")
    upsets = get_upsets(crp_leq, model.domain_size)
    
    # get distributive lattice operations on the upsets
    def dl_meet(x,y):
        return tuple(sorted(set(x) & set(y)))
    def dl_join(x,y):
        return tuple(sorted(set(x) | set(y)))

    # create map to new algebra that agrees on elements from the original algebra
    crp_to_dl = {}
    dl_to_crp = {}
    for i in range(model.domain_size):
        crp_to_dl[i] = principal_upset(crp_leq, i)
        dl_to_crp[crp_to_dl[i]] = i
    i = model.domain_size
    for a in upsets:
        if a not in dl_to_crp:
            dl_to_crp[a] = i
            crp_to_dl[i] = a
            i += 1
    new_domain_size = len(crp_to_dl)
    # make operations on the new algebra
    def meet(x,y):
        return dl_to_crp[dl_meet(crp_to_dl[x], crp_to_dl[y])]
    
    def join(x,y):
        return dl_to_crp[dl_join(crp_to_dl[x], crp_to_dl[y])]

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

def get_expansion_interpretation_text(number: str, model: Model):
    new_domain_size, meet, join, dot, arrow, leq, e = get_expansion_operations(model)
    return to_crl_interpretation_text(number, new_domain_size, meet, join, dot, arrow, leq, e)

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from find_expansions import diagram
    import matplotlib.backends.backend_pdf
    import matplotlib.pyplot as plt
    from draw_orders import draw_idempotent_crl
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str)
    parser.add_argument("-o", "--output", type=str)
    # add optional argument a comma separated list of model numbers to check
    parser.add_argument("-m", "--models", type=str, default=None)
    args = parser.parse_args()
    if args.models is not None:
        model_numbers = args.models.split(',')
    else:
        model_numbers = None
    model_filename = Path(args.input)
    pdf_filename = args.output
    if pdf_filename is None:
        output_folder = Path('output')
        pdf_filename = output_folder / model_filename.with_suffix("_upset_expansion.pdf")
    else:
        pdf_filename = Path(pdf_filename)
    pdf = matplotlib.backends.backend_pdf.PdfPages(filename = str(pdf_filename))
    models = parse_models_from_file(model_filename)
    for model in models:
        name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
        n = int(re.search(r"interpretation\(\s*(\d+),",model.raw).group(1))
        if model_numbers is not None and name not in model_numbers:
            continue
        try:
            expansion_text = get_expansion_interpretation_text(name, model)
            expansion = parse_mace4_output(expansion_text).interpretations[0]
            print(expansion)
            fig = draw_idempotent_crl(expansion,name=name,n=n)
            pdf.savefig(fig, bbox_inches='tight')
            plt.close(fig)
        except Exception as e:
            print(f"model {name}: error in expansion generation: {e}")
            print(model)
    pdf.close()