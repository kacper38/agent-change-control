"""Say whether two Python files are the same program apart from comments and docstrings.

usage: python3 -I same_code.py <a.py> <b.py>

Both files are parsed (never run); every docstring is taken out of the two syntax trees and the trees are
compared. Comments are no part of a syntax tree. Prints the verdict and the number of lines that differ in the
text; exit 0 when the programs are the same, 1 when not.
"""
import ast
import difflib
import sys


def stripped(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body[0].value.value = ""
    return ast.dump(tree), text


def main(argv):
    a, text_a = stripped(argv[0])
    b, text_b = stripped(argv[1])
    changed = sum(1 for line in difflib.unified_diff(text_a.splitlines(), text_b.splitlines(), lineterm="", n=0)
                  if line[:1] in "+-" and line[:3] not in ("+++", "---"))
    same = a == b
    print(f"text lines that differ: {changed} | syntax trees without docstrings: {'the same' if same else 'DIFFERENT'}")
    return 0 if same else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
