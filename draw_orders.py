import uacalc_lib
import matplotlib.pyplot as plt
import matplotlib.backends.backend_pdf
import matplotlib.colors as mcolors
import colorsys
import networkx as nx

Mace4Reader = uacalc_lib.io.Mace4Reader
OrderedSet = uacalc_lib.lat.OrderedSet
BasicAlgebra = uacalc_lib.alg.BasicAlgebra

from typing import Iterable

from icrp import to_ordered_set as icrp_to_ordered_set

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

# Helper function to create hierarchical layout for Hasse diagram
def hasse_layout(G):
    """Create a hierarchical layout suitable for Hasse diagrams."""
    levels = compute_levels(G)
    if not levels:
        return nx.spring_layout(G)
    
    # Group nodes by level
    level_groups = {}
    for node, level in levels.items():
        if level not in level_groups:
            level_groups[level] = []
        level_groups[level].append(node)
    
    pos = {}
    max_level = max(levels.values())
    
    # Position nodes: y-coordinate based on level, x-coordinate evenly spaced within level
    for level in range(max_level + 1):
        nodes_at_level = level_groups.get(level, [])
        num_nodes = len(nodes_at_level)
        if num_nodes > 0:
            # Evenly space nodes horizontally
            for i, node in enumerate(nodes_at_level):
                x = (i - (num_nodes - 1) / 2) / max(num_nodes, 1) * 2
                y = level
                pos[node] = (x, y)
    
    return pos

def get_join_irreducibles_po(join_lattice):
    """
    Get join irreducibles as a partial order from a join lattice.
    
    Uses the new uacalc syntax: join_lattice.join_irreducibles() to get
    join irreducibles directly from the lattice.
    """
    # Get join irreducibles using the new syntax
    join_irreducibles = join_lattice.join_irreducibles()
    join_irreducibles_set = set(join_irreducibles)
    
    # Compute upper covers for each join irreducible element
    # Upper covers are the minimal elements among join irreducibles that are greater than ji
    upper_covers_list = []
    for ji in join_irreducibles:
        covers = []
        # Get all join irreducibles that are >= ji
        filter_ji = list(join_irreducibles_set.intersection(join_lattice.filter(ji)))
        upper_covers_list.append(filter_ji)
    
    # Create OrderedSet from join irreducibles
    jis_po = OrderedSet(join_irreducibles, upper_covers_list, name="JoinIrreducibles")
    return jis_po, join_irreducibles
    
def draw_poset(ax, poset: OrderedSet, title: str = "", node_colors: list[str] = [], highlight_nodes: list = []):
    graph = poset.to_networkx()
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

def draw_idempotent_crl(alg: BasicAlgebra, n: int = 0):
    join_op = None
    dot_op = None
    for op in alg.operations():
        if op.symbol().name() == "v":
            join_op = op
        if op.symbol().name() == "*":
            dot_op = op
    universe = alg.get_universe_list()
    card = len(universe)
    colors = []
    for i in range(n):
        colors.append('orange')
    for i in range(card-n):
        colors.append('lightblue')
    # View dot as meet for fusion order
    dot_lattice = uacalc_lib.lat.lattice_from_meet("FusionSemiLattice", dot_op)
    dot_poset = OrderedSet.from_lattice(dot_lattice, name="FusionSemiLatticePoset")
    dot_graph = dot_poset.to_networkx()

    # Get lattice
    join_lattice = uacalc_lib.lat.lattice_from_join("JoinLattice", join_op)
    join_poset = OrderedSet.from_lattice(join_lattice, name="JoinLatticePoset")
    join_graph = join_poset.to_networkx()

    # Get join irreducibles as a partial order and graph
    # ji_poset, original_join_irreducibles = get_join_irreducibles_po(join_lattice)
    join_irreducibles_list = [node for node in join_lattice.universe() if len(join_graph.in_edges(node)) == 1]
    # print(join_irreducibles_list)
    # ji_graph = ji_poset.to_networkx()
    
    # Create figure with three subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle(alg.name(), fontsize=14, fontweight='bold')
    
    # Draw dot graph (Fusion SemiLattice) using Hasse diagram layout
    ax1 = draw_poset(ax1, dot_poset, "Fusion SemiLattice", node_colors=colors, highlight_nodes=join_irreducibles_list)
    
    # Draw join graph (Join Lattice) using Hasse diagram layout
    ax2 = draw_poset(ax2, join_poset, "Join Lattice", node_colors=colors, highlight_nodes=join_irreducibles_list)

    # # Draw join graph (Join Irreducibles) using Hasse diagram layout
    # pos3 = hasse_layout(ji_graph)
    # nx.draw(ji_graph, pos3, ax=ax3, with_labels=True, node_color='darkred',
    #         node_size=500, font_size=10, font_weight='bold', arrows=True,
    #         arrowsize=15, edge_color='gray')
    # ax3.set_title("Join Irreducibles", fontsize=10)
    # ax3.axis('off')
    
    plt.tight_layout()
    return fig

def idempotent_crls_pdf(algebras: Iterable[BasicAlgebra], pdf_filename: str):
    pdf = matplotlib.backends.backend_pdf.PdfPages(pdf_filename)
    for alg in algebras:
        fig = draw_idempotent_crl(alg)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)
    pdf.close()

def draw_icrp(alg: BasicAlgebra):
    dot_op = None
    for op in alg.operations():
        if op.symbol().name() == "*":
            dot_op = op

    # View dot as meet for fusion order
    dot_lattice = uacalc_lib.lat.lattice_from_meet("FusionSemiLattice", dot_op)
    dot_poset = OrderedSet.from_lattice(dot_lattice, name="FusionSemiLatticePoset")

    # Get order
    poset = icrp_to_ordered_set(alg)

    # Create figure with two subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle(alg.name(), fontsize=14, fontweight='bold')
    node_colors = ['orange'] * len(alg.get_universe_list())
    # Draw dot graph (Fusion SemiLattice) using Hasse diagram layout
    ax1 = draw_poset(ax1, dot_poset, "Fusion SemiLattice", node_colors=node_colors)
    
    # Draw poset using Hasse diagram layout
    ax2 = draw_poset(ax2, poset, "Poset", node_colors=node_colors)

    plt.tight_layout()
    return fig

def icrps_pdf(algebras: Iterable[BasicAlgebra], pdf_filename: str):
    pdf = matplotlib.backends.backend_pdf.PdfPages(pdf_filename)
    for alg in algebras:
        fig = draw_icrp(alg)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)
    pdf.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str, default="simple_idempotent_distributive_crl.model")
    parser.add_argument("-o", "--output", type=str, default="simple_idempotent_distributive_crl.pdf")
    args = parser.parse_args()
    model_filename = args.input
    pdf_filename = args.output
    algebras = Mace4Reader.parse_algebra_list_from_file(model_filename)
    idempotent_crls_pdf(algebras, pdf_filename)
    print(f"PDF saved to {pdf_filename}")
    