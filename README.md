# Curio Notebook Conversion

This project converts a Jupyter Notebook into a JSON structure that can be imported into Curio, an open-source graph-based workflow and dataflow platform. The goal is to take notebook cells, understand how they depend on one another, and serialize that structure into a format Curio can visualize and execute as a workflow.

At a high level, the pipeline is:

1. Read a `.ipynb` notebook.
2. Extract the executable code cells while discarding comments and markdown.
3. Analyze imports, variable usage, and cell-to-cell dependencies.
4. Build a directed graph representing notebook relationships.
5. Export that graph as Curio-ready JSON.

This makes it possible to turn a notebook into a graph that preserves dataflow and execution relationships rather than just raw notebook content.

## The five imported files in the convert_ex_script.py

The main conversion script imports five modules, each of which handles one part of the transformation pipeline:

### 1. `generate_python_files_from_nbs.py`

This file converts a notebook into a Python string that concatenates the notebook's code cells into one script-like source. It removes comments and markdown, leaving only executable code that can be analyzed more easily. This is the first step in making notebook logic machine-readable and ready for dependency analysis.

### 2. `lib_attribution.py`

This module performs library attribution. It inspects the generated Python source and determines which variables, functions, classes, and definitions ultimately originate from third-party libraries, the standard library, or the local notebook code itself. It uses Python's AST parsing combined with a graph representation to trace dependencies back to their source libraries.

This helps answer questions like: which code is local, and which code depends on pandas, numpy, sklearn, or other imported libraries?

### 3. `analyze_notebooks.py`

This file analyzes the notebook structure itself. It reads notebook cells, identifies code-cell dependencies based on variable references between cells, and infers labels for cells based on common data-science or notebook patterns. It produces structured JSON summarizing cells, imports, and relationships between them.

This is the step that turns a collection of notebook cells into an actionable dependency model.

### 4. `graph_prop_labels.py`

This module builds a NetworkX graph from the analysis output. Each node represents a notebook cell, and edges represent how variables flow from one cell to another. It also attaches metadata such as imports and outgoing variables to each node so the graph reflects notebook semantics instead of just raw execution order.

This graph is the key intermediate representation that sits between notebook analysis and Curio output.

### 5. `generate_curio_json.py`

This file converts the cell graph into the JSON schema expected by Curio. It assigns positions to nodes, creates edges between them, and packages the result into a `dataflow` object that can be serialized and loaded into Curio. In other words, this is the final export step where the notebook graph becomes a Curio-compatible JSON document.

## Project purpose

The project is designed to bridge the gap between exploratory notebook workflows and Curio's graph-based workflow representation. Jupyter notebooks are natural for prototyping, experimentation, and analysis, but they are not structured as dependency graphs by default. This project converts that implicit notebook structure into an explicit graph so it can be imported into Curio for viewing, editing, and execution as a dataflow workflow.

In short, the conversion pipeline transforms a notebook into a structured graph and then exports that graph as a Curio JSON object, preserving important relationships in the original analysis workflow.
