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
    for k, v in flipped.adj.items():
        # Add node to JSON
        converted['nodes'].append(
            {

            }
        )

        # Check if mergeflow is necessary
        if len(v) > 1:
            pass

        # Add edges to JSON
        for i in range(len(v)):
            converted['edges'].append(
                {

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
