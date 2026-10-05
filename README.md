# Curio Notebook Conversion

This project converts a Jupyter notebook (`.ipynb`) into a JSON dataflow that
can be loaded into [Curio](https://github.com/urban-toolkit/curio). It extracts
code cells, analyzes variable lineage between cells, builds a directed graph,
and serializes that graph using Curio's dataflow JSON structure.

The resulting graph represents dependencies rather than notebook display
order. A cell that feeds several independent cells branches to each of them;
Curio merge-flow nodes are added only when a cell has multiple incoming graph
edges.

## End-to-end conversion

From the repository root, run:

```bash
python src/convert_ex_script.py path/to/notebook.ipynb
```

The script runs the complete conversion:

1. `generate_python_files_from_nbs.py` extracts code from code cells for
   library-attribution analysis.
2. `lib_attribution.py` analyzes imports and traces definitions to libraries.
3. `analyze_notebooks.py` labels code cells and finds variable dependencies
   using AST-based analysis.
4. `graph_prop_labels.py` creates the cell graph and prepares cell source for
   Curio input and output.
5. `generate_curio_json.py` converts the graph to Curio JSON.

The output is written to the current working directory with a name in the
form `curio_json_test_YYYY-MM-DD_2.json`. For example, running the command on
`test_data/simple_branches_2.ipynb` creates a dated JSON file in the repository
root when the command is run from there. The script does not execute the
notebook; it converts its source and dependencies.

Install the Python dependencies used by the pipeline (`nbformat` and
`networkx`) in the environment you use to run the command.

## Cell labels and Curio node types

The analyzer assigns a label to each code cell using recognizable code
patterns. The exporter maps those labels to Curio's built-in node types:

| Cell label | Curio node type |
| --- | --- |
| `data collection` | `curio.builtin/data-loading@1` |
| `wrangling` | `curio.builtin/data-transformation@1` |
| `training` | `curio.builtin/computation-analysis@1` |
| `evaluation` | `curio.builtin/computation-analysis@1` |
| `exploration` | `curio.builtin/data-transformation@1` |
| `unclassified` or unknown label | `curio.builtin/data-transformation@1` |

The labels are heuristic categories: `data collection` detects common data
loaders and dataset fetchers; `wrangling` covers common data-cleaning and
reshaping operations; `training` identifies selected model-training patterns;
`evaluation` identifies selected model metrics and result attributes; and
`exploration` covers plotting and exploratory-analysis patterns. These are
source-pattern labels, not guarantees about a cell's complete purpose.

The mapping can be overridden when calling `graph_to_curio` directly. An
override only needs to include labels that should differ from the defaults:

```python
from generate_curio_json import graph_to_curio

curio_dataflow = graph_to_curio(
    graph,
    "my_notebook",
    node_type_map={
        "training": "curio.builtin/data-transformation@1",
    },
)
```

## Graph and generated source behavior

- Blank, comment-only, and import-only cells are excluded from the graph.
- Imports are placed before each cell's source, and imported names are not
  treated as data passed between cells.
- Incoming data variables are read from Curio's `arg` value; outgoing
  variables are returned for downstream cells.
- For names loaded but not defined in a cell, variable dependencies use the
  most recent preceding cell definition. Reading a variable does not make the
  reading cell a new origin, so sibling branches that use the same variable
  remain parallel.
- When a node has multiple incoming edges, the Curio export connects all
  predecessors to a `curio.builtin/merge-flow@1` node, then connects that
  merge-flow to the target node.

## Source modules

The `src/` directory contains the pipeline modules:

- **`convert_ex_script.py`** is the end-to-end command-line entry point. It
  invokes the five modules below in pipeline order and writes the final JSON.
- **`generate_python_files_from_nbs.py`** reads a notebook and concatenates
  code-cell source into a Python string for attribution analysis. Its standalone
  command-line mode can also write a `_no_comments.py` file:
  `python src/generate_python_files_from_nbs.py path/to/notebook.ipynb`.
- **`lib_attribution.py`** parses Python source with `ast`, traces definitions
  through local references, and reports the libraries associated with each
  definition. The end-to-end script uses its summary to determine which import
  statements belong in each notebook cell.
- **`analyze_notebooks.py`** reads notebook code cells and the attribution
  summary. It assigns cell labels, adds relevant import statements, and
  identifies inter-cell variable dependencies.
- **`graph_prop_labels.py`** builds a NetworkX directed graph from the
  analysis. Nodes retain cell metadata and prepared source; edges carry the
  variables flowing between cells.
- **`generate_curio_json.py`** serializes the graph as a Curio `dataflow`
  object, assigns a Curio node type based on each cell label, lays out nodes,
  and adds merge-flow nodes for multiple incoming edges.

## Limitations

Cell labels and variable lineage are inferred heuristically from source code.
Dynamic Python behavior, indirect assignments, and complex scoping patterns
may not be fully represented. Review the generated JSON and source before
loading or executing a converted workflow.
