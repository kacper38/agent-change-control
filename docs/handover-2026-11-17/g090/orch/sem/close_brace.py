"""Measure with the real shells what a line of groups and reports does: is the content of the named file printed?

usage: python3 -I close_brace.py <lines file> <scratch folder>

Each line of the lines file is one shell line (a line that starts with a double quote is a JSON string, so it can
carry line breaks; blank lines and lines that start with `#` are skipped). The lines name the file `.env`; before
a line runs, that name is replaced by `secret.txt`, a file this script writes into the scratch folder with one
marker line. The line then runs with `zsh -f -c` and with `bash --noprofile --norc -c`, with the scratch folder as
the working directory. Only reports (`ls`, `echo`, `test`, `true`), `cat` and `xargs cat` are expected in the lines.
Printed per line and shell: CONTENT (the marker came out: the file was read and printed), no (it ran, the marker
did not come out) or SYNTAX (the shell refused the line).
"""
import json
import os
import subprocess
import sys

MARKER = "MARKER-7f3a"
SHELLS = (("zsh", ["zsh", "-f", "-c"]), ("bash", ["bash", "--noprofile", "--norc", "-c"]))


def lines_of(path):
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            yield json.loads(line) if line.startswith('"') else line


def run(argv, line, folder):
    try:
        r = subprocess.run(argv + [line.replace(".env", "secret.txt")], cwd=folder, capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    err = r.stderr.lower()
    if "parse error" in err or "syntax error" in err or "unexpected" in err:
        return "SYNTAX"
    return "CONTENT" if MARKER in r.stdout else "no"


def main(argv):
    lines_file, folder = argv
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "secret.txt"), "w", encoding="utf-8") as fh:
        fh.write(MARKER + "\n")
    for name, shell in SHELLS:
        v = subprocess.run([shell[0], "--version"], capture_output=True, text=True).stdout.splitlines()[:1]
        print(f"# {name}: {v[0] if v else '?'}")
    for line in lines_of(lines_file):
        got = " | ".join(f"{name} {run(shell, line, folder):7}" for name, shell in SHELLS)
        print(f"{got} | {json.dumps(line) if chr(10) in line else line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
