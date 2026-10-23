"""Generate standalone HTML viewers for algebra visualizations.

Reads algebras from .ua, .model, or .json formats and produces a single
self-contained HTML file with:
- Interactive Hasse diagram (zoomable/pannable)
- Operation tables (virtualized for large algebras)
- Element highlighting and search
- Term evaluation for free algebras
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
from pyp9m4 import Model, parse_models_from_file

from algebra_export import AlgebraExportData, model_to_export_data
from draw_orders import hasse_layout
from icrp import get_leq_from_idempotent_residual, adjacency_matrix, get_le
from icrl import get_leq_from_meet


def load_algebra_from_json(json_path: Path) -> AlgebraExportData:
    """Load algebra from common JSON format."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    
    # Parse operations
    operations = {}
    for symbol, op_data in data["operations"].items():
        arity = op_data["arity"]
        table = np.array(op_data["table"]) if arity > 0 else op_data["table"]
        operations[symbol] = {"arity": arity, "table": table}
    
    # Parse relations
    relations = None
    if "relations" in data and data["relations"]:
        relations = {}
        for symbol, rel_data in data["relations"].items():
            arity = rel_data["arity"]
            table = np.array(rel_data["table"], dtype=bool)
            relations[symbol] = {"arity": arity, "table": table}
    
    # Parse order
    order_relation = None
    if "orderRelation" in data:
        order_relation = np.array(data["orderRelation"], dtype=bool)
    
    order_covers = None
    if "orderCovers" in data:
        order_covers = [tuple(edge) for edge in data["orderCovers"]]
    
    # Parse free algebra data
    is_free = data.get("isFree", False)
    generator_index = data.get("generatorIndex")
    representative_terms = data.get("representativeTerms")
    layout_positions = None
    if "layoutPositions" in data:
        layout_positions = {int(k): tuple(v) for k, v in data["layoutPositions"].items()}
    
    return AlgebraExportData(
        name=data["name"],
        cardinality=data["cardinality"],
        operations=operations,
        relations=relations,
        order_type=data.get("orderType"),
        order_relation=order_relation,
        order_covers=order_covers,
        is_free=is_free,
        generator_index=generator_index,
        representative_terms=representative_terms,
        layout_positions=layout_positions,
    )


def load_algebra_from_uacalc(ua_path: Path) -> AlgebraExportData:
    """Load algebra from UACalc .ua file."""
    from uacalc_lib import io as ua_io
    
    algebra = ua_io.parse_algebra_file(str(ua_path))
    
    # Extract operations
    operations = {}
    for op in algebra.operations():
        symbol = op.symbol().name()
        arity = op.arity()
        
        if arity == 0:
            table = op.valueAt([])
        else:
            # Build operation table
            if arity == 1:
                table = np.array([op.valueAt([i]) for i in range(algebra.cardinality())])
            elif arity == 2:
                table = np.array([[op.valueAt([i, j]) for j in range(algebra.cardinality())]
                                  for i in range(algebra.cardinality())])
            else:
                # Higher arity - flatten representation
                table = []
                def enumerate_tuples(n, k):
                    if k == 0:
                        yield []
                    else:
                        for i in range(n):
                            for rest in enumerate_tuples(n, k - 1):
                                yield [i] + rest
                
                for args in enumerate_tuples(algebra.cardinality(), arity):
                    table.append(op.valueAt(args))
                table = np.array(table)
        
        operations[symbol] = {"arity": arity, "table": table}
    
    return AlgebraExportData(
        name=algebra.name(),
        cardinality=algebra.cardinality(),
        operations=operations,
    )


def load_algebra_from_mace4(model_path: Path) -> AlgebraExportData:
    """Load algebra from Mace4 model file."""
    models = list(parse_models_from_file(model_path))
    if not models:
        raise ValueError(f"No models found in {model_path}")
    if len(models) > 1:
        print(f"Warning: multiple models in {model_path}, using first", file=sys.stderr)
    
    model = models[0]
    return model_to_export_data(model)


def compute_order_for_icrp(data: AlgebraExportData) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Compute order relation and covers for iCRP from arrow operation."""
    if "\\" not in data.operations:
        raise ValueError("iCRP algebras must have arrow operation \\")
    
    arrow_table = data.operations["\\"]["table"]
    arrow = lambda i, j: arrow_table[i, j]
    
    leq = get_leq_from_idempotent_residual_operation(arrow, data.cardinality)
    le = get_le(leq)
    adj = adjacency_matrix(le)
    
    # Extract covers from adjacency matrix
    covers = []
    for i in range(data.cardinality):
        for j in range(data.cardinality):
            if adj[i, j]:
                covers.append((i, j))
    
    return leq, covers


def get_leq_from_idempotent_residual_operation(arrow: Callable, cardinality: int) -> np.ndarray:
    """Compute leq from idempotent residual operation."""
    leq = np.zeros((cardinality, cardinality), dtype=bool)
    for i in range(cardinality):
        for j in range(cardinality):
            k = arrow(i, j)
            if k == arrow(k, k):
                leq[i, j] = True
            else:
                leq[i, j] = False
    return leq


def compute_order_for_crl(data: AlgebraExportData) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Compute order relation and covers for CRL from meet operation."""
    if "^" not in data.operations:
        raise ValueError("CRL algebras must have meet operation ^")
    
    meet_table = data.operations["^"]["table"]
    meet = lambda i, j: meet_table[i, j]
    
    leq = get_leq_from_meet_operation(meet, data.cardinality)
    le = get_le(leq)
    adj = adjacency_matrix(le)
    
    # Extract covers
    covers = []
    for i in range(data.cardinality):
        for j in range(data.cardinality):
            if adj[i, j]:
                covers.append((i, j))
    
    return leq, covers


def get_leq_from_meet_operation(meet: Callable, cardinality: int) -> np.ndarray:
    """Compute leq from meet operation."""
    leq = np.zeros((cardinality, cardinality), dtype=bool)
    for i in range(cardinality):
        for j in range(cardinality):
            if i == meet(i, j):
                leq[i, j] = True
            else:
                leq[i, j] = False
    return leq


def ensure_order_computed(data: AlgebraExportData) -> AlgebraExportData:
    """Ensure order relation and covers are computed."""
    if data.order_relation is None or data.order_covers is None:
        # Auto-detect type if not specified
        if data.order_type == "icrp" or (data.order_type is None and "\\" in data.operations):
            data.order_type = "icrp"
            data.order_relation, data.order_covers = compute_order_for_icrp(data)
        elif data.order_type == "crl" or (data.order_type is None and "^" in data.operations):
            data.order_type = "crl"
            data.order_relation, data.order_covers = compute_order_for_crl(data)
        else:
            raise ValueError("Cannot determine order type; specify 'icrp' or 'crl'")
    
    return data


def compute_layout_positions(data: AlgebraExportData) -> dict[int, tuple[float, float]]:
    """Compute Hasse diagram layout using the existing Python algorithm."""
    if data.layout_positions:
        return data.layout_positions
    
    if data.order_covers is None:
        raise ValueError("Order covers must be computed before layout")
    
    # Build graph from covers
    G = nx.DiGraph()
    G.add_nodes_from(range(data.cardinality))
    G.add_edges_from(data.order_covers)
    
    # Use existing hasse_layout
    pos = hasse_layout(G)
    
    return {node: (float(x), float(y)) for node, (x, y) in pos.items()}


def generate_html_viewer(
    data: AlgebraExportData,
    output_path: Path,
    title: str | None = None,
) -> None:
    """Generate standalone HTML viewer."""
    # Ensure order is computed
    data = ensure_order_computed(data)
    
    # Compute layout if not provided
    if data.layout_positions is None:
        data.layout_positions = compute_layout_positions(data)
    
    title = title or data.name
    
    # Prepare data for JavaScript
    js_data = {
        "name": data.name,
        "cardinality": data.cardinality,
        "operations": {},
        "orderCovers": data.order_covers,
        "layoutPositions": {str(k): list(v) for k, v in data.layout_positions.items()},
    }
    
    # Serialize operations
    for symbol, op_data in data.operations.items():
        table = op_data["table"]
        if isinstance(table, np.ndarray):
            table = table.tolist()
        js_data["operations"][symbol] = {
            "arity": op_data["arity"],
            "table": table,
        }
    
    # Free algebra data
    if data.is_free:
        js_data["isFree"] = True
        js_data["generatorIndex"] = data.generator_index
        js_data["representativeTerms"] = data.representative_terms
    
    # Generate HTML
    html = _generate_html_template(title, js_data)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def _generate_html_template(title: str, data: dict[str, Any]) -> str:
    """Generate the complete HTML template with inline JS and CSS."""
    data_json = json.dumps(data, indent=2)
    
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        header {{
            background: #2c3e50;
            color: white;
            padding: 20px 30px;
        }}
        
        header h1 {{
            font-size: 24px;
            margin-bottom: 8px;
        }}
        
        header .info {{
            font-size: 14px;
            opacity: 0.9;
        }}
        
        .content {{
            display: grid;
            grid-template-columns: 1fr 400px;
            gap: 20px;
            padding: 20px;
        }}
        
        @media (max-width: 1024px) {{
            .content {{
                grid-template-columns: 1fr;
            }}
        }}
        
        .diagram-panel {{
            border: 1px solid #ddd;
            border-radius: 4px;
            overflow: hidden;
        }}
        
        .panel-header {{
            background: #ecf0f1;
            padding: 12px 16px;
            font-weight: 600;
            border-bottom: 1px solid #ddd;
            font-size: 14px;
        }}
        
        #diagram-container {{
            position: relative;
            width: 100%;
            height: 600px;
            background: white;
            overflow: hidden;
            cursor: grab;
        }}
        
        #diagram-container:active {{
            cursor: grabbing;
        }}
        
        #diagram-svg {{
            position: absolute;
            top: 0;
            left: 0;
        }}
        
        .node {{
            cursor: pointer;
        }}
        
        .node circle {{
            fill: #3498db;
            stroke: #2980b9;
            stroke-width: 2;
        }}
        
        .node.highlighted circle {{
            fill: #e74c3c;
            stroke: #c0392b;
            stroke-width: 3;
        }}
        
        .node text {{
            fill: white;
            font-size: 14px;
            font-weight: bold;
            pointer-events: none;
            user-select: none;
        }}
        
        .edge {{
            stroke: #7f8c8d;
            stroke-width: 2;
            fill: none;
            marker-end: url(#arrowhead);
        }}
        
        .sidebar {{
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        
        .panel {{
            border: 1px solid #ddd;
            border-radius: 4px;
            overflow: hidden;
        }}
        
        .controls {{
            padding: 16px;
        }}
        
        .control-group {{
            margin-bottom: 16px;
        }}
        
        .control-group:last-child {{
            margin-bottom: 0;
        }}
        
        .control-group label {{
            display: block;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 6px;
            color: #555;
        }}
        
        input[type="text"], input[type="number"] {{
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }}
        
        input[type="text"]:focus, input[type="number"]:focus {{
            outline: none;
            border-color: #3498db;
        }}
        
        button {{
            width: 100%;
            padding: 8px 12px;
            background: #3498db;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }}
        
        button:hover {{
            background: #2980b9;
        }}
        
        button:active {{
            background: #21618c;
        }}
        
        .result {{
            margin-top: 12px;
            padding: 12px;
            background: #ecf0f1;
            border-radius: 4px;
            font-size: 13px;
            line-height: 1.5;
            min-height: 60px;
        }}
        
        .result.error {{
            background: #fadbd8;
            color: #c0392b;
        }}
        
        .result.success {{
            background: #d5f4e6;
            color: #27ae60;
        }}
        
        .result code {{
            background: rgba(0,0,0,0.1);
            padding: 2px 4px;
            border-radius: 2px;
            font-family: 'Courier New', monospace;
        }}
        
        .tables-panel {{
            max-height: 600px;
            overflow-y: auto;
        }}
        
        .table-section {{
            padding: 16px;
            border-bottom: 1px solid #eee;
        }}
        
        .table-section:last-child {{
            border-bottom: none;
        }}
        
        .table-title {{
            font-weight: 600;
            margin-bottom: 12px;
            font-size: 14px;
        }}
        
        .op-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }}
        
        .op-table th, .op-table td {{
            border: 1px solid #ddd;
            padding: 6px;
            text-align: center;
            min-width: 32px;
        }}
        
        .op-table th {{
            background: #ecf0f1;
            font-weight: 600;
        }}
        
        .op-table td {{
            background: white;
        }}
        
        .op-table td.highlighted {{
            background: #ffe5e5;
        }}
        
        .tooltip {{
            position: absolute;
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 13px;
            pointer-events: none;
            z-index: 1000;
            display: none;
            white-space: pre-line;
            max-width: 300px;
        }}
        
        .zoom-controls {{
            position: absolute;
            top: 10px;
            right: 10px;
            display: flex;
            gap: 4px;
            z-index: 10;
        }}
        
        .zoom-btn {{
            width: 32px;
            height: 32px;
            background: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            cursor: pointer;
            font-size: 18px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        .zoom-btn:hover {{
            background: #f5f5f5;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{title}</h1>
            <div class="info">
                <span id="cardinality-info"></span>
            </div>
        </header>
        
        <div class="content">
            <div class="diagram-panel">
                <div class="panel-header">Hasse Diagram</div>
                <div id="diagram-container">
                    <div class="zoom-controls">
                        <button class="zoom-btn" onclick="zoomIn()">+</button>
                        <button class="zoom-btn" onclick="zoomOut()">−</button>
                        <button class="zoom-btn" onclick="resetView()">⊙</button>
                    </div>
                    <svg id="diagram-svg">
                        <defs>
                            <marker id="arrowhead" markerWidth="10" markerHeight="10" 
                                    refX="9" refY="3" orient="auto">
                                <polygon points="0 0, 10 3, 0 6" fill="#7f8c8d" />
                            </marker>
                        </defs>
                    </svg>
                </div>
            </div>
            
            <div class="sidebar">
                <div class="panel">
                    <div class="panel-header">Controls</div>
                    <div class="controls">
                        <div class="control-group">
                            <label for="element-search">Highlight Element</label>
                            <input type="number" id="element-search" 
                                   min="0" placeholder="Enter element number...">
                        </div>
                        
                        <div id="term-eval-section" style="display: none;">
                            <div class="control-group">
                                <label for="term-input">Evaluate Term (generator: <code>x</code>)</label>
                                <input type="text" id="term-input" 
                                       placeholder="e.g., x * (x \\ e)">
                            </div>
                            <button onclick="evaluateTerm()">Evaluate</button>
                            <div id="term-result" class="result"></div>
                        </div>
                    </div>
                </div>
                
                <div class="panel tables-panel">
                    <div class="panel-header">Operation Tables</div>
                    <div id="tables-container"></div>
                </div>
            </div>
        </div>
    </div>
    
    <div id="tooltip" class="tooltip"></div>
    
    <script>
        // Embedded algebra data
        const algebraData = {data_json};
        
        // State
        let currentHighlight = null;
        let viewTransform = {{ x: 0, y: 0, scale: 1 }};
        let isPanning = false;
        let panStart = {{ x: 0, y: 0 }};
        
        // Initialize
        document.addEventListener('DOMContentLoaded', () => {{
            initializeViewer();
        }});
        
        function initializeViewer() {{
            // Display info
            document.getElementById('cardinality-info').textContent = 
                `Cardinality: ${{algebraData.cardinality}}`;
            
            // Show term evaluation for free algebras
            if (algebraData.isFree) {{
                document.getElementById('term-eval-section').style.display = 'block';
            }}
            
            // Draw diagram
            drawDiagram();
            
            // Create operation tables
            createTables();
            
            // Setup event listeners
            document.getElementById('element-search').addEventListener('input', (e) => {{
                const val = e.target.value;
                if (val === '') {{
                    highlightElement(null);
                }} else {{
                    const elem = parseInt(val);
                    if (elem >= 0 && elem < algebraData.cardinality) {{
                        highlightElement(elem);
                    }}
                }}
            }});
            
            // Term input - evaluate on Enter
            const termInput = document.getElementById('term-input');
            if (termInput) {{
                termInput.addEventListener('keypress', (e) => {{
                    if (e.key === 'Enter') {{
                        evaluateTerm();
                    }}
                }});
            }}
            
            // Panning
            const container = document.getElementById('diagram-container');
            container.addEventListener('mousedown', startPan);
            container.addEventListener('mousemove', doPan);
            container.addEventListener('mouseup', endPan);
            container.addEventListener('mouseleave', endPan);
            
            // Mouse wheel zoom
            container.addEventListener('wheel', (e) => {{
                e.preventDefault();
                const delta = e.deltaY > 0 ? 0.9 : 1.1;
                zoom(delta, e.offsetX, e.offsetY);
            }});
        }}
        
        function drawDiagram() {{
            const container = document.getElementById('diagram-container');
            const svg = document.getElementById('diagram-svg');
            
            // Get positions
            const positions = algebraData.layoutPositions;
            const nodes = Object.keys(positions).map(k => parseInt(k));
            
            if (nodes.length === 0) {{
                return;
            }}
            
            // Calculate bounds
            let minX = Infinity, maxX = -Infinity;
            let minY = Infinity, maxY = -Infinity;
            
            nodes.forEach(node => {{
                const [x, y] = positions[node];
                minX = Math.min(minX, x);
                maxX = Math.max(maxX, x);
                minY = Math.min(minY, y);
                maxY = Math.max(maxY, y);
            }});
            
            // Add padding
            const padding = 60;
            const width = (maxX - minX) * 60 + 2 * padding;
            const height = (maxY - minY) * 60 + 2 * padding;
            
            svg.setAttribute('width', width);
            svg.setAttribute('height', height);
            svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
            
            // Scale positions to SVG coordinates
            const scaleX = (x) => (x - minX) * 60 + padding;
            const scaleY = (y) => (maxY - y) * 60 + padding; // Invert Y
            
            // Draw edges
            const edgesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            edgesGroup.setAttribute('class', 'edges');
            
            algebraData.orderCovers.forEach(([from, to]) => {{
                const [x1, y1] = positions[from];
                const [x2, y2] = positions[to];
                
                const sx1 = scaleX(x1);
                const sy1 = scaleY(y1);
                const sx2 = scaleX(x2);
                const sy2 = scaleY(y2);
                
                // Shorten edge to account for node radius
                const dx = sx2 - sx1;
                const dy = sy2 - sy1;
                const len = Math.sqrt(dx * dx + dy * dy);
                const nodeRadius = 20;
                
                const nx = dx / len;
                const ny = dy / len;
                
                const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                const path = `M ${{sx1 + nx * nodeRadius}} ${{sy1 + ny * nodeRadius}} L ${{sx2 - nx * (nodeRadius + 5)}} ${{sy2 - ny * (nodeRadius + 5)}}`;
                line.setAttribute('d', path);
                line.setAttribute('class', 'edge');
                
                edgesGroup.appendChild(line);
            }});
            
            svg.appendChild(edgesGroup);
            
            // Draw nodes
            const nodesGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            nodesGroup.setAttribute('class', 'nodes');
            
            nodes.forEach(node => {{
                const [x, y] = positions[node];
                const sx = scaleX(x);
                const sy = scaleY(y);
                
                const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
                g.setAttribute('class', 'node');
                g.setAttribute('data-node', node);
                
                const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                circle.setAttribute('cx', sx);
                circle.setAttribute('cy', sy);
                circle.setAttribute('r', 20);
                
                const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                text.setAttribute('x', sx);
                text.setAttribute('y', sy);
                text.setAttribute('text-anchor', 'middle');
                text.setAttribute('dominant-baseline', 'middle');
                text.textContent = node;
                
                g.appendChild(circle);
                g.appendChild(text);
                
                // Click handler
                g.style.cursor = 'pointer';
                g.addEventListener('click', () => {{
                    highlightElement(node);
                    document.getElementById('element-search').value = node;
                }});
                
                // Hover handler for free algebras
                if (algebraData.isFree && algebraData.representativeTerms) {{
                    g.addEventListener('mouseenter', (e) => {{
                        showTooltip(e, `Element: ${{node}}\\nTerm: ${{algebraData.representativeTerms[node]}}`);
                    }});
                    g.addEventListener('mouseleave', hideTooltip);
                }}
                
                nodesGroup.appendChild(g);
            }});
            
            svg.appendChild(nodesGroup);
            
            // Center view
            resetView();
        }}
        
        function createTables() {{
            const container = document.getElementById('tables-container');
            
            Object.entries(algebraData.operations).forEach(([symbol, op]) => {{
                const section = document.createElement('div');
                section.className = 'table-section';
                
                const title = document.createElement('div');
                title.className = 'table-title';
                
                if (op.arity === 0) {{
                    title.textContent = `${{symbol}} = ${{op.table}}`;
                    section.appendChild(title);
                }} else if (op.arity === 1) {{
                    title.textContent = `Unary operation: ${{symbol}}`;
                    section.appendChild(title);
                    section.appendChild(createUnaryTable(symbol, op));
                }} else if (op.arity === 2) {{
                    title.textContent = `Binary operation: ${{symbol}}`;
                    section.appendChild(title);
                    section.appendChild(createBinaryTable(symbol, op));
                }}
                
                container.appendChild(section);
            }});
        }}
        
        function createUnaryTable(symbol, op) {{
            const table = document.createElement('table');
            table.className = 'op-table';
            
            // Header
            const thead = document.createElement('thead');
            const headerRow = document.createElement('tr');
            headerRow.innerHTML = '<th>x</th><th>' + escapeHtml(symbol) + '(x)</th>';
            thead.appendChild(headerRow);
            table.appendChild(thead);
            
            // Body
            const tbody = document.createElement('tbody');
            for (let i = 0; i < algebraData.cardinality; i++) {{
                const row = document.createElement('tr');
                row.innerHTML = `<th>${{i}}</th><td data-cell="${{symbol}}-${{i}}">${{op.table[i]}}</td>`;
                tbody.appendChild(row);
            }}
            table.appendChild(tbody);
            
            return table;
        }}
        
        function createBinaryTable(symbol, op) {{
            const n = algebraData.cardinality;
            
            // For large tables, show a message
            if (n > 50) {{
                const msg = document.createElement('div');
                msg.style.padding = '12px';
                msg.style.color = '#7f8c8d';
                msg.textContent = `Table too large to display (${{n}}×${{n}}). Operation data is available for term evaluation.`;
                return msg;
            }}
            
            const table = document.createElement('table');
            table.className = 'op-table';
            
            // Header row
            const thead = document.createElement('thead');
            const headerRow = document.createElement('tr');
            headerRow.innerHTML = '<th>' + escapeHtml(symbol) + '</th>';
            for (let j = 0; j < n; j++) {{
                headerRow.innerHTML += `<th>${{j}}</th>`;
            }}
            thead.appendChild(headerRow);
            table.appendChild(thead);
            
            // Body
            const tbody = document.createElement('tbody');
            for (let i = 0; i < n; i++) {{
                const row = document.createElement('tr');
                row.innerHTML = `<th>${{i}}</th>`;
                for (let j = 0; j < n; j++) {{
                    const cell = document.createElement('td');
                    cell.textContent = op.table[i][j];
                    cell.setAttribute('data-cell', `${{symbol}}-${{i}}-${{j}}`);
                    row.appendChild(cell);
                }}
                tbody.appendChild(row);
            }}
            table.appendChild(tbody);
            
            return table;
        }}
        
        function highlightElement(elem) {{
            // Clear previous highlight
            document.querySelectorAll('.node.highlighted').forEach(node => {{
                node.classList.remove('highlighted');
            }});
            document.querySelectorAll('.op-table td.highlighted').forEach(cell => {{
                cell.classList.remove('highlighted');
            }});
            
            currentHighlight = elem;
            
            if (elem === null) return;
            
            // Highlight node
            const node = document.querySelector(`.node[data-node="${{elem}}"]`);
            if (node) {{
                node.classList.add('highlighted');
            }}
            
            // Highlight in tables
            document.querySelectorAll('.op-table td').forEach(cell => {{
                if (cell.textContent == elem) {{
                    cell.classList.add('highlighted');
                }}
            }});
        }}
        
        function evaluateTerm() {{
            const input = document.getElementById('term-input').value.trim();
            const resultDiv = document.getElementById('term-result');
            
            if (!input) {{
                resultDiv.className = 'result';
                resultDiv.textContent = '';
                return;
            }}
            
            try {{
                const result = parseAndEvaluate(input);
                resultDiv.className = 'result success';
                const term = algebraData.representativeTerms[result];
                resultDiv.innerHTML = `<strong>Result:</strong> Element <code>${{result}}</code><br><strong>Representative term:</strong> <code>${{escapeHtml(term)}}</code>`;
                
                // Highlight result
                highlightElement(result);
                document.getElementById('element-search').value = result;
            }} catch (e) {{
                resultDiv.className = 'result error';
                resultDiv.innerHTML = `<strong>Error:</strong> ${{escapeHtml(e.message)}}`;
            }}
        }}
        
        function parseAndEvaluate(input) {{
            // Tokenize
            const tokens = tokenize(input);
            
            // Parse and evaluate
            const {{ value, pos }} = parseExpression(tokens, 0);
            
            if (pos < tokens.length) {{
                throw new Error(`Unexpected token: ${{tokens[pos].value}}`);
            }}
            
            return value;
        }}
        
        function tokenize(input) {{
            const tokens = [];
            let i = 0;
            
            while (i < input.length) {{
                const ch = input[i];
                
                if (/\\s/.test(ch)) {{
                    i++;
                    continue;
                }}
                
                if (ch === '(') {{
                    tokens.push({{ type: 'LPAREN', value: '(' }});
                    i++;
                }} else if (ch === ')') {{
                    tokens.push({{ type: 'RPAREN', value: ')' }});
                    i++;
                }} else if (ch === '*') {{
                    tokens.push({{ type: 'OP', value: '*', symbol: '*' }});
                    i++;
                }} else if (ch === '\\\\') {{
                    tokens.push({{ type: 'OP', value: '\\\\', symbol: '\\\\' }});
                    i++;
                }} else if (/[a-zA-Z_]/.test(ch)) {{
                    let j = i;
                    while (j < input.length && /[a-zA-Z0-9_]/.test(input[j])) {{
                        j++;
                    }}
                    const id = input.substring(i, j);
                    tokens.push({{ type: 'ID', value: id }});
                    i = j;
                }} else {{
                    throw new Error(`Unexpected character: ${{ch}}`);
                }}
            }}
            
            return tokens;
        }}
        
        // Prover9/Mace4 precedence (lower number = higher precedence):
        // \\ (arrow) has lower precedence than * (fusion)
        // Both are left-associative
        function parseExpression(tokens, pos) {{
            return parseArrow(tokens, pos);
        }}
        
        function parseArrow(tokens, pos) {{
            let {{ value, pos: newPos }} = parseFusion(tokens, pos);
            
            while (newPos < tokens.length && tokens[newPos].type === 'OP' && tokens[newPos].value === '\\\\') {{
                newPos++; // consume \\
                const right = parseFusion(tokens, newPos);
                value = applyOp('\\\\', value, right.value);
                newPos = right.pos;
            }}
            
            return {{ value, pos: newPos }};
        }}
        
        function parseFusion(tokens, pos) {{
            let {{ value, pos: newPos }} = parsePrimary(tokens, pos);
            
            while (newPos < tokens.length && tokens[newPos].type === 'OP' && tokens[newPos].value === '*') {{
                newPos++; // consume *
                const right = parsePrimary(tokens, newPos);
                value = applyOp('*', value, right.value);
                newPos = right.pos;
            }}
            
            return {{ value, pos: newPos }};
        }}
        
        function parsePrimary(tokens, pos) {{
            if (pos >= tokens.length) {{
                throw new Error('Unexpected end of input');
            }}
            
            const token = tokens[pos];
            
            if (token.type === 'LPAREN') {{
                const inner = parseExpression(tokens, pos + 1);
                if (inner.pos >= tokens.length || tokens[inner.pos].type !== 'RPAREN') {{
                    throw new Error('Expected closing parenthesis');
                }}
                return {{ value: inner.value, pos: inner.pos + 1 }};
            }}
            
            if (token.type === 'ID') {{
                if (token.value === 'x') {{
                    if (!algebraData.isFree) {{
                        throw new Error('Variable x only available in free algebras');
                    }}
                    return {{ value: algebraData.generatorIndex, pos: pos + 1 }};
                }} else if (token.value === 'e') {{
                    // Constant e
                    const eOp = algebraData.operations['e'];
                    if (!eOp) {{
                        throw new Error('Unknown identifier: ' + token.value);
                    }}
                    return {{ value: eOp.table, pos: pos + 1 }};
                }} else {{
                    throw new Error('Unknown identifier: ' + token.value);
                }}
            }}
            
            throw new Error('Unexpected token: ' + token.value);
        }}
        
        function applyOp(symbol, left, right) {{
            const op = algebraData.operations[symbol];
            if (!op) {{
                throw new Error('Unknown operation: ' + symbol);
            }}
            if (op.arity !== 2) {{
                throw new Error('Operation ' + symbol + ' is not binary');
            }}
            return op.table[left][right];
        }}
        
        function showTooltip(e, text) {{
            const tooltip = document.getElementById('tooltip');
            tooltip.textContent = text;
            tooltip.style.display = 'block';
            tooltip.style.left = (e.pageX + 10) + 'px';
            tooltip.style.top = (e.pageY + 10) + 'px';
        }}
        
        function hideTooltip() {{
            const tooltip = document.getElementById('tooltip');
            tooltip.style.display = 'none';
        }}
        
        function startPan(e) {{
            if (e.target.closest('.node')) return; // Don't pan when clicking nodes
            isPanning = true;
            panStart = {{ x: e.clientX - viewTransform.x, y: e.clientY - viewTransform.y }};
        }}
        
        function doPan(e) {{
            if (!isPanning) return;
            viewTransform.x = e.clientX - panStart.x;
            viewTransform.y = e.clientY - panStart.y;
            applyTransform();
        }}
        
        function endPan() {{
            isPanning = false;
        }}
        
        function zoom(factor, centerX, centerY) {{
            const oldScale = viewTransform.scale;
            viewTransform.scale *= factor;
            viewTransform.scale = Math.max(0.1, Math.min(5, viewTransform.scale));
            
            // Adjust position to zoom toward center
            const scaleChange = viewTransform.scale / oldScale;
            viewTransform.x = centerX - (centerX - viewTransform.x) * scaleChange;
            viewTransform.y = centerY - (centerY - viewTransform.y) * scaleChange;
            
            applyTransform();
        }}
        
        function zoomIn() {{
            const container = document.getElementById('diagram-container');
            zoom(1.2, container.clientWidth / 2, container.clientHeight / 2);
        }}
        
        function zoomOut() {{
            const container = document.getElementById('diagram-container');
            zoom(0.8, container.clientWidth / 2, container.clientHeight / 2);
        }}
        
        function resetView() {{
            const svg = document.getElementById('diagram-svg');
            const container = document.getElementById('diagram-container');
            
            const svgWidth = parseFloat(svg.getAttribute('width'));
            const svgHeight = parseFloat(svg.getAttribute('height'));
            const containerWidth = container.clientWidth;
            const containerHeight = container.clientHeight;
            
            // Fit to container with padding
            const scale = Math.min(
                (containerWidth - 40) / svgWidth,
                (containerHeight - 40) / svgHeight
            );
            
            viewTransform.scale = scale;
            viewTransform.x = (containerWidth - svgWidth * scale) / 2;
            viewTransform.y = (containerHeight - svgHeight * scale) / 2;
            
            applyTransform();
        }}
        
        function applyTransform() {{
            const svg = document.getElementById('diagram-svg');
            svg.style.transform = `translate(${{viewTransform.x}}px, ${{viewTransform.y}}px) scale(${{viewTransform.scale}})`;
        }}
        
        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}
    </script>
</body>
</html>'''


def main() -> None:
    """Command-line interface for generating HTML viewers."""
    parser = argparse.ArgumentParser(
        description="Generate standalone HTML viewer for algebra visualization."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input file (.ua, .model, or .json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output HTML file (default: <input-stem>.html)",
    )
    parser.add_argument(
        "--order-type",
        choices=["icrp", "crl"],
        default=None,
        help="Order type (icrp or crl); auto-detected if omitted",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Custom title for the viewer",
    )
    args = parser.parse_args()
    
    input_path = args.input
    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    
    # Determine format and load
    suffix = input_path.suffix.lower()
    
    try:
        if suffix == ".json":
            print(f"Loading from JSON: {input_path}")
            data = load_algebra_from_json(input_path)
        elif suffix == ".ua":
            print(f"Loading from UACalc: {input_path}")
            data = load_algebra_from_uacalc(input_path)
        elif suffix == ".model":
            print(f"Loading from Mace4: {input_path}")
            data = load_algebra_from_mace4(input_path)
        else:
            print(f"Error: unsupported file type: {suffix}", file=sys.stderr)
            print("Supported formats: .json, .ua, .model", file=sys.stderr)
            sys.exit(1)
        
        # Override order type if specified
        if args.order_type:
            data.order_type = args.order_type
        
        # Determine output path
        output_path = args.output
        if output_path is None:
            output_path = input_path.parent / f"{input_path.stem}.html"
        
        # Generate viewer
        print(f"Generating HTML viewer...")
        generate_html_viewer(data, output_path, title=args.title)
        
        print(f"✓ HTML viewer saved to: {output_path}")
        print(f"  Cardinality: {data.cardinality}")
        print(f"  Operations: {', '.join(data.operations.keys())}")
        if data.is_free:
            print(f"  Free algebra with generator: {data.generator_index}")
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
