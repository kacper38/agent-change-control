"""List the frozen rows that expect `silent` and name a secret-looking path on a line with shell structure.

usage: python3 -I silent_structure_rows.py <rows file> [<rows file> ...] [--all]

A row is `id | branch[@client] | rule | expected | command` (a command that starts with a double quote is a JSON
string). Printed: per file the number of rows that expect `silent`, and of those the rows whose command holds a
brace, a reserved word, a quote, a backslash, a substitution or a double bracket, grouped by what they hold, so
that a stricter reading can be judged against what the rows need. Read-only; nothing is run.
"""
import collections
import json
import re
import sys

STRUCT = {"{", "}", "if", "then", "else", "elif", "fi", "while", "until", "do", "done", "for", "select", "case",
          "esac", "time", "repeat", "function", "coproc", "!", "[[", "]]"}


def rows(path):
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split(" | ", 4)
            if len(parts) != 5:
                continue
            ident, where, rule, expected, command = parts
            if command.startswith('"'):
                try:
                    command = json.loads(command)
                except ValueError:
                    pass
            yield ident.strip(), where.strip(), rule.strip(), expected.strip(), command


def traits(command):
    found = []
    words = re.split(r"[\s;&|()<>]+", command)
    if any(w in STRUCT for w in words):
        found.append("structure word")
    if "$(" in command or "`" in command:
        found.append("substitution")
    if "$'" in command:
        found.append("ansi-c quote")
    if "${" in command or "$[" in command:
        found.append("parameter braces")
    if re.search(r"['\"\\]", command):
        found.append("quote or backslash")
    return found


def main(argv):
    show_all = "--all" in argv
    files = [a for a in argv if a != "--all"]
    per_trait = collections.defaultdict(list)
    total = 0
    for path in files:
        silent = [r for r in rows(path) if r[3] == "silent"]
        total += len(silent)
        for r in silent:
            for t in traits(r[4]):
                per_trait[t].append((path.rsplit("/", 1)[-1], r))
    print(f"rows that expect silent: {total}")
    for t in sorted(per_trait):
        cmds = collections.OrderedDict()
        for name, r in per_trait[t]:
            cmds.setdefault(r[4], (name, r))
        print(f"== {t}: rows {len(per_trait[t])} | distinct commands {len(cmds)}")
        if show_all or t != "quote or backslash":
            for command, (name, r) in cmds.items():
                print(f"   {name} {r[0]} [{r[2]}] {json.dumps(command)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
