"""Build a labeled cell dependency graph from ``analyze_notebooks.py`` JSON.

Each graph node represents a notebook code cell.  Its ``source`` attribute
contains the cell imports at the top, the original cell source, and a return
statement for variables passed to downstream cells.  Each edge stores the
variables passed from its source cell to its target cell.

Usage::

    python graph_prop_labels.py notebook_analysis.json
    python graph_prop_labels.py notebook_analysis.json -o notebook_graph.pkl
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any

import networkx as nx

def _read_analysis(path: Path) -> dict[str, Any]:
    try:
        analysis = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read valid JSON from {path}: {exc}") from exc
    if not isinstance(analysis, dict):
        raise ValueError(f"{path} must contain an analysis object")
    if not isinstance(analysis.get("cells"), list) or not isinstance(
        analysis.get("edges"), list
    ):
        raise ValueError(f"{path} must contain cells and edges lists")
    return analysis


def _source_with_imports(
    source: str, import_statements: list[str], outgoing_variables: list[str]
) -> str:
    """Compose source with imports first and an optional outgoing return."""
    source_lines = source.splitlines()
    existing_imports = {
        line.strip()
        for line in source_lines
        if line.strip().startswith(("import ", "from "))
    }
    imports = [
        statement
        for statement in sorted(set(import_statements))
        if statement.strip() not in existing_imports
    ]
    body = source.rstrip()
    sections = []
    if imports:
        sections.append("\n".join(imports))
    if body:
        sections.append(body)
    if outgoing_variables:
        returned = (
            outgoing_variables[0]
            if len(outgoing_variables) == 1
            else f"({', '.join(outgoing_variables)})"
        )
        sections.append(f"return {returned}")
    return "\n\n".join(sections)


def build_graph(analysis: dict[str, Any]) -> nx.DiGraph:
    """Build a directed cell graph from an analyzer report."""
    graph = nx.DiGraph()
    outgoing: dict[int, set[str]] = {}

    for edge in analysis["edges"]:
        if not isinstance(edge, dict):
            raise ValueError("Every edge must be an object")
        source = edge.get("source_cell")
        target = edge.get("target_cell")
        variables = edge.get("variables", [])
        if not isinstance(source, int) or not isinstance(target, int):
            raise ValueError("Edge cell identifiers must be integers")
        if not isinstance(variables, list) or not all(
            isinstance(variable, str) for variable in variables
        ):
            raise ValueError("Edge variables must be a list of strings")
        outgoing.setdefault(source, set()).update(variables)
        graph.add_edge(
            str(source),
            str(target),
            variables=sorted(set(variables)),
        )

    for cell in analysis["cells"]:
        if not isinstance(cell, dict) or not isinstance(cell.get("cell_index"), int):
            raise ValueError("Every cell must have an integer cell_index")
        cell_index = cell["cell_index"]
        imports = cell.get("import_statements", [])
        source = cell.get("source", "")
        if not isinstance(imports, list) or not all(
            isinstance(statement, str) for statement in imports
        ):
            raise ValueError("Cell import_statements must be a list of strings")
        if not isinstance(source, str):
            raise ValueError("Cell source must be a string")
        variables = sorted(outgoing.get(cell_index, set()))
        cell_type = cell.get("cell_type")
        graph.add_node(
            str(cell_index),
            cell_index=cell_index,
            execution_count=cell.get("execution_count"),
            cell_type=cell_type,
            import_statements=sorted(set(imports)),
            outgoing_variables=variables,
            source=_source_with_imports(source, imports, variables),
        )

    return graph


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path, help="analyze_notebooks.py JSON output")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output pickle path (default: <analysis>_graph.pkl)",
    )
    args = parser.parse_args()

    try:
        graph = build_graph(_read_analysis(args.analysis))
        output = args.output or args.analysis.with_name(f"{args.analysis.stem}_graph.pkl")
        with output.open("wb") as stream:
            pickle.dump(graph, stream)
        print(f"Wrote {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges to {output}")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
