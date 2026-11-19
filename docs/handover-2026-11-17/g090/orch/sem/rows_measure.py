"""Run the command of every row of a rows file in the real shells and say whether the content of the named file
comes out: the measurement behind the rows of the fifth fix round.

usage: python3 -I rows_measure.py <rows file> <scratch folder> [--show]

A row is `id | branch[@client] | rule | expected | command`; a command that starts with a double quote is a JSON
string. Each distinct command runs once per shell, with `.env` replaced by `secret.txt`, a stand-in this script
writes into the scratch folder with one marker line, by `zsh -f -c` and `bash --noprofile --norc -c`, the scratch
folder as working directory. The rows hold reports (`ls`, `echo`, `test`, `printf`, `stat`, `[[ ]]`), `true`, `:`,
`cat`, `xargs cat`, a few read-only tools (`grep`, `date`, `hostname`, `whoami`, `id`, `wc`) and two lines that
append a name to `.gitignore`, which lands in the scratch folder.

Printed: per family (the row id) and expectation, how many commands print the content in zsh only, in bash only,
in both, in none. The script fails (exit 1) when a row of a family other than `Fs` expects `ask` and no shell
prints the content, or when a row expects `silent` and a shell prints it. --show lists every command.
"""
import collections
import json
import os
import subprocess
import sys

MARKER = "MARKER-7f3a"
SHELLS = (("zsh", ["zsh", "-f", "-c"]), ("bash", ["bash", "--noprofile", "--norc", "-c"]))


def rows_of(path):
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            rid, _ctx, _rule, expected, command = [p.strip() for p in line.split(" | ", 4)]
            yield rid, expected, json.loads(command) if command.startswith('"') else command


def run(argv, line, folder):
    try:
        r = subprocess.run(argv + [line.replace(".env", "secret.txt")], cwd=folder, capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    if MARKER in r.stdout or MARKER in r.stderr:
        return "CONTENT"
    err = r.stderr.lower()
    return "SYNTAX" if ("parse error" in err or "syntax error" in err) else "no"


def main(argv):
    show = "--show" in argv
    path, folder = [a for a in argv if a != "--show"]
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "secret.txt"), "w", encoding="utf-8") as fh:
        fh.write(MARKER + "\n")
    seen = {}
    counts = collections.Counter()
    bad = []
    for rid, expected, command in rows_of(path):
        if command not in seen:
            seen[command] = {name: run(argv_, command, folder) for name, argv_ in SHELLS}
            got = seen[command]
            printed = [name for name in ("zsh", "bash") if got[name] == "CONTENT"]
            where = "both" if len(printed) == 2 else (printed[0] + " only" if printed else "none")
            counts[(rid, expected, where)] += 1
            if show:
                print(f"{rid:4} {expected:6} zsh {got['zsh']:7} bash {got['bash']:7} | {json.dumps(command)}")
            if expected == "ask" and rid != "Fs" and not printed:
                bad.append((rid, expected, command, got))
            if expected == "silent" and printed:
                bad.append((rid, expected, command, got))
    print(f"rows file: {os.path.basename(path)} | distinct commands {len(seen)}")
    for (rid, expected, where), n in sorted(counts.items()):
        print(f"  {rid:4} expects {expected:6} | content printed by {where:9} | {n} commands")
    print(f"ROWS AGAINST THE SHELLS: {len(bad)} disagree")
    for rid, expected, command, got in bad:
        print(f"  {rid} expects {expected}, zsh {got['zsh']}, bash {got['bash']} | {json.dumps(command)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
