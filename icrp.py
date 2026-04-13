from pyp9m4 import Model, parse_models_from_file
import numpy as np
import networkx as nx
import itertools

from typing import Function

def to_interpretation_text(number: str, cardinality: int, dot: Function, arrow: Function, leq: np.ndarray, e: int):
    embedding = f"interpretation( {cardinality}, [number = {number}, seconds = 0], [\n"
    embedding += f"    function(*(_,_), [{op_to_string(dot, cardinality)}]),\n"
    embedding += f"    function(\\(_,_), [{op_to_string(arrow, cardinality)}]),\n"
    embedding += f"    relation(<=(_,_), [{matrix_to_string(leq, cardinality)}]),\n"
    embedding += f"    function(e, [{e}]]).\n"
    return embedding

def matrix_to_string(matrix, cardinality: int):
    table = []
    for i,j in itertools.product(range(cardinality), repeat=2):
        if i!=0 and j == 0:
            table.append('\n                       '+str(int(matrix[i,j])))
        else:
            table.append(str(int(matrix[i,j])))
    return ','.join(table)

def op_to_string(op, cardinality: int):
    s = ""
    table = []
    for i,j in itertools.product(range(cardinality), repeat=2):
        if i!=0 and j == 0:
            table.append('\n                      '+str(int(op(i,j))))
        else:
            table.append(str(int(op(i,j))))
    return ','.join(table)

def get_le(leq: np.ndarray):
    le = leq.copy()
    np.fill_diagonal(le, False)
    return le

def get_leq_from_idempotent_residual_operation(arrow: Function, cardinality: int):
    leq = np.zeros((cardinality, cardinality),dtype=bool)
    for i,j in itertools.product(range(cardinality), repeat=2):
        k = arrow(i, j)
        if k == arrow(k, k):
            leq[i, j] = True
        else:
            leq[i, j] = False
    return leq

def get_leq_from_idempotent_residual(model: Model):
    arrow = model.as_function("\\")
    return get_leq_from_idempotent_residual_operation(arrow, model.domain_size)

def get_le_from_idempotent_residual(model: Model):
    return get_le(get_leq_from_idempotent_residual(model))

def get_leq_from_fusion_operation(dot: Function, cardinality: int):
    leq = np.zeros((cardinality, cardinality),dtype=bool)
    for i,j in itertools.product(range(cardinality), repeat=2):
        if i == dot(i, j):
            leq[i, j] = True
        else:
            leq[i, j] = False
    return leq

def get_fusion_leq(model: Model):
    dot = model.as_function("*")
    return get_leq_from_fusion_operation(dot, model.domain_size)

def get_fusion_le(model: Model):
    return get_le(get_fusion_leq(model))

def adjacency_matrix(le: np.ndarray):
    w = le.astype(np.uint8) @ le.astype(np.uint8)
    return le & (w == 0)

def get_graph_from_le(le: np.ndarray):
    adj = adjacency_matrix(le)
    return nx.from_numpy_array(adj,create_using=nx.DiGraph)

def get_graph_from_idempotent_residual(model: Model):
    return get_graph_from_le(get_le_from_idempotent_residual(model))

def get_fusion_graph(model: Model):
    return get_graph_from_le(get_fusion_le(model))

def get_graphs(model: Model):
    le_graph = get_graph_from_idempotent_residual(model)
    fusion_le_graph = get_fusion_graph(model)
    return le_graph, fusion_le_graph

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from draw_orders import icrps_pdf
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str)
    parser.add_argument("-o", "--output", type=str)
    args = parser.parse_args()
    model_filename = Path(args.input)
    pdf_filename = args.output
    if pdf_filename is None:
        output_folder = Path('output')
        pdf_filename = output_folder / model_filename.with_suffix(".pdf").name
    else:
        pdf_filename = Path(pdf_filename)
    models = parse_models_from_file(model_filename)
    icrps_pdf(models, pdf_filename)
    print(f"PDF saved to {pdf_filename}")