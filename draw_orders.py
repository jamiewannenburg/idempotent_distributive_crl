import matplotlib.pyplot as plt
import matplotlib.backends.backend_pdf
import matplotlib.colors as mcolors
import colorsys
import networkx as nx
from pyp9m4 import Model, parse_models_from_file
import re
import sys

from typing import Iterable

from icrp import get_graphs as icrp_to_graphs
from icrl import get_graphs as icrl_to_graphs, get_join_irreducibles_from_graph

# Helper function to compute levels for Hasse diagram layout
def compute_levels(G):
    """Compute the level (longest path from minimal elements) for each node."""
    if len(G) == 0:
        return {}
    # Find minimal elements (nodes with no incoming edges)
    in_degree = dict(G.in_degree())
    minimal = [n for n in G.nodes() if in_degree[n] == 0]
    
    if not minimal:
        # If no minimal elements, all nodes are at level 0
        return {n: 0 for n in G.nodes()}
    
    # Initialize levels: minimal elements are at level 0
    levels = {m: 0 for m in minimal}
    
    # Topological sort to process nodes in order
    # Compute longest path from minimal elements
    remaining = set(G.nodes()) - set(minimal)
    
    while remaining:
        progress = False
        for node in list(remaining):
            # Check if all predecessors have been processed
            preds = list(G.predecessors(node))
            if all(p in levels for p in preds):
                # Level is max of all predecessors' levels + 1
                if preds:
                    levels[node] = max(levels[p] for p in preds) + 1
                else:
                    levels[node] = 0
                remaining.remove(node)
                progress = True
        
        if not progress:
            # Handle cycles or disconnected components
            for node in remaining:
                levels[node] = 0
            break
    
    return levels


def _node_sort_key(n):
    return (str(n), n)


def _crossings_between_layers(G, levels, order_lo, order_hi, lo, hi):
    """Count edge crossings between nodes on level lo and level hi (hi == lo + 1)."""
    idx_lo = {n: i for i, n in enumerate(order_lo)}
    idx_hi = {n: i for i, n in enumerate(order_hi)}
    edge_pairs = []
    for u, v in G.edges():
        if levels.get(u) == lo and levels.get(v) == hi:
            if u in idx_lo and v in idx_hi:
                edge_pairs.append((idx_lo[u], idx_hi[v]))
    c = 0
    for i in range(len(edge_pairs)):
        x1, y1 = edge_pairs[i]
        for j in range(i + 1, len(edge_pairs)):
            x2, y2 = edge_pairs[j]
            if x1 == x2 or y1 == y2:
                continue
            if (x1 < x2) != (y1 < y2):
                c += 1
    return c


def _total_adjacent_crossings(G, levels, order_by_level, max_level):
    t = 0
    for lev in range(max_level):
        t += _crossings_between_layers(
            G, levels, order_by_level[lev], order_by_level[lev + 1], lev, lev + 1
        )
    return t


def _barycenter_refine_orders(G, levels, level_groups, max_level, iterations=24):
    """
    Order nodes within each level to reduce crossings (barycenter heuristic),
    trying natural and reversed initial orders and keeping the better result.
    """
    if max_level <= 0:
        return {
            0: sorted(level_groups.get(0, []), key=_node_sort_key),
        }

    best_order = None
    best_crossings = None

    for reverse_initial in (False, True):
        order = {}
        for lev in range(max_level + 1):
            nodes = sorted(level_groups.get(lev, []), key=_node_sort_key)
            if reverse_initial:
                nodes = list(reversed(nodes))
            order[lev] = nodes

        for _ in range(iterations):
            for lev in range(1, max_level + 1):
                prev_idx = {n: i for i, n in enumerate(order[lev - 1])}
                cur_idx = {n: i for i, n in enumerate(order[lev])}

                def key_down(v, lev=lev, prev_idx=prev_idx, cur_idx=cur_idx):
                    preds = [u for u in G.predecessors(v) if levels.get(u) == lev - 1]
                    if preds:
                        b = sum(prev_idx[u] for u in preds) / len(preds)
                    else:
                        b = cur_idx[v]
                    return (b, *_node_sort_key(v))

                order[lev].sort(key=key_down)

            for lev in range(max_level - 1, -1, -1):
                next_idx = {n: i for i, n in enumerate(order[lev + 1])}
                cur_idx = {n: i for i, n in enumerate(order[lev])}

                def key_up(v, lev=lev, next_idx=next_idx, cur_idx=cur_idx):
                    succs = [w for w in G.successors(v) if levels.get(w) == lev + 1]
                    if succs:
                        b = sum(next_idx[w] for w in succs) / len(succs)
                    else:
                        b = cur_idx[v]
                    return (b, *_node_sort_key(v))

                order[lev].sort(key=key_up)

        crossings = _total_adjacent_crossings(G, levels, order, max_level)
        if best_crossings is None or crossings < best_crossings:
            best_crossings = crossings
            best_order = {lev: list(nodes) for lev, nodes in order.items()}

    return best_order


# Helper function to create hierarchical layout for Hasse diagram
def hasse_layout(G):
    """Create a hierarchical layout suitable for Hasse diagrams (crossing reduction)."""
    levels = compute_levels(G)
    if not levels:
        return nx.spring_layout(G)

    level_groups = {}
    for node, level in levels.items():
        level_groups.setdefault(level, []).append(node)

    max_level = max(levels.values())
    order_by_level = _barycenter_refine_orders(G, levels, level_groups, max_level)

    pos = {}
    for level in range(max_level + 1):
        nodes_at_level = order_by_level.get(level, [])
        num_nodes = len(nodes_at_level)
        if num_nodes > 0:
            for i, node in enumerate(nodes_at_level):
                x = (i - (num_nodes - 1) / 2) / max(num_nodes, 1) * 2
                y = level
                pos[node] = (x, y)

    return pos

def _terminal_status(msg: str, *, stream=None) -> None:
    """Print msg on one terminal line, replacing the previous status line."""
    stream = stream or sys.stdout
    stream.write("\r" + msg + "\033[K")
    stream.flush()

def draw_graph(ax, graph: nx.DiGraph, title: str = "", node_colors: list[str] = [], highlight_nodes: list = []):
    if len(node_colors) == 0:
        node_colors_copy = ['lightblue'] * len(graph.nodes())
    else:
        node_colors_copy = node_colors.copy()
    node_rgb = [mcolors.to_rgb(color) for color in node_colors]
    node_hls = [colorsys.rgb_to_hls(*c) for c in node_rgb]
    for node in highlight_nodes:
        c = node_hls[node]
        node_colors_copy[node] = mcolors.to_hex(colorsys.hls_to_rgb(c[0], c[1]*0.7, c[2])) # darken the color
    nx.draw(graph, pos=hasse_layout(graph), ax=ax, with_labels=True, node_color=node_colors_copy,
            node_size=500, font_size=10, font_weight='bold', arrows=True, 
            arrowsize=15, edge_color='gray')
    ax.set_title(title, fontsize=10)
    ax.axis('off')
    return ax

def draw_idempotent_crl(model: Model, n: int = 0):
    universe = list(range(model.domain_size))
    card = model.domain_size
    name = re.search(r"number = (\d+)",model.raw).group(1)
    colors = []
    for i in range(n):
        colors.append('orange')
    for i in range(card-n):
        colors.append('lightblue')
    le_graph, dot_graph = icrl_to_graphs(model)
    join_irreducibles_list = get_join_irreducibles_from_graph(le_graph)
    
    # Create figure with three subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle(f"model{name}", fontsize=14, fontweight='bold')
    
    # Draw dot graph (Fusion SemiLattice) using Hasse diagram layout
    ax1 = draw_graph(ax1, dot_graph, "Fusion SemiLattice", node_colors=colors, highlight_nodes=join_irreducibles_list)
    
    # Draw join graph (Join Lattice) using Hasse diagram layout
    ax2 = draw_graph(ax2, le_graph, "Lattice", node_colors=colors, highlight_nodes=join_irreducibles_list)
    
    plt.tight_layout()
    return fig

def idempotent_crls_pdf(models: Iterable[Model], pdf_filename: str):
    pdf = matplotlib.backends.backend_pdf.PdfPages(pdf_filename)
    for i, model in enumerate(models):
        name = re.search(r"number = (\d+)",model.raw).group(1)
        _terminal_status(f"PDF page {i+1}: drawing model {name}...")
        fig = draw_idempotent_crl(model)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)
    print()
    pdf.close()

def draw_icrp(model: Model):
    # Get graphs
    leq_graph, fusion_leq_graph = icrp_to_graphs(model)
    name = re.search(r"number = (\d+)",model.raw).group(1)
    # Create figure with two subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle(f"model{name}", fontsize=14, fontweight='bold')
    node_colors = ['orange'] * model.domain_size
    # Draw dot graph (Fusion SemiLattice) using Hasse diagram layout
    ax1 = draw_graph(ax1, fusion_leq_graph, "Fusion SemiLattice", node_colors=node_colors)
    
    # Draw poset using Hasse diagram layout
    ax2 = draw_graph(ax2, leq_graph, "Poset", node_colors=node_colors)

    plt.tight_layout()
    return fig

def icrps_pdf(models: Iterable[Model], pdf_filename: str):
    pdf = matplotlib.backends.backend_pdf.PdfPages(pdf_filename)
    
    for i, model in enumerate(models):
        name = re.search(r"number = (\d+)",model.raw).group(1)
        _terminal_status(f"PDF page {i+1}: drawing model {name}...")
        fig = draw_icrp(model)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)
    print()
    pdf.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str, default="model_outputs/simple_idempotent_distributive_crl.model")
    parser.add_argument("-o", "--output", type=str, default="output/simple_idempotent_distributive_crl.pdf")
    args = parser.parse_args()
    model_filename = args.input
    pdf_filename = args.output
    models = parse_models_from_file(model_filename)
    idempotent_crls_pdf(models, pdf_filename)
    print(f"PDF saved to {pdf_filename}")
    