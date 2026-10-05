"""Serialize a notebook cell graph as Curio-compatible dataflow JSON.

Cell labels select Curio built-in node templates using
``DEFAULT_NODE_TYPE_MAP``. Nodes are positioned by graph depth, and a
``curio.builtin/merge-flow@1`` node is inserted for every target with multiple
incoming graph edges.
"""
import networkx as nx
import pickle
import json
import sys
import uuid

def generate_id() -> str:
    return uuid.uuid4().hex


DEFAULT_NODE_TYPE_MAP: dict[str, str] = {
    "data collection": "curio.builtin/data-loading@1",
    "wrangling": "curio.builtin/data-transformation@1",
    "training": "curio.builtin/computation-analysis@1",
    "evaluation": "curio.builtin/computation-analysis@1",
    "exploration": "curio.builtin/data-transformation@1",
    "unclassified": "curio.builtin/data-transformation@1",
}


def _node_type_for_label(label: str | None, override: dict[str, str] | None = None, default: str = "curio.builtin/data-transformation@1") -> str:
    """Resolve a cell label to its Curio node type.

    ``override`` entries replace matching defaults; missing and unknown labels
    resolve to ``default``.
    """
    mapping = DEFAULT_NODE_TYPE_MAP if override is None else {**DEFAULT_NODE_TYPE_MAP, **override}
    if not label:
        return default
    return mapping.get(label, default)


def graph_to_curio(graph: nx.DiGraph, name: str, node_type_map: dict[str, str] | None = None, default_type: str = "curio.builtin/data-transformation@1") -> dict:
    """Convert a NetworkX cell graph to Curio's ``dataflow`` JSON structure.

    Args:
        graph: Directed cell graph with ``source`` and ``cell_type`` node
            attributes.
        name: Dataflow name, typically the notebook filename without suffix.
        node_type_map: Optional label-to-Curio-type overrides. Entries replace
            the corresponding values in ``DEFAULT_NODE_TYPE_MAP``.
        default_type: Curio node type for missing or unknown labels.

    Returns:
        A dictionary suitable for JSON serialization and Curio import.
    """

    converted = {'dataflow': {
                    'nodes': [],
                    'edges': [],
                    'name': name, # Filename with extension removed
                    'task': "", # Check with Fabio
                    'timestamp': None, # Check with Fabio
                    'provenance_id': None, # Need to check with Fabio to see how to set this/if nodeProvenance and dataflowProvenance are needed
                    'packages': []
                }}

    # Condensing strongly connected components lets cyclic inputs still be
    # placed in a deterministic layer without changing their graph structure.
    layered_graph = nx.condensation(graph)
    node_layers = {}
    for layer, components in enumerate(nx.topological_generations(layered_graph)):
        for component in components:
            for node in layered_graph.nodes[component]["members"]:
                node_layers[node] = layer

    nodes_by_layer = {}
    for node in graph.nodes:
        nodes_by_layer.setdefault(node_layers[node], []).append(node)

    node_positions = {}
    for layer, nodes in nodes_by_layer.items():
        for row, node in enumerate(nodes):
            node_positions[node] = {"x": layer * 500, "y": row * 300}

    node_ids = {node: generate_id() for node in graph.nodes}
    for node in graph.nodes:
        cur_node_id = node_ids[node]
        node_label = graph.nodes[node].get('cell_type')
        node_type = _node_type_for_label(node_label, override=node_type_map, default=default_type)
        converted['dataflow']['nodes'].append(
            {
                "id": cur_node_id,
                "type": node_type,
                "x": node_positions[node]["x"],
                "y": node_positions[node]["y"],
                "saveOutputDataset": False,
                "content": graph.nodes[node].get('source', ''),
                "out": "DEFAULT",
                "in": "DEFAULT",
                "goal": "",
                "metadata": {
                    "keywords": []
                }
            }
        )

        incoming = list(graph.predecessors(node))
        if len(incoming) > 1:
            merge_flow_id = generate_id()
            incoming_x = sum(node_positions[source]["x"] for source in incoming) / len(incoming)
            incoming_y = sum(node_positions[source]["y"] for source in incoming) / len(incoming)
            converted['dataflow']['nodes'].append(
                {
                    "id": merge_flow_id,
                    "type": "curio.builtin/merge-flow@1",
                    "x": (incoming_x + node_positions[node]["x"]) / 2,
                    "y": (incoming_y + node_positions[node]["y"]) / 2,
                    "saveOutputDataset": False,
                    "content": "",
                    "out": "DEFAULT",
                    "in": "DEFAULT",
                    "goal": "",
                    "metadata": {
                        "keywords": []
                    }
                }
            )

            for predecessor in incoming:
                converted['dataflow']['edges'].append(
                    {
                        "id": f"reactflow__edge-{node_ids[predecessor]}out-{merge_flow_id}in",
                        "source": node_ids[predecessor],
                        "target": merge_flow_id,
                        "sourceHandle": "out",
                        "targetHandle": "in"
                    }
                )

            converted['dataflow']['edges'].append(
                {
                    "id": f"reactflow__edge-{merge_flow_id}out-{cur_node_id}in",
                    "source": merge_flow_id,
                    "target": cur_node_id,
                    "sourceHandle": "out",
                    "targetHandle": "in"
                }
            )
        else:
            for predecessor in incoming:
                converted['dataflow']['edges'].append(
                    {
                        "id": f"reactflow__edge-{node_ids[predecessor]}out-{cur_node_id}in",
                        "source": node_ids[predecessor],
                        "target": cur_node_id,
                        "sourceHandle": "out",
                        "targetHandle": "in"
                    }
                )

    return converted

if __name__ == '__main__':
    target_file = sys.argv[1]
    graph = pickle.load(open(target_file, 'rb'))

    curio_json = graph_to_curio(graph)

    output_path = target_file.replace('.pkl', '_curio.json')

    with open(output_path, 'w') as outfile:
        json.dump(curio_json, outfile)
