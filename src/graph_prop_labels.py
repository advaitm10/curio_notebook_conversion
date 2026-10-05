"""Build a NetworkX cell graph from an ``analyze_notebooks.py`` report.

Each node represents a retained notebook code cell and stores its label,
imports, source, and incoming/outgoing variable names. Blank, comment-only,
and import-only cells are omitted. Imports are placed at the start of the
generated source; incoming variables are read from ``arg`` and outgoing
variables are returned. Each directed edge records the variables flowing
between its source and target cells.

Usage::

    python src/graph_prop_labels.py notebook_analysis.json
    python src/graph_prop_labels.py notebook_analysis.json -o notebook_graph.pkl
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any

import ast

import networkx as nx


def _import_aliases(import_statements: list[str]) -> set[str]:
    """Return variable names introduced by import statements in a cell."""
    aliases: set[str] = set()
    for statement in import_statements:
        if not isinstance(statement, str):
            continue
        stripped = statement.strip()
        if not stripped:
            continue
        try:
            tree = ast.parse(stripped)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    aliases.add(alias.asname or alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    aliases.add(alias.asname or alias.name)
    return aliases


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


def _is_import_only_source(source: str) -> bool:
    """Return whether the source has no executable statements besides imports."""
    filtered: list[str] = []
    for line in str(source).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "%", "!")):
            continue
        filtered.append(stripped)
    return bool(filtered) and all(
        statement.startswith(("import ", "from ")) for statement in filtered
    )


def _incoming_assignment(incoming_variables: list[str]) -> str:
    """Create an ``arg`` assignment for the variables this cell consumes."""
    if not incoming_variables:
        return ""
    if len(incoming_variables) == 1:
        return f"{incoming_variables[0]} = arg"
    targets = ", ".join(incoming_variables)
    return f"{targets}, *_ = arg"


def _source_with_imports(
    source: str,
    import_statements: list[str],
    outgoing_variables: list[str],
    incoming_variables: list[str] | None = None,
) -> str:
    """Compose imports, optional ``arg`` ingestion, cell body, and output return."""
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
    sections: list[str] = []
    if imports:
        sections.append("\n".join(imports))
    if incoming_variables:
        sections.append(_incoming_assignment(incoming_variables))
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
    """Build the cell dependency graph represented by an analysis report.

    The returned graph uses stringified cell indices as node IDs. Edges are
    retained only when both endpoint cells are retained and at least one
    non-import variable flows across them.
    """
    graph = nx.DiGraph()
    valid_cells: dict[int, dict[str, Any]] = {}
    cell_import_aliases: dict[int, set[str]] = {}

    for cell in analysis["cells"]:
        if not isinstance(cell, dict) or not isinstance(cell.get("cell_index"), int):
            raise ValueError("Every cell must have an integer cell_index")
        cell_index = cell["cell_index"]
        imports = cell.get("import_statements", [])
        if not isinstance(imports, list) or not all(
            isinstance(statement, str) for statement in imports
        ):
            raise ValueError("Cell import_statements must be a list of strings")
        source = cell.get("source", "")
        if not isinstance(source, str):
            raise ValueError("Cell source must be a string")
        if not source.strip() or all(
            not line.strip() or line.strip().startswith(("#", "%", "!"))
            for line in source.splitlines()
        ):
            continue
        if _is_import_only_source(source):
            continue
        valid_cells[cell_index] = cell
        cell_import_aliases[cell_index] = _import_aliases(imports)

    outgoing_by_source: dict[int, list[tuple[int, list[str]]]] = {}
    incoming_by_target: dict[int, list[tuple[int, list[str]]]] = {}

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
        if source not in valid_cells or target not in valid_cells:
            continue

        filtered = [
            variable
            for variable in variables
            if variable not in cell_import_aliases.get(source, set())
        ]
        if not filtered:
            continue

        outgoing_by_source.setdefault(source, []).append((target, filtered))
        incoming_by_target.setdefault(target, []).append((source, filtered))

    for cell_index in sorted(valid_cells):
        cell = valid_cells[cell_index]
        imports = cell.get("import_statements", [])
        source = cell.get("source", "")
        if not isinstance(source, str):
            raise ValueError("Cell source must be a string")

        incoming_variables = sorted({
            name for _, values in incoming_by_target.get(cell_index, []) for name in values
        })
        outgoing_variables = sorted({
            name for _, values in outgoing_by_source.get(cell_index, []) for name in values
        })

        graph.add_node(
            str(cell_index),
            cell_index=cell_index,
            execution_count=cell.get("execution_count"),
            cell_type=cell.get("cell_type"),
            import_statements=sorted(set(imports)),
            outgoing_variables=outgoing_variables,
            incoming_variables=incoming_variables,
            source=_source_with_imports(
                source,
                imports,
                outgoing_variables,
                incoming_variables=incoming_variables,
            ),
        )

        for target_cell, edge_vars in outgoing_by_source.get(cell_index, []):
            graph.add_edge(
                str(cell_index),
                str(target_cell),
                variables=sorted(set(edge_vars)),
            )

    return graph


def main() -> int:
    """Build and pickle a graph from an analysis JSON file."""
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
