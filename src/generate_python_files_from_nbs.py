"""
Python file that turns a Jupyter notebook into a python file that concatenates all the code blocks
of the notebook together and removes any comments. The main function allows a user to call the core method from the CLI.
"""
import sys
import nbformat

def convert_nb(target_file):
    """
    Method to convert Jupyter notebook into a python file without comments or markdown.

    Parameters:
    A string of the path to the target .ipynb file.

    Returns:
    A string representing the python file in memory
    """

    ret = ''

    notebook = nbformat.read(target_file, nbformat.NO_CONVERT)

    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            cell_code = ""
            for line in cell['source'].splitlines():
                if line == "":
                    cell_code += '\n'
                elif (line[0] != '#' or line[0] != '%' or line[0] != '!'):
                    cell_code += line + '\n'

            if (cell_code != "" and cell_code[-1] != '\n'):
                cell_code += '\n'
        ret += cell_code

    return ret


if __name__ == '__main__':
    target_file = sys.argv[1]

    output_text = convert_nb(target_file)

    output_path = target_file.replace('.ipynb', '_no_comments.py')

    with open(output_path, 'w') as outfile:
        outfile.write(output_text)