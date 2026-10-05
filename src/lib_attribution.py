"""Attribute Python definitions to imports and their originating libraries.

The module parses source with :mod:`ast`, resolves references using
deterministic file-local heuristics, and represents definitions and library
imports as a NetworkX dependency graph. Transitive library dependencies are
reported for variables, functions, and classes. Analysis uses source text and
does not require the referenced third-party packages to be installed.

This is best-effort rather than scope-complete: Python's full LEGB scoping and
dynamic behavior (such as ``getattr``, ``exec``, and monkeypatching) are not
modeled. Similar names in unrelated scopes can therefore be ambiguous.

Command-line examples::

    python src/lib_attribution.py script.py
    python src/lib_attribution.py script.py --json
    python src/lib_attribution.py script.py --graphml dependency-graph.graphml
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import networkx as nx

STDLIB_MODULES = set(sys.stdlib_module_names)

# Modules whose real implementation lives in a differently-named module
# (platform-specific backends, C-accelerated shadows, etc.) but that a user
# would recognize by the name they actually imported.
MODULE_ALIASES = {
    "posixpath": "os",
    "ntpath": "os",
    "genericpath": "os",
    "nt": "os",
    "posix": "os",
}


def _normalize_module(mod: str) -> str:
    """Collapse C-extension shadow modules like '_collections' -> 'collections'."""
    if mod.startswith("_") and mod.lstrip("_") in STDLIB_MODULES:
        mod = mod.lstrip("_")
    return MODULE_ALIASES.get(mod, mod)


def _classify(
    module_name: str | None,
    in_builtin: bool,
    script_modules: set[str],
) -> tuple[str, str] | None:
    """Return (category, library_key) for a resolved module definition."""
    if not module_name:
        return None
    if module_name in script_modules:
        return ("local", module_name)
    top = _normalize_module(module_name).split(".")[0]
    if top == "builtins":
        return ("builtin", "builtins")
    if top in STDLIB_MODULES:
        return ("third_party", top)
    return ("third_party", top)


class LibraryAttributor:
    """Build and summarize a best-effort dependency graph for Python source."""

    def __init__(self, source: str, path: str | None = None):
        self.source = source
        # A path is optional metadata. Source-only callers never need a file.
        self.path = path or "<source>"
        self.script_module = Path(path).stem if path else "<source>"
        self.script_modules = (
            {Path(path).stem, Path(path).parent.name}
            if path
            else {"<source>"}
        )
        # Keep resolution deterministic and file-independent. Jedi can
        # resolve a reassigned local name through the containing directory
        # package (for example ``test_data``), which incorrectly changes the
        # attribution of later variables. The AST/file-local resolver avoids
        # that ambiguity and works equally with or without a path.
        self.script = None
        self.graph = nx.DiGraph()
        # (name, line) -> node_id, used to match a jedi "local" goto result
        # back to one of our own definition nodes.
        self._by_name_line: dict[tuple[str, int], str] = {}
        # name -> [node_id, ...] in file order, used by the no-jedi fallback
        # to guess "nearest prior definition of this name".
        self._by_name: dict[str, list[str]] = {}
        # name -> (category, library), for imports -- always available
        # straight from the `import` statement itself, regardless of
        # whether that library is actually installed.
        self._imports_by_name: dict[str, tuple[str, str]] = {}
        self._pending_ref_scans: list[tuple[str, ast.AST]] = []

    # ---------- pass 1: structure (pure ast, no jedi needed) ----------

    def _add_def_node(self, name: str, line: int, col: int, kind: str,
                      **attributes: str) -> str:
        # Keep one canonical node for a variable name.  Notebook cells often
        # reassign a dataframe (for example, ``df = df.dropna()``); treating
        # that reassignment as a new library definition makes later variables
        # inherit the script/module name rather than the dataframe's library.
        if kind == "variable" and name in self._by_name:
            return self._by_name[name][0]
        node_id = f"{name}@{line}:{col}"
        self.graph.add_node(
            node_id, name=name, kind=kind, line=line, category="local", **attributes
        )
        self._by_name_line[(name, line)] = node_id
        self._by_name.setdefault(name, []).append(node_id)
        return node_id

    def _add_lib_node(self, category: str, key: str) -> str:
        node_id = f"lib:{key}"
        if node_id not in self.graph:
            self.graph.add_node(node_id, name=key, kind="library", category=category)
        return node_id

    def build(self) -> nx.DiGraph:
        """Parse the source and construct definition/reference dependencies."""
        tree = ast.parse(self.source, filename=self.path)
        self._collect_definitions(tree)
        for node_id, scan_target in self._pending_ref_scans:
            self._link_references(node_id, scan_target)
        self._propagate_assignment_libraries()
        return self.graph

    def _collect_definitions(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._handle_import(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nid = self._add_def_node(node.name, node.lineno, node.col_offset, "function")
                self._pending_ref_scans.append((nid, node))
            elif isinstance(node, ast.ClassDef):
                nid = self._add_def_node(node.name, node.lineno, node.col_offset, "class")
                self._pending_ref_scans.append((nid, node))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name_node in self._store_names(target):
                        is_new = name_node.id not in self._by_name
                        nid = self._add_def_node(name_node.id, node.lineno, name_node.col_offset, "variable")
                        if is_new:
                            self._pending_ref_scans.append((nid, node.value))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                is_new = node.target.id not in self._by_name
                nid = self._add_def_node(node.target.id, node.lineno, node.target.col_offset, "variable")
                if is_new and node.value is not None:
                    self._pending_ref_scans.append((nid, node.value))
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                is_new = node.target.id not in self._by_name
                nid = self._add_def_node(node.target.id, node.lineno, node.target.col_offset, "variable")
                if is_new:
                    self._pending_ref_scans.append((nid, node.value))

    @staticmethod
    def _store_names(target: ast.AST):
        for n in ast.walk(target):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                yield n

    def _handle_import(self, node: ast.Import | ast.ImportFrom) -> None:
        statement = ast.get_source_segment(self.source, node) or ""
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                bound = alias.asname or alias.name.split(".")[0]
                self._record_import(
                    bound, node.lineno, node.col_offset, top, alias.name, statement
                )
        else:
            if node.level and not node.module:
                top = None  # plain relative import, e.g. `from . import x`
            else:
                top = (node.module or "").split(".")[0]
            for alias in node.names:
                bound = alias.asname or alias.name
                if top is None:
                    import_path = alias.name
                    self._record_import(
                        bound, node.lineno, node.col_offset, None, import_path,
                        statement, relative=True
                    )
                else:
                    import_path = f"{node.module}.{alias.name}"
                    self._record_import(
                        bound, node.lineno, node.col_offset, top, import_path, statement
                    )

    def _record_import(
        self,
        bound_name: str,
        line: int,
        col: int,
        top: str | None,
        import_path: str,
        statement: str,
        relative: bool = False,
    ) -> None:
        nid = self._add_def_node(
            bound_name, line, col, "import",
            import_path=import_path, import_statement=statement,
        )
        if relative:
            lib_id = self._add_lib_node("relative", self.script_module)
            self.graph.add_edge(nid, lib_id, relation="imports")
            self._imports_by_name[bound_name] = ("relative", self.script_module)
            return
        category = "third_party"
        lib_id = self._add_lib_node(category, import_path)
        self.graph.add_edge(nid, lib_id, relation="imports")
        self._imports_by_name[bound_name] = (category, import_path)

    # ---------- pass 2: resolve references ----------
    #
    # For each name referenced in a definition's body/RHS, try jedi.goto()
    # first (never infer() -- goto is lighter-weight and, when it works,
    # more precise, but both fail equally once a package isn't installed,
    # so we never lean on jedi being available). Whenever jedi comes back
    # empty, fall back to a plain lexical guess built entirely from this
    # file's own imports and definitions.

    def _link_references(self, node_id: str, subtree: ast.AST) -> None:
        seen_edges: set[str] = set()
        for n in ast.walk(subtree):
            if not (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)):
                continue
            line, col = n.lineno, n.col_offset

            matched = False
            for target, category, key in self._resolve_with_jedi(line, col):
                matched = True
                if target == "skip":
                    continue
                self._add_edge(node_id, target, category, key, seen_edges)

            if not matched:
                target, category, key = self._resolve_fallback(n.id, line)
                self._add_edge(node_id, target, category, key, seen_edges)

    def _propagate_assignment_libraries(self) -> None:
        """Preserve the libraries of variables used to construct assignments.

        Jedi can resolve dataframe subscripts to a module in the analyzed
        script rather than to the local variable being sliced.  Re-checking
        assignment references using the file-local fallback lets an
        assignment inherit the known libraries of that variable directly.
        """
        for node_id, subtree in self._pending_ref_scans:
            if self.graph.nodes[node_id].get("kind") != "variable":
                continue

            for name_node in ast.walk(subtree):
                if not (isinstance(name_node, ast.Name) and isinstance(name_node.ctx, ast.Load)):
                    continue
                target, _, _ = self._resolve_fallback(name_node.id, name_node.lineno)
                if target is None or target == node_id:
                    continue

                libraries = self.base_libraries(target)
                for key in libraries["third_party"]:
                    self.graph.add_edge(
                        node_id,
                        self._add_lib_node("third_party", key),
                        relation="uses",
                    )

    def _resolve_with_jedi(self, line: int, col: int):
        """Yield (local_node_id | 'skip' | None, category_or_None, key_or_None).

        'skip' means jedi *did* resolve the name (e.g. to a function
        parameter) but to something we don't track as a library-relevant
        node -- the caller should count that as handled, not fall through
        to the no-jedi guess.
        """
        if self.script is None:
            return
        try:
            results = self.script.goto(line, col, follow_imports=True, follow_builtin_imports=True)
        except Exception:
            results = []
        for d in results:
            try:
                info = _classify(
                    d.module_name,
                    d.in_builtin_module(),
                    self.script_modules,
                )
            except Exception:
                info = None
            if info is None:
                continue
            category, key = info
            if category == "local":
                target = self._by_name_line.get((d.name, d.line))
                if target is None:
                    yield ("skip", None, None)  # e.g. a parameter, not a tracked node
                else:
                    yield (target, None, None)
            else:
                yield (None, category, key)

    def _resolve_fallback(self, name: str, ref_line: int) -> tuple[str | None, str | None, str | None]:
        """Best-effort, jedi-free resolution using only this file's text.

        Picks the nearest prior definition of `name` by line number as a
        stand-in for real scoping. This can mis-fire when the same name is
        reused unrelatedly elsewhere in the file, but per-file it's a
        reasonable approximation and never depends on any package being
        importable.
        """
        if name in self._imports_by_name:
            category, key = self._imports_by_name[name]
            return (None, category, key)
        candidates = self._by_name.get(name)
        if candidates:
            ordered = sorted(candidates, key=lambda nid: self.graph.nodes[nid]["line"])
            prior = [nid for nid in ordered if self.graph.nodes[nid]["line"] <= ref_line]
            return (prior[-1] if prior else ordered[0], None, None)
        # Unknown name: most commonly a builtin (len, range, print, ...),
        # occasionally a typo or a name from an unresolvable wildcard
        # import. Treating it as "builtin" is the safer default of the two.
        return (None, "builtin", "builtins")

    def _add_edge(self, node_id: str, local_target: str | None, category: str | None, key: str | None,
                  seen_edges: set[str]) -> None:
        if local_target is not None:
            if local_target == node_id:
                return
            edge_key = f"L{local_target}"
            target = local_target
        else:
            target = self._add_lib_node(category, key)
            edge_key = f"G{target}"
        if edge_key in seen_edges:
            return
        seen_edges.add(edge_key)
        self.graph.add_edge(node_id, target, relation="uses")

    # ---------- summarizing ----------

    def base_libraries(self, node_id: str) -> dict[str, set[str]]:
        """Every library reachable from this node, grouped by category."""
        out: dict[str, set[str]] = {"third_party": set(), "builtin": set(), "relative": set()}
        if node_id not in self.graph:
            return out
        for desc in nx.descendants(self.graph, node_id) | {node_id}:
            data = self.graph.nodes[desc]
            if data.get("kind") == "library":
                out.setdefault(data["category"], set()).add(data["name"])
        return out

    def summary(self) -> list[dict]:
        """Return one library-attribution record for each non-library definition."""
        rows = []
        for node_id, data in self.graph.nodes(data=True):
            if data.get("kind") == "library":
                continue
            libs = self.base_libraries(node_id)
            flat = sorted(libs["third_party"])
            primary = flat[0] if flat else (
                "builtins" if libs["builtin"] else
                ("<relative import>" if libs["relative"] else "local-only")
            )
            row = {
                "name": data["name"],
                "kind": data["kind"],
                "line": data["line"],
                "primary_library": primary,
                "third_party": sorted(libs["third_party"]),
            }
            if data.get("kind") == "import":
                row["import_statement"] = data.get("import_statement", "")
                row["import_path"] = data.get("import_path", data["name"])
            rows.append(row)
        rows.sort(key=lambda r: r["line"])
        return rows


def analyze(source: str, path: str | None = None) -> tuple[nx.DiGraph, list[dict]]:
    """Analyze Python source and return its dependency graph and summary rows.

    Args:
        source: Python source text to analyze.
        path: Optional filename context used for AST diagnostics and module
            attribution. The analysis itself uses the supplied source text.

    Returns:
        A pair containing the definition/library dependency graph and summary
        rows suitable for JSON serialization.
    """
    attributor = LibraryAttributor(source, path)
    graph = attributor.build()
    return graph, attributor.summary()


# CATEGORY_COLORS = {
#     "third_party": "#e07a5f",
#     "stdlib": "#3d8bfd",
#     "builtin": "#adb5bd",
#     "relative": "#9d4edd",
#     "local": "#2a9d8f",
# }


# def draw(graph: nx.DiGraph, out_path: str) -> None:
#     """Render the dependency digraph, color-coded by category, to a PNG."""
#     import matplotlib.pyplot as plt

#     plt.figure(figsize=(max(8, graph.number_of_nodes() * 0.9), 7))
#     pos = nx.spring_layout(graph, k=1.2, seed=7)

#     node_colors = [CATEGORY_COLORS.get(d.get("category", "local"), "#2a9d8f") for _, d in graph.nodes(data=True)]
#     lib_nodes = [n for n, d in graph.nodes(data=True) if d.get("kind") == "library"]
#     local_nodes = [n for n in graph.nodes if n not in lib_nodes]

#     nx.draw_networkx_edges(graph, pos, alpha=0.35, arrows=True, arrowsize=10)
#     nx.draw_networkx_nodes(graph, pos, nodelist=local_nodes, node_color=[CATEGORY_COLORS["local"]] * len(local_nodes),
#                             node_shape="o", node_size=700, alpha=0.9)
#     nx.draw_networkx_nodes(graph, pos, nodelist=lib_nodes,
#                             node_color=[CATEGORY_COLORS.get(graph.nodes[n]["category"], "#333") for n in lib_nodes],
#                             node_shape="s", node_size=900, alpha=0.95)
#     labels = {n: graph.nodes[n]["name"] for n in graph.nodes}
#     nx.draw_networkx_labels(graph, pos, labels, font_size=8)

#     handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=10, label=cat)
#                for cat, c in CATEGORY_COLORS.items()]
#     plt.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.9)
#     plt.axis("off")
#     plt.tight_layout()
#     plt.savefig(out_path, dpi=150)
#     plt.close()


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", help="Path to the .py file to analyze")
    parser.add_argument("--json", action="store_true", help="Print summary as JSON instead of a table")
    parser.add_argument("--graphml", help="Optional path to write the dependency graph as GraphML")
    # parser.add_argument("--draw", help="Optional path to save a PNG visualization of the dependency graph")
    args = parser.parse_args()

    src = Path(args.script).read_text()
    graph, rows = analyze(src, path=args.script)

    if args.json:
        # print(json.dumps(rows, indent=2))
        with open(args.script.replace('_no_comments.py', '_vars.json'), 'w') as outfile:
            json.dump(rows, outfile)
    else:
        w_name = max([len("name")] + [len(r["name"]) for r in rows])
        w_kind = max([len("kind")] + [len(r["kind"]) for r in rows])
        w_lib = max([len("primary_library")] + [len(r["primary_library"]) for r in rows])
        header = f'{"line":>4}  {"name".ljust(w_name)}  {"kind".ljust(w_kind)}  {"primary_library".ljust(w_lib)}  extra'
        print(header)
        print("-" * len(header))
        for r in rows:
            extra_libs = [l for l in r["third_party"] if l != r["primary_library"]]
            extra = ("+" + ",".join(extra_libs)) if extra_libs else ""
            print(f'{r["line"]:>4}  {r["name"].ljust(w_name)}  {r["kind"].ljust(w_kind)}  {r["primary_library"].ljust(w_lib)}  {extra}')

    if args.graphml:
        # GraphML needs string-only attributes
        clean = nx.DiGraph()
        for n, d in graph.nodes(data=True):
            clean.add_node(n, **{k: str(v) for k, v in d.items()})
        for u, v, d in graph.edges(data=True):
            clean.add_edge(u, v, **{k: str(v) for k, v in d.items()})
        nx.write_graphml(clean, args.graphml)
        print(f"\nGraph written to {args.graphml}")

    # if args.draw:
    #     draw(graph, args.draw)
    #     print(f"\nDiagram saved to {args.draw}")
