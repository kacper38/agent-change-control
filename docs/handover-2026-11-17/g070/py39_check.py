#!/usr/bin/env python3
"""A static look for code that Python 3.9 would refuse, for a machine that has no 3.9 interpreter.
It is no substitute for running the suite on 3.9: it reads the grammar and a short list of names.

usage: python3 -I py39_check.py <directory> [<directory> ...]

Checks per .py file:
  grammar   the file parses with the 3.9 grammar (no match statement, no parenthesised with-items, no except*)
  f-string  no replacement field reuses the quote of its string or holds a backslash (allowed from 3.12 only)
  union     no `X | Y` in an annotation unless the module has `from __future__ import annotations`
  calls     no zip(strict=…), no dataclass(slots=…/kw_only=…)
  names     none of a short list of names that arrived after 3.9
Prints one line per finding and a total; exit 1 when there is a finding.
"""
import ast
import os
import sys

LATER_NAMES = {  # attribute or imported name -> first version
    "pairwise": "3.10", "bit_count": "3.10", "TypeAlias": "3.10", "ParamSpec": "3.10", "TypeGuard": "3.10",
    "Concatenate": "3.10", "UnionType": "3.10", "NoneType": "3.10", "EllipsisType": "3.10", "aclosing": "3.10",
    "stdlib_module_names": "3.10", "orig_argv": "3.10", "tomllib": "3.11", "Self": "3.11", "StrEnum": "3.11",
    "LiteralString": "3.11", "assert_never": "3.11", "NotRequired": "3.11", "Required": "3.11",
    "TaskGroup": "3.11", "ExceptionGroup": "3.11", "BaseExceptionGroup": "3.11", "file_digest": "3.11",
    "NOFLAG": "3.11", "batched": "3.12", "override": "3.12",
}
LATER_ATTRS = {("datetime", "UTC"): "3.11", ("contextlib", "chdir"): "3.11", ("asyncio", "timeout"): "3.11",
               ("_dt", "UTC"): "3.11"}
LATER_BUILTINS = {"aiter": "3.10", "anext": "3.10"}


def fstring_findings(src, tree):
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = ast.get_source_segment(src, node) or ""
        body = text.lstrip("rRbBuUfF")
        quote = body[:3] if body[:3] in ('"""', "'''") else body[:1]
        if not quote:
            continue
        for part in ast.walk(node):
            if isinstance(part, ast.FormattedValue):
                expr = ast.get_source_segment(src, part.value) or ""
                if quote in expr or "\\" in expr:
                    out.append((node.lineno, f"f-string field reuses its quote or holds a backslash: {expr[:40]!r}"))
    return out


def annotation_nodes(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for a in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                if a is not None and a.annotation is not None:
                    yield a.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def findings(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    try:
        tree = ast.parse(src, filename=path, feature_version=(3, 9))
    except SyntaxError as exc:  # the one finding that makes the rest unreadable
        return [(exc.lineno or 0, f"does not parse with the 3.9 grammar: {exc.msg}")]
    out = fstring_findings(src, tree)
    future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
                 and any(a.name == "annotations" for a in n.names) for n in tree.body)
    if not future:
        for ann in annotation_nodes(tree):
            for sub in ast.walk(ann):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                    out.append((sub.lineno, "`X | Y` in an annotation that is evaluated at run time"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            keys = {k.arg for k in node.keywords}
            if name == "zip" and "strict" in keys:
                out.append((node.lineno, "zip(strict=…) is 3.10"))
            if name == "dataclass" and keys & {"slots", "kw_only"}:
                out.append((node.lineno, "dataclass(slots=…/kw_only=…) is 3.10"))
            if name == "isinstance" and len(node.args) == 2 and isinstance(node.args[1], ast.BinOp):
                out.append((node.lineno, "isinstance(x, A | B) is 3.10"))
            if isinstance(node.func, ast.Name) and node.func.id in LATER_BUILTINS:
                out.append((node.lineno, f"{node.func.id}() is {LATER_BUILTINS[node.func.id]}"))
        elif isinstance(node, ast.Attribute):
            base = getattr(node.value, "id", None)
            if (base, node.attr) in LATER_ATTRS:
                out.append((node.lineno, f"{base}.{node.attr} is {LATER_ATTRS[(base, node.attr)]}"))
            elif node.attr in LATER_NAMES:
                out.append((node.lineno, f".{node.attr} is {LATER_NAMES[node.attr]}"))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                last = alias.name.rpartition(".")[2]
                if last in LATER_NAMES:
                    out.append((node.lineno, f"import of {alias.name} is {LATER_NAMES[last]}"))
    return sorted(set(out))


def main(argv):
    total = files = 0
    for root_dir in argv[1:]:
        for folder, dirs, names in os.walk(root_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for name in sorted(names):
                if not name.endswith(".py"):
                    continue
                files += 1
                path = os.path.join(folder, name)
                for line, what in findings(path):
                    total += 1
                    print(f"{path}:{line}: {what}")
    print(f"py39 check: {files} files, {total} finding(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
