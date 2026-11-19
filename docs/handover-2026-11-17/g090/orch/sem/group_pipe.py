"""Measure with the real shells whether a shell behind a pipe runs what a group in front of it prints.

usage: python3 -I group_pipe.py <lines file> <scratch folder>

The scratch folder gets `run.sh` with the one line `echo RAN$((3+4))OK`: its text does not hold `RAN7OK`, only a
shell that runs it prints that. Each line of the lines file is one shell line (blank lines and lines that start
with `#` are skipped); it runs with `zsh -f -c` and with `bash --noprofile --norc -c` in the scratch folder. The
lines hold only `cat run.sh`, `echo`, `printf`, `true` and `sh`. Printed per line and shell: RAN (the script was
run by the shell behind the pipe), no (the line ran, the script did not) or SYNTAX (the shell refused the line).
"""
import os
import subprocess
import sys

SHELLS = (("zsh", ["zsh", "-f", "-c"]), ("bash", ["bash", "--noprofile", "--norc", "-c"]))


def run(argv, line, folder):
    try:
        r = subprocess.run(argv + [line], cwd=folder, capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    err = r.stderr.lower()
    if "parse error" in err or "syntax error" in err or "unexpected" in err:
        return "SYNTAX"
    return "RAN" if "RAN7OK" in r.stdout else "no"


def main(argv):
    lines_file, folder = argv
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "run.sh"), "w", encoding="utf-8") as fh:
        fh.write("echo RAN$((3+4))OK\n")
    with open(lines_file, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            got = " | ".join(f"{name} {run(shell, line, folder):6}" for name, shell in SHELLS)
            print(f"{got} | {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
