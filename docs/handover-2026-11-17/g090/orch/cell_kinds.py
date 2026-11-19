"""Put the weaker cells no due row asks for to a kind of group C, so that each can be read against its kind.

usage: python3 -I cell_kinds.py <unexplained.json> [--kind K6] [--width N] [--known FILE]

Reads the file weaker_cells.py writes with --json. A cell is weaker when the new guard answers less than guard
0.8.0. The kind is a first guess from the rule and the words of the command; the guess is what the list is
sorted by, not a verdict: every distinct command is printed once under its kind, to be read. Commands that fit
no kind come first. --known FILE: a file of commands (one per line, JSON string when it starts with a double
quote) already read and accepted; they are counted and not printed. Nothing is run.
"""
import collections
import json
import re
import sys

SEARCH = r"\b(grep|egrep|fgrep|zgrep|rg|ag|ack|GREP|RG|AG|ACK|EGREP|ggrep|gegrep)\b"
HELP = r"(\s--help|\s-h|\s--version|\s-V|\shelp)\b"
GUESS = (
    ("host-install", "K1 find's pattern operand", r"\bfind\b.*\s-(i?name|i?path|i?regex|i?wholename|lname)\b"),
    ("delete-guard", "K2 git restore --staged", r"\bgit\b.*\brestore\b.*(\s--staged\b|\s-[a-zA-Z]*S)"),
    ("delete-guard", "K5 help probe", HELP),
    ("delete-guard", "K4 preview", r"(--dry-run|\s-[a-zA-Z]*n[a-zA-Z]*\b)"),
    ("deploy-ask", "K5 help probe", HELP),
    ("deploy-ask", "K4 preview", r"--dry-run"),
    ("host-install", "K5 help probe", HELP),
    ("secret-shell", "K9 echo/printf text", r"\b(echo|printf)\b"),
    ("secret-shell", "K7 git report", r"\bgit\b.*\b(check-ignore|ls-files|status)\b"),
    ("secret-shell", "K6 ls/stat/test", r"(\bg?ls\b|\bg?stat\b|\btest\b|\[)"),
    ("secret-shell", "K8 exclude option", r"--exclude(-dir)?\b"),
    ("secret-shell", "K3 search pattern", SEARCH),
    ("egress-guard", "K10 command -v", r"\bcommand\s+-[vV]\b"),
    ("egress-guard", "K11 quoted pattern", SEARCH + r".*['\"][^'\"]*\|"),
)


def kind_of(rule, command):
    for want, kind, pattern in GUESS:
        if want == rule and re.search(pattern, command):
            return kind
    return "NO KIND"


def commands_in(path):
    out = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            try:
                out.add(json.loads(line) if line.startswith('"') else line)
            except ValueError:
                out.add(line)
    return out


def main(argv):
    only = argv[argv.index("--kind") + 1] if "--kind" in argv else None
    width = int(argv[argv.index("--width") + 1]) if "--width" in argv else 170
    known = commands_in(argv[argv.index("--known") + 1]) if "--known" in argv else set()
    with open(argv[0], encoding="utf-8") as handle:
        cells = json.load(handle)
    groups = collections.OrderedDict()   # (kind, rule) -> command -> contexts
    for cell in cells:
        kind = kind_of(cell["rule"], cell["command"])
        per = groups.setdefault((kind, cell["rule"]), collections.OrderedDict())
        per.setdefault(cell["command"], []).append(f"{cell['branch']}@{cell['boundary']} {cell['old']}>{cell['new']}")
    total = len(cells)
    print(f"weaker cells no due row asks for: {total} | distinct commands: {len({c['command'] for c in cells})}")
    for (kind, rule), per in sorted(groups.items(), key=lambda kv: (kv[0][0] != "NO KIND", kv[0])):
        cells_here = sum(len(v) for v in per.values())
        seen = sum(1 for command in per if command in known)
        print(f"\n== {kind} | {rule} | cells {cells_here} | commands {len(per)} | read before {seen}")
        if only and not kind.startswith(only):
            continue
        for command, contexts in per.items():
            if command in known:
                continue
            directions = sorted({c.split(" ")[1] for c in contexts})
            places = ",".join(sorted({c.split(" ")[0].replace("feat/x@", "f@").replace("main@", "m@") for c in contexts}))
            print(f"  [{places} {'/'.join(directions)}] {json.dumps(command, ensure_ascii=False)[1:-1][:width]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
