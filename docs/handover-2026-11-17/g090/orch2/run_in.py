"""Run one command with a given working directory, without changing this shell's.

usage: python3 -I run_in.py <directory> [NAME=VALUE ...] -- CMD [ARG...]

The NAME=VALUE pairs are added to the environment of that one process. Exits with the command's code.
"""
import os
import subprocess
import sys


def main(argv):
    if "--" not in argv or len(argv) < 3:
        sys.exit(__doc__)
    cut = argv.index("--")
    env = dict(os.environ)
    for pair in argv[1:cut]:
        name, _, value = pair.partition("=")
        env[name] = value
    return subprocess.run(argv[cut + 1 :], cwd=argv[0], env=env).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
