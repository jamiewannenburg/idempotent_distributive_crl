"""Export algebras to multiple formats: Mace4 model and JSON.

Supports both regular algebras and free algebras with additional metadata.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pyp9m4 import Model



@dataclass
class AlgebraExportData:
    """Common algebra data for export to various formats."""

    name: str
    cardinality: int
    operations: dict[str, Any]  # symbol -> operation data
    relations: dict[str, Any] | None = None  # symbol -> relation data
    order_type: str | None = None  # "icrp" or "crl" or None
    order_relation: np.ndarray | None = None  # precomputed order (leq matrix)
    order_covers: list[tuple[int, int]] | None = None  # Hasse diagram edges
    
    # Free algebra extensions
    is_free: bool = False
    generator_index: int | None = None
    representative_terms: list[str] | None = None
    layout_positions: dict[int, tuple[float, float]] | None = None


def export_to_json(data: AlgebraExportData, output_path: Path) -> None:
    """Export algebra to common JSON format."""
    json_data = {
        "name": data.name,
        "cardinality": data.cardinality,
        "operations": {},
        "relations": {},
    }
    
    # Export operations (convert numpy arrays to lists)
    for symbol, op_data in data.operations.items():
        if isinstance(op_data, dict):
            # Already structured (arity + table)
            json_data["operations"][symbol] = {
                "arity": op_data["arity"],
                "table": _serialize_table(op_data["table"]),
            }
        elif callable(op_data):
            # Function: need arity and cardinality to build table
            raise ValueError(f"Cannot export function {symbol} without explicit table")
    
    # Export relations
    if data.relations:
        for symbol, rel_data in data.relations.items():
            json_data["relations"][symbol] = {
                "arity": rel_data["arity"],
                "table": _serialize_table(rel_data["table"]),
            }
    
    # Order information
    if data.order_type:
        json_data["orderType"] = data.order_type
    if data.order_relation is not None:
        json_data["orderRelation"] = _serialize_table(data.order_relation)
    if data.order_covers:
        json_data["orderCovers"] = data.order_covers
    
    # Free algebra extensions
    if data.is_free:
        json_data["isFree"] = True
        if data.generator_index is not None:
            json_data["generatorIndex"] = data.generator_index
        if data.representative_terms:
            json_data["representativeTerms"] = data.representative_terms
        if data.layout_positions:
            json_data["layoutPositions"] = {
                str(k): list(v) for k, v in data.layout_positions.items()
            }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2)


def _serialize_table(table: Any) -> list:
    """Convert numpy array or nested structure to JSON-serializable list."""
    if isinstance(table, np.ndarray):
        return table.tolist()
    elif isinstance(table, (list, tuple)):
        return list(table)
    else:
        return table


def export_to_mace4(data: AlgebraExportData, output_path: Path) -> None:
    """Export algebra to Mace4 model format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"interpretation( {data.cardinality}, [number = 1, seconds = 0], [\n")
        
        items = []
        
        # Write operations
        for symbol, op_data in data.operations.items():
            arity = op_data["arity"]
            table = op_data["table"]
            
            if arity == 0:
                # Constant
                items.append(f"    function({symbol}, [{table}])")
            else:
                table_str = _format_mace4_table(table, data.cardinality, arity)
                items.append(f"    function({symbol}({','.join(['_'] * arity)}), [{table_str}])")
        
        # Write relations
        if data.relations:
            for symbol, rel_data in data.relations.items():
                arity = rel_data["arity"]
                table = rel_data["table"]
                table_str = _format_mace4_table(table, data.cardinality, arity)
                items.append(f"    relation({symbol}({','.join(['_'] * arity)}), [{table_str}])")
        
        f.write(",\n".join(items))
        f.write("]).\n")


def _format_mace4_table(table: Any, cardinality: int, arity: int) -> str:
    """Format operation/relation table for Mace4."""
    if isinstance(table, np.ndarray):
        flat = table.flatten()
    else:
        flat = np.array(table).flatten()
    
    # Convert booleans to 0/1
    if flat.dtype == bool:
        flat = flat.astype(int)
    
    parts = []
    for i, val in enumerate(flat):
        if arity == 2 and i > 0 and i % cardinality == 0:
            parts.append(f"\n                       {val}")
        else:
            parts.append(str(val))
    
    return ",".join(parts)


def model_to_export_data(
    model: Model,
    order_type: str | None = None,
    order_relation: np.ndarray | None = None,
    order_covers: list[tuple[int, int]] | None = None,
) -> AlgebraExportData:
    """Convert a pyp9m4 Model to AlgebraExportData."""
    import re
    
    # Extract name from model
    match = re.search(r"number\s*=\s*(\d+)", model.raw)
    name = f"model{match.group(1)}" if match else "model"
    
    # Extract operations
    operations = {}
    function_symbols = model.function_symbols
    
    # Common iCRP operations
    if "*" in function_symbols:
        dot = model.as_function("*")
        table = np.array([[dot(i, j) for j in range(model.domain_size)] 
                          for i in range(model.domain_size)])
        operations["*"] = {"arity": 2, "table": table}
    
    if "\\" in function_symbols:
        arrow = model.as_function("\\")
        table = np.array([[arrow(i, j) for j in range(model.domain_size)] 
                          for i in range(model.domain_size)])
        operations["\\"] = {"arity": 2, "table": table}
    
    if "e" in function_symbols:
        e = model.as_function("e")()
        operations["e"] = {"arity": 0, "table": e}
    
    # CRL operations
    if "^" in function_symbols:
        meet = model.as_function("^")
        table = np.array([[meet(i, j) for j in range(model.domain_size)] 
                          for i in range(model.domain_size)])
        operations["^"] = {"arity": 2, "table": table}
    
    if "v" in function_symbols:
        join = model.as_function("v")
        table = np.array([[join(i, j) for j in range(model.domain_size)] 
                          for i in range(model.domain_size)])
        operations["v"] = {"arity": 2, "table": table}
    
    # Relations
    relations = None
    relation_symbols = model.relation_symbols
    if "<=" in relation_symbols:
        leq = model.as_relation("<=")
        table = np.array([[leq(i, j) for j in range(model.domain_size)] 
                          for i in range(model.domain_size)], dtype=bool)
        relations = {"<=": {"arity": 2, "table": table}}
    
    return AlgebraExportData(
        name=name,
        cardinality=model.domain_size,
        operations=operations,
        relations=relations,
        order_type=order_type,
        order_relation=order_relation,
        order_covers=order_covers,
    )


def export_model_all_formats(
    model: Model,
    base_path: Path,
    order_type: str | None = None,
    order_relation: np.ndarray | None = None,
    order_covers: list[tuple[int, int]] | None = None,
) -> dict[str, Path]:
    """Export a Model to .model and .json formats."""
    base_path = Path(base_path)
    stem = base_path.stem
    parent = base_path.parent
    
    data = model_to_export_data(model, order_type, order_relation, order_covers)
    
    paths = {}
    
    # Export to each format
    model_path = parent / f"{stem}.model"
    export_to_mace4(data, model_path)
    paths["model"] = model_path
    
    json_path = parent / f"{stem}.json"
    export_to_json(data, json_path)
    paths["json"] = json_path
    
    return paths
