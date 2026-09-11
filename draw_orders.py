import matplotlib.pyplot as plt
import matplotlib.backends.backend_pdf
import matplotlib.colors as mcolors
import colorsys
import math
import networkx as nx
from pyp9m4 import Model, parse_models_from_file
import re
import sys

from typing import Iterable

from icrp import get_graphs as icrp_to_graphs
from icrl import get_graphs as icrl_to_graphs, get_join_irreducibles_from_graph

# Layout scores: node/edge collisions are much worse than ordinary crossings.
_CROSSING_PENALTY = 1.0
_NODE_HIT_PENALTY = 1000.0
_EDGE_OVERLAP_PENALTY = 1000.0
_NODE_OVERLAP_PENALTY = 1000.0
_NODE_HIT_RADIUS = 0.28
_NODE_MIN_DIST = 0.55
_LEVEL_X_GAP = 0.75
_EDGE_OVERLAP_DIST = 0.08
_EDGE_OVERLAP_MIN_LEN = 0.35

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


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _proper_segment_intersect(p1, p2, q1, q2):
    """True if the open segments p1-p2 and q1-q2 cross."""
    if p1 == q1 or p1 == q2 or p2 == q1 or p2 == q2:
        return False
    o1 = _orient(p1, p2, q1)
    o2 = _orient(p1, p2, q2)
    o3 = _orient(q1, q2, p1)
    o4 = _orient(q1, q2, p2)
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def _point_hits_segment(p, a, b, radius=_NODE_HIT_RADIUS):
    """True if p lies near the interior of segment a-b."""
    ax, ay = a
    bx, by = b
    px, py = p
    vx, vy = bx - ax, by - ay
    len2 = vx * vx + vy * vy
    if len2 < 1e-18:
        return False
    t = ((px - ax) * vx + (py - ay) * vy) / len2
    if t <= 0.06 or t >= 0.94:
        return False
    qx = ax + t * vx
    qy = ay + t * vy
    return math.hypot(px - qx, py - qy) < radius


def _segments_overlap(a1, a2, b1, b2, dist_tol=_EDGE_OVERLAP_DIST, min_len=_EDGE_OVERLAP_MIN_LEN):
    """True if two segments are nearly collinear and overlap in interior length."""
    va = (a2[0] - a1[0], a2[1] - a1[1])
    vb = (b2[0] - b1[0], b2[1] - b1[1])
    la = math.hypot(*va)
    lb = math.hypot(*vb)
    if la < 1e-12 or lb < 1e-12:
        return False
    if abs(va[0] * vb[1] - va[1] * vb[0]) / (la * lb) > 0.08:
        return False
    dist = abs(va[0] * (b1[1] - a1[1]) - va[1] * (b1[0] - a1[0])) / la
    if dist > dist_tol:
        return False

    def proj(p):
        return ((p[0] - a1[0]) * va[0] + (p[1] - a1[1]) * va[1]) / la

    pa1, pa2 = 0.0, la
    pb1, pb2 = proj(b1), proj(b2)
    if pb1 > pb2:
        pb1, pb2 = pb2, pb1
    overlap = min(max(pa1, pa2), pb2) - max(min(pa1, pa2), pb1)
    share_vertex = a1 == b1 or a1 == b2 or a2 == b1 or a2 == b2
    if share_vertex:
        return overlap > min_len
    return overlap > min_len


def _positions_from_order(order_by_level, max_level):
    pos = {}
    for level in range(max_level + 1):
        nodes_at_level = order_by_level.get(level, [])
        n = len(nodes_at_level)
        if n == 0:
            continue
        for i, node in enumerate(nodes_at_level):
            x = (i - (n - 1) / 2) * _LEVEL_X_GAP
            pos[node] = (x, float(level))
    return pos


def _layout_cost(G, pos):
    """Score a placement: crossings plus high penalties for node hits and overlaps."""
    nodes = [n for n in G.nodes() if n in pos]
    edges = [(u, v) for u, v in G.edges() if u in pos and v in pos]
    cost = 0.0

    for i, a in enumerate(nodes):
        pa = pos[a]
        for b in nodes[i + 1 :]:
            pb = pos[b]
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if d < _NODE_MIN_DIST:
                cost += _NODE_OVERLAP_PENALTY

    for u, v in edges:
        pu, pv = pos[u], pos[v]
        y0, y1 = pu[1], pv[1]
        lo, hi = (y0, y1) if y0 < y1 else (y1, y0)
        for n in nodes:
            if n == u or n == v:
                continue
            pn = pos[n]
            if not (lo < pn[1] < hi):
                continue
            if _point_hits_segment(pn, pu, pv):
                cost += _NODE_HIT_PENALTY

    for i, (u1, v1) in enumerate(edges):
        p1, p2 = pos[u1], pos[v1]
        for u2, v2 in edges[i + 1 :]:
            q1, q2 = pos[u2], pos[v2]
            if _proper_segment_intersect(p1, p2, q1, q2):
                cost += _CROSSING_PENALTY
            if _segments_overlap(p1, p2, q1, q2):
                cost += _EDGE_OVERLAP_PENALTY
    return cost


def _real_positions(order_by_level, max_level, dummies):
    pos = _positions_from_order(order_by_level, max_level)
    if dummies:
        pos = {n: xy for n, xy in pos.items() if n not in dummies}
    return pos


def _order_cost(G, order_by_level, max_level, dummies=frozenset()):
    return _layout_cost(G, _real_positions(order_by_level, max_level, dummies))


def _copy_order(order):
    return {lev: list(nodes) for lev, nodes in order.items()}


def _with_dummies(G, levels):
    """Insert dummy vertices on intermediate ranks so long edges occupy x-slots."""
    H = nx.DiGraph()
    H.add_nodes_from(G.nodes())
    dummy_levels = dict(levels)
    dummies = set()
    dummy_id = 0
    for u, v in G.edges():
        lu, lv = levels[u], levels[v]
        if lu > lv:
            u, v = v, u
            lu, lv = lv, lu
        if lv - lu <= 1:
            H.add_edge(u, v)
            continue
        prev = u
        for y in range(lu + 1, lv):
            d = ("_dummy", dummy_id)
            dummy_id += 1
            dummies.add(d)
            dummy_levels[d] = y
            H.add_node(d)
            H.add_edge(prev, d)
            prev = d
        H.add_edge(prev, v)
    return H, dummy_levels, dummies


def _barycenter_refine_orders(
    G, levels, level_groups, max_level, score_graph=None, dummies=None, iterations=24
):
    """
    Order nodes within each level to reduce layout cost (barycenter heuristic),
    trying natural and reversed initial orders and keeping the better result.
    """
    score_graph = G if score_graph is None else score_graph
    dummies = frozenset() if dummies is None else frozenset(dummies)
    if max_level <= 0:
        return {
            0: sorted(level_groups.get(0, []), key=_node_sort_key),
        }

    best_order = None
    best_cost = None

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

            cost = _order_cost(score_graph, order, max_level, dummies)
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_order = _copy_order(order)

        cost = _order_cost(score_graph, order, max_level, dummies)
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_order = _copy_order(order)

    return _improve_order_by_swaps(
        score_graph, best_order, max_level, best_cost, dummies=dummies
    )


def _improve_order_by_swaps(G, order, max_level, current_cost, max_rounds=40, dummies=frozenset()):
    """Adjacent swaps on each level, accepting moves that lower the layout cost."""
    order = _copy_order(order)
    cost = (
        current_cost
        if current_cost is not None
        else _order_cost(G, order, max_level, dummies)
    )
    for _ in range(max_rounds):
        improved = False
        for lev in range(max_level + 1):
            seq = order[lev]
            for i in range(len(seq) - 1):
                seq[i], seq[i + 1] = seq[i + 1], seq[i]
                new_cost = _order_cost(G, order, max_level, dummies)
                if new_cost < cost:
                    cost = new_cost
                    improved = True
                else:
                    seq[i], seq[i + 1] = seq[i + 1], seq[i]
        if not improved:
            break
    return order


def _nudge_positions(G, pos, order_by_level, max_level, steps=13, passes=8):
    """Shift nodes horizontally, keeping order, to dodge node hits and overlaps."""
    pos = {n: (float(xy[0]), float(xy[1])) for n, xy in pos.items()}
    best = _layout_cost(G, pos)
    if best == 0:
        return pos
    extra = 2.0 * _LEVEL_X_GAP
    for _ in range(passes):
        improved = False
        for lev in range(max_level + 1):
            seq = [n for n in order_by_level.get(lev, []) if n in pos]
            if not seq:
                continue
            xs = [pos[n][0] for n in seq]
            n = len(seq)
            min_sep = _NODE_MIN_DIST
            for i, node in enumerate(seq):
                lo = xs[i - 1] + min_sep if i else xs[i] - extra
                hi = xs[i + 1] - min_sep if i + 1 < n else xs[i] + extra
                if hi <= lo:
                    continue
                y = pos[node][1]
                local_best_x = xs[i]
                for s in range(steps):
                    x = lo + (hi - lo) * s / (steps - 1) if steps > 1 else xs[i]
                    pos[node] = (x, y)
                    c = _layout_cost(G, pos)
                    if c < best:
                        best = c
                        local_best_x = x
                        improved = True
                pos[node] = (local_best_x, y)
                xs[i] = local_best_x
                if best == 0:
                    return pos
        if not improved:
            break
    return pos


def hasse_layout(G):
    """Create a hierarchical layout suitable for Hasse diagrams (crossing reduction)."""
    levels = compute_levels(G)
    if not levels:
        return nx.spring_layout(G)

    layered, layered_levels, dummies = _with_dummies(G, levels)
    level_groups = {}
    for node, level in layered_levels.items():
        level_groups.setdefault(level, []).append(node)

    max_level = max(layered_levels.values())
    order_by_level = _barycenter_refine_orders(
        layered,
        layered_levels,
        level_groups,
        max_level,
        score_graph=G,
        dummies=dummies,
    )
    pos = _real_positions(order_by_level, max_level, dummies)
    real_order = {
        lev: [n for n in nodes if n not in dummies]
        for lev, nodes in order_by_level.items()
    }
    return _nudge_positions(G, pos, real_order, max_level)


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

def draw_idempotent_crl(model: Model, name: str = "0", n: int = 0):
    universe = list(range(model.domain_size))
    card = model.domain_size
    if name == "0":
        name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
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
        name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
        _terminal_status(f"PDF page {i+1}: drawing model {name}...")
        fig = draw_idempotent_crl(model)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)
    print()
    pdf.close()

def draw_icrp(model: Model):
    # Get graphs
    leq_graph, fusion_leq_graph = icrp_to_graphs(model)
    name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
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
        name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
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
    