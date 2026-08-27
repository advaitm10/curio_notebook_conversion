"""
Python file that turns a NetworkX DiGraph object into a JSON in the format required for import into Curio. The main method allows
a user to call the core method from the CLI.
"""
import networkx as nx
import pickle
import json
import sys

def graph_to_curio(graph) -> dict:
    """
    Method to convert NetworkX DiGraph object into a JSON in the format required for import into Curio.

    Parameters:
    A NetworkX DiGraph object.

    Returns:
    A dictionary that can be serialized into JSON.
    """
    pass

if __name__ == '__main__':
    target_file = sys.argv[1]
    graph = pickle.load(open(target_file, 'rb'))

    curio_json = graph_to_curio(graph)

    output_path = target_file.replace('.pkl', '_curio.json')

    with open(output_path, 'w') as outfile:
        json.dump(curio_json, outfile)
