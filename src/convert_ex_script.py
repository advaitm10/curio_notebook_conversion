from generate_python_files_from_nbs import convert_nb
from lib_attribution import analyze
from analyze_notebooks import analyze_notebook
from graph_prop_labels import build_graph
from generate_curio_json import graph_to_curio

from pathlib import Path
import pickle
import json
import datetime

if __name__ == '__main__':
    nb_path = '../test_data/nb_1191.ipynb'
    code = convert_nb(nb_path)
    _graph, var_attribution = analyze(code)
    nb_analyzed = analyze_notebook(Path(nb_path), var_attribution)
    nb_graph = build_graph(nb_analyzed)
    # with open('../adhoc/ex_graph.pkl', 'wb') as outfile:
    #     pickle.dump(nb_graph, outfile)
    curio_json = graph_to_curio(nb_graph, Path(nb_path).stem)

    with open(f'curio_json_test_{str(datetime.datetime.today())}.json', 'w') as outfile:
        json.dump(curio_json, outfile)