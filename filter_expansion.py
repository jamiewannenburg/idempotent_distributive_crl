from pyp9m4 import Model, parse_models_from_file
from pyp9m4.parsers.mace4 import parse_mace4_output
import re
import numpy as np
import itertools
from icrp import get_leq_from_idempotent_residual, leq_arrows
from icrl import get_leq_from_meet_operation
from icrl import to_interpretation_text as to_crl_interpretation_text
from upset_expansion import principal_upset
from typing import Any, Callable

def get_filters(leq: np.ndarray, meet: Callable[[int, int], int], domain_size: int):
    filters = []
    universe = list(range(domain_size))
    for subset in itertools.chain.from_iterable(itertools.combinations(universe, r) for r in range(len(universe)+1)):
        # if len(subset) == 0:
        #     continue
        closed = True # upwards closed and closed under meet
        for i in subset:
            if len(set(principal_upset(leq, i))-set(subset)) != 0:
                closed = False
                break

        if closed:
            for i,j in itertools.product(subset, repeat=2):
                if meet(i, j) not in subset:
                    closed = False
                    break
        if closed:
            filters.append(subset)
    return filters


def get_leq_array(model: Model):
    return get_leq_array_from_relation(model.as_relation("<="), model.domain_size)

def get_leq_array_from_relation(relation: Callable[[int, int], bool], domain_size: int):
    leq = np.zeros((domain_size, domain_size), dtype=bool)
    for i,j in itertools.product(range(domain_size), repeat=2):
        if relation(i, j):
            leq[i, j] = True
        else:
            leq[i, j] = False
    return leq


def get_filter_expansion_operations(m: Model): # CRL
    leq = get_leq_array(m)
    dot = m.as_function("*")
    meet = m.as_function("^")
    e = m.get_value("e")
    filters = get_filters(leq, meet, m.domain_size)
    
    # get distributive lattice operations on the filters
    def dl_meet(x,y):
        return tuple[Any, ...](sorted(set(x) & set(y)))
    def dl_join(x,y):
        result_set = set(x) | set(y)
        while True:
            new_elements = set()
            for i,j in itertools.product(result_set, repeat=2):
                v = meet(i, j)
                if v not in result_set:
                    upv = principal_upset(leq, v)
                    for w in upv:
                        if w not in result_set:
                            new_elements.add(w)
            if len(new_elements) == 0:
                break
            result_set.update(new_elements)
        return tuple[Any, ...](sorted(result_set))

    # create map to new algebra that agrees on elements from the original algebra
    crl_to_dl = {}
    dl_to_crl = {}
    for i in range(m.domain_size):
        crl_to_dl[i] = principal_upset(leq, i)
        dl_to_crl[crl_to_dl[i]] = i
    i = m.domain_size
    for a in filters:
        if a not in dl_to_crl:
            dl_to_crl[a] = i
            crl_to_dl[i] = a
            i += 1
    new_domain_size = len(crl_to_dl)
    # make operations on the new algebra
    def exmeet(x,y):
        return dl_to_crl[dl_meet(crl_to_dl[x], crl_to_dl[y])]
    
    def exjoin(x,y):
        return dl_to_crl[dl_join(crl_to_dl[x], crl_to_dl[y])]

    def exdot(x,y):
        # pointwise multiplication
        xs = crl_to_dl[x]
        ys = crl_to_dl[y]
        result_set = set()
        for i,j in itertools.product(xs, ys):
            v = dot(i, j)
            upv = principal_upset(leq, v)
            for w in upv:
                if w not in result_set:
                    result_set.add(w)
        while True:
            new_elements = set()
            for i,j in itertools.product(result_set, repeat=2):
                v = meet(i, j)
                if v not in result_set:
                    upv = principal_upset(leq, v)
                    for w in upv:
                        if w not in result_set:
                            new_elements.add(w)
            if len(new_elements) == 0:
                break
            result_set.update(new_elements)
        return dl_to_crl[tuple(sorted(result_set))]

    exleq = get_leq_from_meet_operation(exmeet, new_domain_size)

    def exarrow(x,y):
        # largest element whose dot with x is less than or equal to y
        best = None
        for i in range(new_domain_size):
            if exleq[exdot(i, x), y]:
                if best is None:
                    best = i
                elif exleq[best, i]:
                    best = i
                elif exleq[i, best]:
                    best = best
                else:
                    new_best = exjoin(best, i)
                    assert exleq[exdot(new_best, x), y], f"{crl_to_dl[x]} * {crl_to_dl[i]} = {crl_to_dl[exdot(i, x)]} <= {crl_to_dl[y]} and \n{crl_to_dl[x]} * {crl_to_dl[best]} = {crl_to_dl[exdot(best, x)]} <= {crl_to_dl[y]} but the join\n {crl_to_dl[x]} * {crl_to_dl[new_best]} = {crl_to_dl[exdot(new_best, x)]} not <= {crl_to_dl[y]}"
                    best = new_best
        return best

    return new_domain_size, exmeet, exjoin, exdot, exarrow, exleq, e

def get_filter_expansion_interpretation_text(number: str, m: Model):
    new_domain_size, meet, join, dot, arrow, leq, e = get_filter_expansion_operations(m)
    return to_crl_interpretation_text(number, new_domain_size, meet, join, dot, arrow, leq, e)


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from find_expansions import diagram, check_formulas
    import matplotlib.backends.backend_pdf
    import matplotlib.pyplot as plt
    from semigroup_expansion import draw_fusion_graph, draw_le_graph, check_idempotent, check_expansion
    from semigroup_expansion import get_expansion_interpretation_text as get_sg_expansion_interpretation_text

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
        pdf_filename = output_folder / (model_filename.stem+"_filter_expansion.pdf")
    else:
        pdf_filename = Path(pdf_filename)
    pdf = matplotlib.backends.backend_pdf.PdfPages(filename = str(pdf_filename))
    models = parse_models_from_file(model_filename)
    for model in models:
        name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
        n = model.domain_size
        if model_numbers is not None and name not in model_numbers:
            continue
        print(f"expanding model {name}")
        # try:
        first_expansion_text = get_sg_expansion_interpretation_text(name, model)
        first_expansion = parse_mace4_output(first_expansion_text).interpretations[0]
        print(first_expansion)
        first_idempotent = check_idempotent(first_expansion)
        if not first_idempotent:
            print(f"first expansion of model {name} is not idempotent")
        
        if not check_formulas("x^(y v z)=(x^y)v(x^z).",first_expansion):
            print(f"first expansion of model {name} is not distributive")

        expansion_text = get_filter_expansion_interpretation_text(name, first_expansion)
        print(expansion_text)
        expansion = parse_mace4_output(expansion_text).interpretations[0]
        second_idempotent = check_idempotent(expansion)

        if not second_idempotent:
            print(f"expansion of model {name} is not idempotent")
        check_expansion(model, expansion)
        if not check_formulas("x^(y v z)=(x^y)v(x^z).",expansion):
            print(f"expansion of model {name} is not distributive")

        #fig = draw_idempotent_crl(expansion,name=name,n=n)
        
        # Create figure with three subplots side by side
        if first_idempotent and second_idempotent:
            fig, (ax1,ax2,ax3,ax4) = plt.subplots(1, 4, figsize=(10, 4))
            ax1 = draw_fusion_graph(ax1, first_expansion, n, title="First Expansion Fusion SemiLattice")
            ax2 = draw_le_graph(ax2, first_expansion, n, title="First Expansion Lattice")
            ax3 = draw_fusion_graph(ax3, expansion, n, title="Second Expansion Fusion SemiLattice")
            ax4 = draw_le_graph(ax4, expansion, n, title="Second Expansion Lattice")
        elif first_idempotent:
            fig, (ax1,ax2,ax3) = plt.subplots(1, 3, figsize=(10, 4))
            ax1 = draw_fusion_graph(ax1, first_expansion, n, title="First Expansion Fusion SemiLattice")
            ax2 = draw_le_graph(ax2, first_expansion, n, title="First Expansion Lattice")
            ax3 = draw_le_graph(ax3, expansion, n, title="Second Expansion Lattice")
        else:
            fig, (ax1,ax2) = plt.subplots(1, 2, figsize=(10, 4))
            ax1 = draw_le_graph(ax1, first_expansion, n, title="First Expansion Lattice")
            ax2 = draw_le_graph(ax2, expansion, n, title="Second Expansion Lattice")
        fig.suptitle(f"model{name}", fontsize=14, fontweight='bold')
        
        plt.tight_layout()
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)
        # except Exception as e:
        #     print(f"model {name}: error in expansion generation: {e}")
        #     print(model)
    pdf.close()