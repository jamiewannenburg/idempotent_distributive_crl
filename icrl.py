from pyp9m4 import Model, parse_models_from_file, InterpFilter
from pyp9m4.options import InterpfilterCliOptions
import numpy as np
import networkx as nx
from icrp import get_fusion_graph, get_fusion_leq, get_fusion_le, get_graph_from_le, get_le, matrix_to_string, op_to_string
import tempfile
from axioms import idcrl_axioms
import os
import re
import itertools
from collections.abc import Callable

def to_interpretation_text(number: str, cardinality: int, meet: Callable, join: Callable, dot: Callable, arrow: Callable, leq: np.ndarray, e: int):
    embedding = f"interpretation( {cardinality}, [number = {number}, seconds = 0], [\n"
    embedding += f"    function(*(_,_), [{op_to_string(dot, cardinality)}]),\n"
    embedding += f"    function(^(_,_), [{op_to_string(meet, cardinality)}]),\n"
    embedding += f"    function(v(_,_), [{op_to_string(join, cardinality)}]),\n"
    embedding += f"    function(\\(_,_), [{op_to_string(arrow, cardinality)}]),\n"
    embedding += f"    relation(<=(_,_), [{matrix_to_string(leq, cardinality)}]),\n"
    embedding += f"    function(e, [{e}])]).\n"
    return embedding

def get_leq_from_meet_operation(meet: Callable, cardinality: int):
    leq =np.zeros((cardinality, cardinality),dtype=bool)
    for i,j in itertools.product(range(cardinality), repeat=2):
        if i == meet(i, j):
            leq[i, j] = True
        else:
            leq[i, j] = False
    return leq

def get_leq_from_meet(model: Model):
    meet = model.as_function("^")
    return get_leq_from_meet_operation(meet, model.domain_size)

def get_le_from_meet(model: Model):
    return get_le(get_leq_from_meet(model))

def get_graph_from_meet(model: Model):
    return get_graph_from_le(get_le_from_meet(model))

def get_graphs(model: Model):
    le_graph = get_graph_from_meet(model)
    fusion_le_graph = get_fusion_graph(model)
    return le_graph, fusion_le_graph


def get_leq_from_join(model: Model):
    join = model.as_function("v")
    leq = np.zeros((model.domain_size, model.domain_size),dtype=bool)
    for i in range(model.domain_size):
        for j in range(model.domain_size):
            if i == join(i, j):
                leq[j, i] = True
            else:
                leq[j, i] = False
    return leq

def get_le_from_join(model: Model):
    return get_le(get_leq_from_join(model))

def get_graph_from_join(model: Model):
    return get_graph_from_le(get_le_from_join(model))

def get_join_irreducibles_from_graph(le_graph: nx.DiGraph):
    join_irreducibles_list = [node for node in le_graph.nodes() if len(le_graph.in_edges(node)) == 1]
    return join_irreducibles_list

def get_join_irreducibles(model: Model):
    le_graph = get_graph_from_meet(model)
    return get_join_irreducibles_from_graph(le_graph)

def is_idcrl(model: Model):
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.write(idcrl_axioms.encode('utf-8'))
    temp_file.close()
    result = InterpFilter().run(input=model.raw,formulas_file=temp_file.name,test='all_true')
    os.unlink(temp_file.name)
    m = re.search("checked 1, passed 1", result.stdout)
    if m:
        return True
    else:
        print(result.stdout)
        return False

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from draw_orders import idempotent_crls_pdf
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
    for model in models:
        assert is_idcrl(model), f"model {model} is not an idempotent CRL"
    idempotent_crls_pdf(models, pdf_filename)
    print(f"PDF saved to {pdf_filename}")