#!/usr/bin/env python3
"""brief_lint — a worker brief names every field once and leaves none empty (plan step 1.3).

  python3 tools/orchestration/brief_lint.py FILE [FILE ...]

A brief is Markdown; its fields are `## ` headings with the names in FIELDS, in any order, each body running to
the next `## ` heading. HTML comments do not count as content, so the bare template fails. `Done evidence` must
hold the command (an inline code span or a fenced block); `Size limit` must hold a number. Other headings are
ignored. Exit codes: 0 every file passes, 1 a problem or an unreadable file, 2 usage.
"""
from __future__ import annotations

import re
import sys

FIELDS = ("Goal", "Decisions not to reopen", "Scope", "Writable paths", "Forbidden paths", "Forbidden actions",
          "What to ignore", "Done evidence", "Output format", "Report fields", "Size limit")
COMMENT = re.compile(r"<!--.*?-->", re.S)
CODE = re.compile(r"`[^`\n]+`|^\s*```", re.M)


def sections(text: str) -> list:
    """[(heading name, body)] for every `## ` heading outside a fenced block."""
    out, fence, name, body = [], False, None, []
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            if name is not None:
                out.append((name, "\n".join(body)))
            name, body = line[3:].strip(), []
        elif name is not None:
            body.append(line)
    if name is not None:
        out.append((name, "\n".join(body)))
    return out


def lint(text: str) -> list:
    found = {}
    for name, body in sections(text):
        found.setdefault(name, []).append(COMMENT.sub("", body).strip())
    problems = []
    for field in FIELDS:
        bodies = found.get(field, [])
        if len(bodies) != 1:
            problems.append(f'field "{field}" is missing' if not bodies else f'field "{field}" is given twice')
            continue
        body = bodies[0]
        if not body:
            problems.append(f'field "{field}" is empty')
        elif field == "Done evidence" and not CODE.search(body):
            problems.append('field "Done evidence" names no command (an inline code span or a fenced block)')
        elif field == "Size limit" and not re.search(r"[0-9]", body):
            problems.append('field "Size limit" holds no number')
    return problems


def main(argv: list | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or any(a.startswith("-") for a in argv):
        sys.stderr.write("usage: brief_lint.py FILE [FILE ...]\n")
        raise SystemExit(2)
    rc = 0
    for path in argv:
        try:
            with open(path, encoding="utf-8") as fh:
                problems = lint(fh.read())
        except (OSError, UnicodeDecodeError) as exc:
            problems = [f"cannot read: {exc}"]
        for p in problems:
            print(f"brief_lint: {path}: {p}")
        if problems:
            rc = 1
        else:
            print(f"brief_lint: {path}: ok")
    return rc


if __name__ == "__main__":
    sys.exit(main())
