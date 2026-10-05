"""Extract notebook code-cell source for downstream Python analysis.

Markdown cells are ignored. Code cells are concatenated in notebook order, and
comment, IPython magic, and shell-escape lines beginning in column zero are
omitted. The ``convert_nb`` function returns the text in memory; running this
module as a script writes it to a sibling ``_no_comments.py`` file.
"""
import sys
import nbformat


def convert_nb(target_file: str) -> str:
    """Return concatenated code-cell source from a notebook.

    Args:
        target_file: Path to the source ``.ipynb`` notebook.

    Returns:
        Python source text for attribution analysis. The notebook itself is
        neither modified nor executed.
    """

    ret = ''

    notebook = nbformat.read(target_file, nbformat.NO_CONVERT)

    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            cell_code = ""
            for line in cell['source'].splitlines():
                if line == "":
                    cell_code += '\n'
                elif (line[0] != '#' and line[0] != '%' and line[0] != '!'):
                    cell_code += line + '\n'

            if (cell_code != "" and cell_code[-1] != '\n'):
                cell_code += '\n'
        else:
            continue
        ret += cell_code

    return ret


if __name__ == '__main__':
    target_file = sys.argv[1]

    output_text = convert_nb(target_file)

    output_path = target_file.replace('.ipynb', '_no_comments.py')

    with open(output_path, 'w') as outfile:
        outfile.write(output_text)