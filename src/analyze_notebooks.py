"""Infer notebook cell labels and variable-reference edges as readable JSON.

This is the Python replacement for ``Jupyter-Notebook-Project/analyze_notebooks.js``.
It consumes the notebook passed to ``lib_attribution.py`` and that tool's JSON
summary.  It uses only Python's standard-library ``ast`` module for reference
analysis; it does not invoke ``analyze_notebook`` or the custom program
analysis implementation.

Example::

    python analyze_notebooks.py notebook.ipynb attribution.json -o report.json
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any


LABEL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("training", ("RandomizedSearchCV", ".compile", "TransformedTargetRegressor")),
    ("data collection", (
        "make_moons", "fetch_", "load_", "make_blobs", "make_classification",
        "make_friedman", "make_gaussian_quantiles", "make_hastie",
        "read_csv", "read_table", "read_excel", "read_sql", "read_json",
        "read_html", "read_clipboard",
    )),
    ("wrangling", (
        "PCA", "NMF", ".reindex", ".dropna", ".fillna", ".apply", "pd.concat",
        ".merge", ".groupby", ".stack", ".unstack", ".date_range",
    )),
    ("evaluation", (
        ".predict_proba", "best_params_", "best_score_", "grid_scores_",
        "best_estimator_", ".feature_importances_",
    )),
    ("exploration", (
        ".plot", ".show", ".subplot", ".histogram", ".matshow", ".imshow",
        ".contour", ".scatter", "AffinityPropagation", "KMeans",
        "AgglomerativeClustering", "DBSCAN", "MeanShift", "SpectralClustering",
    )),
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read valid JSON from {path}: {exc}") from exc


def _source_lines(cell: dict[str, Any]) -> list[str]:
    source = cell.get("source", [])
    if isinstance(source, str):
        return source.splitlines(keepends=True)
    if isinstance(source, list) and all(isinstance(line, str) for line in source):
        return source
    raise ValueError("Notebook cell source must be a string or list of strings")


def _line_label(line: str, matplotlib_aliases: set[str]) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "%", "!")):
        return None
    if stripped.startswith(("import ", "from ")) and " import " in stripped:
        return None
    if any(f"{alias}." in line for alias in matplotlib_aliases):
        return "exploration"
    for label, keywords in LABEL_RULES:
        if any(keyword in line for keyword in keywords):
            return label
    return None


def _cell_type(labels: list[str]) -> str:
    if not labels:
        return "unclassified"
    counts = Counter(labels)
    return sorted(counts, key=lambda label: (-counts[label], label))[0]


def _definitions(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
    return names


def _cell_names(tree: ast.AST) -> set[str]:
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _reference_edges(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Link each variable reference to the closest preceding cell occurrence."""
    last_occurrence: dict[str, int] = {}
    edges: dict[tuple[int, int], dict[str, Any]] = {}
    for cell_index, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(_source_lines(cell))
        try:
            tree = ast.parse(source, filename=f"cell_{cell_index}.py")
        except SyntaxError:
            continue
        loads = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        for name in sorted(loads):
            origin = last_occurrence.get(name)
            if origin is None or origin == cell_index:
                continue
            key = (origin, cell_index)
            edge = edges.setdefault(
                key,
                {
                    "source_cell": origin,
                    "target_cell": cell_index,
                    "variables": [],
                },
            )
            edge["variables"].append(name)

        definitions = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                definitions.update(
                    alias.asname or alias.name.split(".", 1)[0]
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                definitions.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                                   ast.NamedExpr, ast.For, ast.AsyncFor,
                                   ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definitions.update(_definitions(node))
        for name in loads | definitions:
            last_occurrence[name] = cell_index

    for edge in edges.values():
        edge["variables"].sort()
    return sorted(edges.values(), key=lambda edge: (edge["source_cell"], edge["target_cell"]))


def analyze_notebook(notebook_path: Path, attribution: dict) -> dict[str, Any]:
    notebook = _read_json(notebook_path)
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        raise ValueError(f"{notebook_path} is not a valid notebook")
    if not isinstance(attribution, list) or not all(isinstance(row, dict) for row in attribution):
        raise ValueError(f"{attribution} must contain attribution objects")

    library_statements: dict[str, set[str]] = {}
    for row in attribution:
        statement = row.get("import_statement")
        if not statement:
            continue
        statement = str(statement)
        keys = set(row.get("third_party", []))
        keys.add(str(row.get("primary_library", "")))
        for key in keys:
            if key:
                key = str(key)
                library_statements.setdefault(key, set()).add(statement)
                library_statements.setdefault(key.split(".", 1)[0], set()).add(statement)

    cells: list[dict[str, Any]] = []
    matplotlib_aliases: set[str] = {"plt"}
    for index, raw_cell in enumerate(notebook["cells"]):
        if not isinstance(raw_cell, dict):
            raise ValueError(f"Notebook cell {index} is not an object")
        lines = _source_lines(raw_cell)
        if raw_cell.get("cell_type") != "code":
            continue
        source = "".join(lines)
        try:
            tree = ast.parse(source, filename=f"cell_{index}.py")
        except SyntaxError:
            tree = None
        execution_count = raw_cell.get("execution_count")
        if execution_count is None:
            execution_count = sum(
                1 for previous in cells if previous["execution_count"] is not None
            ) + 1
        labels: list[str] = []
        for line in lines:
            if "import matplotlib.pyplot as" in line:
                matplotlib_aliases.add(line.split(" as ", 1)[1].strip().split()[0])
            label = _line_label(line, matplotlib_aliases)
            if label:
                labels.append(label)
        names = _cell_names(tree) if tree is not None else set()
        import_statements: set[str] = set()
        for row in attribution:
            if row.get("name") not in names:
                continue
            libraries = set(row.get("third_party", []))
            primary = row.get("primary_library")
            if primary:
                libraries.add(str(primary))
            for library in libraries:
                library = str(library)
                import_statements.update(library_statements.get(library, set()))
                import_statements.update(
                    library_statements.get(library.split(".", 1)[0], set())
                )
            if row.get("import_statement"):
                import_statements.add(str(row["import_statement"]))
        cells.append(
            {
                "cell_index": index,
                "execution_count": execution_count,
                "source": source,
                "cell_type": _cell_type(labels),
                "import_statements": sorted(import_statements),
            }
        )

    edges = _reference_edges(notebook["cells"])
    return {
        "format": "curio-notebook-cell-analysis",
        "version": 5,
        "notebook": str(notebook_path),
        "summary": {
            "code_cells": len(cells),
            "edges": len(edges),
            "cell_types": dict(sorted(Counter(cell["cell_type"] for cell in cells).items())),
            "attribution_definitions": len(attribution),
        },
        "cells": cells,
        "edges": edges,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebook", type=Path, help="The .ipynb analyzed by lib_attribution")
    parser.add_argument("attribution", type=Path, help="lib_attribution.py JSON output")
    parser.add_argument("--json", action="store_true", help="Flag to dump a json file")
    args = parser.parse_args()
    try:
        rendered = analyze_notebook(args.notebook, _read_json(args.attribution))
        serialized = json.dumps(rendered, indent=2, ensure_ascii=False) + "\n"
        if args.json:
            output_path = args.notebook.with_name(f"{args.notebook.stem}_analysis.json")
            output_path.write_text(serialized, encoding="utf-8")
        else:
            print(serialized, end="")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
