import uacalc_lib
import matplotlib.pyplot as plt
import matplotlib.backends.backend_pdf
import networkx as nx

Mace4Reader = uacalc_lib.io.Mace4Reader
algebras = Mace4Reader.parse_algebra_list_from_file("idempotent_distributive_crl.model")

# Create PDF file
pdf_filename = "algebra_orders.pdf"
pdf = matplotlib.backends.backend_pdf.PdfPages(pdf_filename)


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
    
for alg in algebras:
    join_op = None
    dot_op = None
    for op in alg.operations():
        if op.symbol().name() == "v":
            join_op = op
        if op.symbol().name() == "*":
            dot_op = op

    # View dot as meet for fusion order
    dot_lattice = uacalc_lib.lat.lattice_from_meet("FusionSemiLattice", dot_op)
    dot_poset = dot_lattice.to_ordered_set(name="FusionSemiLatticePoset")
    dot_graph = dot_poset.to_networkx()

    # get join irreducibles as a partial order for join lattice
    join_lattice = uacalc_lib.lat.lattice_from_join("JoinLattice", join_op)
    join_poset = join_lattice.join_irreducibles_po()
    join_graph = join_poset.to_networkx()
    
    # Create figure with two subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle(alg.name(), fontsize=14, fontweight='bold')
    
    # Draw dot graph (Fusion SemiLattice) using Hasse diagram layout
    pos1 = hasse_layout(dot_graph)
    nx.draw(dot_graph, pos1, ax=ax1, with_labels=True, node_color='lightblue',
            node_size=500, font_size=10, font_weight='bold', arrows=True, 
            arrowsize=15, edge_color='gray')
    ax1.set_title("Fusion SemiLattice", fontsize=10)
    ax1.axis('off')
    
    # Draw join graph (Join Irreducibles) using Hasse diagram layout
    pos2 = hasse_layout(join_graph)
    nx.draw(join_graph, pos2, ax=ax2, with_labels=True, node_color='lightcoral',
            node_size=500, font_size=10, font_weight='bold', arrows=True,
            arrowsize=15, edge_color='gray')
    ax2.set_title("Join Irreducibles", fontsize=10)
    ax2.axis('off')
    
    plt.tight_layout()
    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)

pdf.close()
print(f"PDF saved to {pdf_filename}")
    