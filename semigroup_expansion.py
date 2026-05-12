from pyp9m4 import Model, parse_models_from_file
import re
import numpy as np
import itertools
from icrp import get_leq_from_idempotent_residual, leq_arrows, get_fusion_graph
from icrl import get_leq_from_meet_operation, get_le, get_join_irreducibles_from_graph, get_graph_from_le
from icrl import to_interpretation_text as to_crl_interpretation_text
from upset_expansion import principal_upset
from axioms import idcrl_axioms, check_formulas
from typing import Callable
from pyp9m4.parsers.mace4 import parse_mace4_output
from draw_orders import draw_idempotent_crl, draw_graph


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
        # if len(subset) == 0:
        #     continue
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

def get_expansion_operations(model: Model):
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
        if best is None:
            raise ValueError(f"no element whose dot with {x} is less than or equal to {y}")
        return best

    return new_domain_size, meet, join, dot, arrow, leq, e

def get_expansion_interpretation_text(number: str, model: Model):
    new_domain_size, meet, join, dot, arrow, leq, e = get_expansion_operations(model)
    return to_crl_interpretation_text(number, new_domain_size, meet, join, dot, arrow, leq, e)

def get_le_graph(model: Model):
    leq = np.zeros((model.domain_size, model.domain_size), dtype=bool)
    for i,j in itertools.product(range(model.domain_size), repeat=2):
        if model.holds("<=", i, j):
            leq[i, j] = True
        else:
            leq[i, j] = False
    le = get_le(leq)
    return get_graph_from_le(le)

def get_le_graph_colors_and_highlight_nodes(model: Model, n: int):
    card = model.domain_size
    colors = []
    for i in range(n):
        colors.append('orange')
    for i in range(card-n):
        colors.append('lightblue')
    le_graph = get_le_graph(model)
    join_irreducibles_list = get_join_irreducibles_from_graph(le_graph)
    return le_graph, colors, join_irreducibles_list

def draw_le_graph(ax, model: Model, n: int, title: str = "Lattice"):
    le_graph, colors, join_irreducibles_list = get_le_graph_colors_and_highlight_nodes(model, n)
    ax = draw_graph(ax, le_graph, title, node_colors=colors, highlight_nodes=join_irreducibles_list)
    return ax

def draw_fusion_graph(ax, model: Model, n: int, title: str = "Fusion SemiLattice"):
    le_graph, colors, join_irreducibles_list = get_le_graph_colors_and_highlight_nodes(model, n)
    fusion_graph = get_fusion_graph(model)
    ax = draw_graph(ax, fusion_graph, title, node_colors=colors, highlight_nodes=join_irreducibles_list)
    return ax

def check_idempotent(model: Model):
    for i in range(model.domain_size):
        if model.get_value("*", i, i) != i:
            print(f"model {model.number} is not idempotent at {i}^2={model.value_at('*', i, i)}")
            return False
    return True

def check_expansion(model: Model, expansion: Model):
    for i,j in itertools.product(range(model.domain_size), repeat=2):
        if model.value_at("*", i, j) != expansion.value_at("*", i, j):
            print(f"expansion {model.number} does not agree on {i} * {j}")
            return False
        if model.value_at("\\", i, j) != expansion.value_at("\\", i, j):
            print(f"expansion {model.number} does not agree on {i} \\ {j}")
            return False
    return True

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from find_expansions import diagram, check_formulas
    import matplotlib.backends.backend_pdf
    import matplotlib.pyplot as plt
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
        pdf_filename = output_folder / (model_filename.stem+"_sg_expansion.pdf")
    else:
        pdf_filename = Path(pdf_filename)
    pdf = matplotlib.backends.backend_pdf.PdfPages(filename = str(pdf_filename))
    models = parse_models_from_file(model_filename)
    for model in models:
        name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
        n = model.domain_size
        if model_numbers is not None and name not in model_numbers:
            continue
        # try:
        first_expansion_text = get_expansion_interpretation_text(name, model)
        first_expansion = parse_mace4_output(first_expansion_text).interpretations[0]
        first_idempotent = check_idempotent(first_expansion)
        expansion_text = get_expansion_interpretation_text(name, first_expansion)
        print(expansion_text)
        expansion = parse_mace4_output(expansion_text).interpretations[0]
        second_idempotent = check_idempotent(expansion)

        check_expansion(model, expansion)
        if not check_formulas("x^(y v z)=(x^y)v(x^z).",expansion):
            print(f"expansion {name} does not satisfy the distributive property")

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