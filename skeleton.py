from pyp9m4 import Model, parse_models_from_file
import re
import networkx as nx
import numpy as np
import matplotlib.colors as mcolors
import colorsys
from draw_orders import hasse_layout
from icrp import get_graph_from_idempotent_residual, get_fusion_graph

def draw_closed_graph(ax, graph: nx.DiGraph, title: str = "", node_colors: list[str] = [], highlight_nodes: list = []):
    if len(node_colors) == 0:
        node_colors_copy = ['lightblue'] * len(graph.nodes())
    else:
        node_colors_copy = node_colors.copy()
    for node in highlight_nodes:
        node_colors_copy[node] = 'lightblue'
    nx.draw(graph, pos=hasse_layout(graph), ax=ax, with_labels=True, node_color=node_colors_copy,
            node_size=500, font_size=10, font_weight='bold', arrows=True, 
            arrowsize=15, edge_color='gray')
    ax.set_title(title, fontsize=10)
    ax.axis('off')
    return ax


def arrow_e(model: Model):
    arrow = model.as_function("\\")
    e = model.get_value("e")
    return lambda x: arrow(x, e)

def arrow_e_arrow_e(model: Model):
    arrow_e_function = arrow_e(model)
    return lambda x: arrow_e_function(arrow_e_function(x))


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
        pdf_filename = output_folder / (model_filename.stem+"_skeleton.pdf")
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
        arrow_e_function = arrow_e(model)
        arrow_e_arrow_e_nucleus = arrow_e_arrow_e(model)
        # nuclear image
        closed_elements = []
        table = []
        columns = []
        rows = [r'$x \to e$', r'$(x \to e) \to e$']
        colors = []
        for i in range(n):
            columns.append(i)
            ae = arrow_e_function(i)
            aeae = arrow_e_arrow_e_nucleus(i)
            colors.append('orange')
            if i == aeae:
                closed_elements.append(i)
            table.append([ae, aeae])
        table = np.array(table).T.tolist()

        le_graph = get_graph_from_idempotent_residual(model)
        fusion_graph = get_fusion_graph(model)
        fig, (ax1,ax2) = plt.subplots(1, 2, figsize=(10, 4))
        ax1 = draw_closed_graph(ax1, fusion_graph, title="Fusion SemiLattice", node_colors=colors, highlight_nodes=closed_elements)
        ax2 = draw_closed_graph(ax2, le_graph, title="Lattice", node_colors=colors, highlight_nodes=closed_elements)
        table_ax = fig.add_axes([0.1, 0.1, 0.8, 0.1])
        table_ax.table(cellText=table, 
            # colLabels=columns,
            rowLabels=rows, 
            loc='bottom')
        
        table_ax.axis('off')
        fig.suptitle(f"model{name}", fontsize=14, fontweight='bold')
        
        # plt.tight_layout()
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)
        # except Exception as e:
        #     print(f"model {name}: error in expansion generation: {e}")
        #     print(model)
    pdf.close()