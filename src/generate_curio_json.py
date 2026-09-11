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

    # Reverse graph and build it from destination up to source, you can add merge flows to any node with multiple edges when reversed
    flipped = graph.reversed()
    node_ids = dict() # Key: Node name in digraph, Value: Unique ID assigned to node name TODO: Ask Fabio how IDs are set
    for k, v in flipped.adj.items():
        # Add node to JSON
        cur_node_id = node_ids[k]
        converted['nodes'].append(
            {
                "id": cur_node_id,
                "type": None, # Maybe just a placeholder for testing purposes?
                "x": 0, # TODO: Need to figure out how to set locations, maybe look at Andres' solution or current Jupyter conversion
                "y": 0,
                "saveOutputDataset": False, # Double check with Fabio
                "content": "PLACEHOLDER CODE", # TODO: Needs to be taken from graph attributes
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
            converted['nodes'].append(
                {
                    "id": merge_flow_id,
                    "type": "curio.builtin/merge-flow@1",
                    "x": 0,
                    "y": 0,
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
            target_id = node_ids[v]

            converted['edges'].append(
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
