
import uacalc_lib as ua
BasicAlgebra = ua.alg.BasicAlgebra
BasicOperation = ua.alg.BasicOperation
string_to_term = ua.terms.string_to_term
TermOperationImp = ua.terms.TermOperationImp
Variable = ua.terms.VariableImp
Equation = ua.eq.Equation
OrderedSet = ua.lat.OrderedSet
# x = Variable('x')
# y = Variable('y')
# arrow_mod_term = string_to_term('\\(\\(x,y),\\(x,y))')

# def arrow_mod(alg: BasicAlgebra):
#     arrow_op = TermOperationImp(arrow_mod_term, [x, y], alg, name="arrowmod")
#     return arrow_op
from pyp9m4 import Model, parse_mace4_output
from pyp9m4.parsers.mace4 import Mace4InterpretationBuffer
import numpy as np
import networkx as nx

def leq(x, y, arrow_op: BasicOperation, universe):
    """Carrier order: x <= y iff (x->y) = (x->y)->(x->y) (idempotent residual).

    BasicOperation.int_value_at (and value_at) take *indices* 0..n-1 into the carrier
    and return the result as another such index (the row-major table value), not as a
    universe label. Do not pass universe values into int_value_at or wrap its result
    with universe.index.
    """
    i = universe.index(x)
    j = universe.index(y)
    k = arrow_op.int_value_at([i, j])
    return k == arrow_op.int_value_at([k, k])

def get_filters(alg: BasicAlgebra):
    universe = alg.get_universe_list()
    print(universe)
    arrow_op = None
    for op in alg.operations():
        if op.symbol().name() == "\\":
            arrow_op = op
    # arrow_mod_op = arrow_mod(alg)
    filters = []
    for i,x in enumerate(universe):
        xfilter = []
        for j,y in enumerate(universe):
            if leq(x,y,arrow_op,universe):
                xfilter.append(y)
        filters.append(xfilter)

    return filters

def to_ordered_set(alg: BasicAlgebra):
    filters = get_filters(alg)
    print(alg.get_universe_list(),filters)
    return OrderedSet.from_filters(alg.get_universe_list(),filters,name=alg.name())

def get_leq_from_idempotent_residual(model: Model):
    arrow = model.as_function("\\")
    leq = np.zeros((model.domain_size, model.domain_size),dtype=bool)
    for i in range(model.domain_size):
        for j in range(model.domain_size):
            k = arrow(i, j)
            if k == arrow(k, k):
                leq[i, j] = True
            else:
                leq[i, j] = False
    return leq

def get_leq_from_fusion(model: Model):
    dot = model.as_function("*")
    leq = np.zeros((model.domain_size, model.domain_size),dtype=bool)
    for i in range(model.domain_size):
        for j in range(model.domain_size):
            if i == dot(i, j):
                leq[i, j] = True
            else:
                leq[i, j] = False
    return leq

def get_leq(model: Model):
    return get_leq_from_idempotent_residual(model)

def adjacency_matrix(le: np.ndarray):
    w = le.astype(np.uint8) @ le.astype(np.uint8)
    return le & (w == 0)

def get_le(leq: np.ndarray):
    le = leq.copy()
    np.fill_diagonal(le, False)
    return le

def get_graphs(model: Model):
    le = get_le(get_leq_from_idempotent_residual(model))
    fusion_le = get_le(get_leq_from_fusion(model))
    adj_le = adjacency_matrix(le)
    adj_fusion_le = adjacency_matrix(fusion_le)
    leq_graph = nx.from_numpy_array(adj_le,create_using=nx.DiGraph)
    fusion_leq_graph = nx.from_numpy_array(adj_fusion_le,create_using=nx.DiGraph)
    return leq_graph, fusion_leq_graph

def get_models(model_filename: str):
    with open(model_filename) as f:
        buffer = Mace4InterpretationBuffer()
        for line in f:
            for model in buffer.feed(line):
                model = model[0]
                yield model

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    Mace4Reader = ua.io.Mace4Reader
    from draw_orders import icrps_pdf
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str)
    parser.add_argument("-o", "--output", type=str)
    args = parser.parse_args()
    model_filename = Path(args.input)
    pdf_filename = args.output
    if pdf_filename is None:
        pdf_filename = model_filename.with_suffix(".pdf")
    else:
        pdf_filename = Path(pdf_filename)
    models = get_models(model_filename)
    icrps_pdf(models, pdf_filename)
    print(f"PDF saved to {pdf_filename}")