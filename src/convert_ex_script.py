"""Convert a Jupyter notebook into Curio-compatible dataflow JSON.

Run from the repository root with::

    python src/convert_ex_script.py path/to/notebook.ipynb

The generated ``curio_json_test_<date>_2.json`` file is written to the current
working directory. The notebook is analyzed and converted; it is not executed.
"""

from generate_python_files_from_nbs import convert_nb
from lib_attribution import analyze
from analyze_notebooks import analyze_notebook
from graph_prop_labels import build_graph
from generate_curio_json import graph_to_curio

from pathlib import Path
import json
import datetime
import sys


if __name__ == '__main__':
    nb_path = sys.argv[1]
    code = convert_nb(nb_path)
    _graph, var_attribution = analyze(code)
    nb_analyzed = analyze_notebook(Path(nb_path), var_attribution)
    nb_graph = build_graph(nb_analyzed)
    # with open('../adhoc/ex_graph.pkl', 'wb') as outfile:
    #     pickle.dump(nb_graph, outfile)
    curio_json = graph_to_curio(nb_graph, Path(nb_path).stem)

    with open(f'curio_json_test_{str(datetime.datetime.today()).split()[0]}_2.json', 'w') as outfile:
        json.dump(curio_json, outfile)