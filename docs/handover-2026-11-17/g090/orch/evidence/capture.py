"""Run the repository's capture tool with a checkout as its working directory, without changing this shell's.

usage: python3 -I capture.py <checkout> <tag> <name> -- CMD [ARG...]

Calls `<checkout>/tools/tracker/evidence_export.py capture --tag <tag> --name <name> -- CMD…` with the checkout
as the working directory of that one process, and exits with its code.
"""
import subprocess
import sys


def main(argv):
    checkout, tag, name = argv[0], argv[1], argv[2]
    rest = argv[4:] if argv[3:4] == ["--"] else argv[3:]
    tool = f"{checkout}/tools/tracker/evidence_export.py"
    return subprocess.run([sys.executable, tool, "capture", "--tag", tag, "--name", name, "--", *rest],
                          cwd=checkout).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
