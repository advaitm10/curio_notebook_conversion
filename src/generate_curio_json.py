"""
Python file that turns a NetworkX DiGraph object into a JSON in the format required for import into Curio. The main method allows
a user to call the core method from the CLI.
"""
import networkx as nx
import pickle
import json
import sys

def graph_to_curio(graph: nx.DiGraph, name: str) -> dict:
    """
    Method to convert NetworkX DiGraph object into a JSON in the format required for import into Curio.

    Parameters:
    A NetworkX DiGraph object.

    Returns:
    A dictionary that can be serialized into JSON.

    TODO: Add arguments and returns to every node
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

    # Reverse graph and build it from destination up to source, you can add merge flows to any node with multiple edges when reversed
    flipped = graph.reverse()
    node_ids = dict() # Key: Node name in digraph, Value: Unique ID assigned to node name TODO: Ask Fabio how IDs are set
    for k, v in flipped.adj.items():
        # Add node to JSON
        cur_node_id = node_ids.get(k, 0)
        converted['dataflow']['nodes'].append(
            {
                "id": cur_node_id,
                "type": "curio.builtin/data-loading@1", # Maybe just a placeholder for testing purposes?
                "x": node_positions[k]["x"],
                "y": node_positions[k]["y"],
                "saveOutputDataset": False, # Double check with Fabio
                "content": flipped.nodes[k]['source'],
                "out": "DEFAULT",
                "in": "DEFAULT",
                "goal": "",
                "metadata": {
                    "keywords": []
                }
            }
        )

        # Check if mergeflow is necessary
        merge_flow_id = None
        if len(v) > 1:
            merge_flow_id = 1 # TODO: Set merge_flow_id
            incoming_x = sum(node_positions[node]["x"] for node in v) / len(v)
            incoming_y = sum(node_positions[node]["y"] for node in v) / len(v)
            converted['dataflow']['nodes'].append(
                {
                    "id": merge_flow_id,
                    "type": "curio.builtin/merge-flow@1",
                    "x": (incoming_x + node_positions[k]["x"]) / 2,
                    "y": (incoming_y + node_positions[k]["y"]) / 2,
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

        # Add edges to JSON
        count = 0
        for i in v:
            targetHandle = f"in_{i}" if len(v) > 1 else "in"
            target_id = node_ids.get(i, 0)

            converted['dataflow']['edges'].append(
                {
                    "id": f"reactflow__edge-{cur_node_id}out-{target_id}in",
                    "source": merge_flow_id if merge_flow_id else target_id,
                    "target": cur_node_id,
                    "sourceHandle": "out",
                    "targetHandle": targetHandle
                }
            )

            count += 1 # Increase targetHandle counter by 1

    return converted

if __name__ == '__main__':
    target_file = sys.argv[1]
    graph = pickle.load(open(target_file, 'rb'))

    curio_json = graph_to_curio(graph)

    output_path = target_file.replace('.pkl', '_curio.json')

    with open(output_path, 'w') as outfile:
        json.dump(curio_json, outfile)
