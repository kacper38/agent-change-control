"""Show, for every row of a rows file, what each guard answers and what each shell prints, side by side.

usage: python3 -I rows_verdicts.py <rows file> <scratch folder> <guard.py> [<guard.py> ...]

A row is `id | branch[@client] | rule | expected | command`; a command that starts with a double quote is a JSON
string. Every command is judged by rule_secret_shell of every guard, as a string (never run by the guard), on a
feature branch in the kit's own boundary. Then it is run once per shell with `.env` replaced by `secret.txt`, a
stand-in this script writes into the scratch folder with one marker line, by `zsh -f -c` and
`bash --noprofile --norc -c`, the scratch folder as working directory, standard input closed. Printed per row:
the id, the expectation, one letter per guard (s silent, a ask, d deny), `Z` when zsh prints the content, `B`
when bash does, and the command.
"""
import importlib.util
import json
import os
import subprocess
import sys

MARKER = "MARKER-7f3a"
SHELLS = (("Z", ["zsh", "-f", "-c"]), ("B", ["bash", "--noprofile", "--norc", "-c"]))


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_rows_{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verdict(g, command):
    g._nc_cached.cache_clear()
    ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                  "cwd": "/nonexistent-scratch"})
    try:
        got = g.rule_secret_shell(ev, dict(g.DEFAULTS))
    except Exception as exc:  # a crash is a finding of its own
        return "!" + type(exc).__name__
    return (got or ("silent",))[0][0]


def main(argv):
    rows_file, scratch, guards = argv[0], argv[1], [load(p, n) for n, p in enumerate(argv[2:])]
    os.makedirs(scratch, exist_ok=True)
    with open(os.path.join(scratch, "secret.txt"), "w", encoding="utf-8") as fh:
        fh.write(MARKER + "\n")
    with open(rows_file, encoding="utf-8") as fh:
        lines = [x.rstrip("\n") for x in fh if x.strip() and not x.lstrip().startswith("#")]
    for line in lines:
        rid, _branch, _rule, expected, command = [p.strip() for p in line.split(" | ", 4)]
        if command.startswith('"'):
            command = json.loads(command)
        answers = "".join(verdict(g, command) for g in guards)
        run = command.replace(".env", "secret.txt")
        printed = ""
        for letter, argv_shell in SHELLS:
            try:
                res = subprocess.run(argv_shell + [run], cwd=scratch, stdin=subprocess.DEVNULL, capture_output=True,
                                     text=True, timeout=10)
                printed += letter if MARKER in res.stdout + res.stderr else "-"
            except subprocess.TimeoutExpired:
                printed += "T"
        print(f"{rid:4} {expected:6} guards {answers:4} shells {printed} | {json.dumps(command)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
