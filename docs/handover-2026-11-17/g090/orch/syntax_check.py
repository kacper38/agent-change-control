"""Say for each command of a list whether bash and zsh accept its syntax. The shells run with -n: they read the
line from standard input, check it and execute nothing of it.

usage: python3 -I syntax_check.py <commands file or rows file> [...]

A commands file has one command per line (a line that starts with a double quote is a JSON string); in a rows
file the command is the fifth field of `id | branch | rule | expected | command`. Lines with `#` are skipped.
"""
import json
import subprocess
import sys


def commands(path):
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln.strip() or ln.startswith("#"):
                continue
            parts = ln.split(" | ", 4)
            text = parts[4] if len(parts) == 5 and parts[3] in ("ask", "deny", "silent") else ln
            yield json.loads(text) if text.startswith('"') else text


def accepts(shell, line):
    try:
        done = subprocess.run([shell, "-n"], input=line, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):  # no such shell here, or it hangs: reported as not known
        return None
    return done.returncode == 0


def main(argv):
    for path in argv:
        for line in commands(path):
            b, z = accepts("bash", line), accepts("zsh", line)
            print(f"bash {'yes' if b else 'no ' if b is not None else '?  '} | zsh {'yes' if z else 'no ' if z is not None else '?  '} | {line!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
