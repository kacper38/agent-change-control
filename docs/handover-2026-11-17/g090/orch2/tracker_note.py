"""Post one tracker note from a text file, so that no note text stands on a command line.

usage: python3 -I tracker_note.py <tracker.py> <owner/name> <issue number> <text file> [--show]

Calls `tracker.py --repo <owner/name> note <N> <text>` with the file's text (stripped at both ends) as one
argument. With --show the text is printed and nothing is sent.
"""
import subprocess
import sys


def main(argv):
    tracker, repo, number, path = argv[:4]
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    if "--show" in argv:
        print(f"NOTE for #{number} in {repo} ({len(text)} chars):\n{text}")
        return 0
    return subprocess.run([sys.executable, tracker, "--repo", repo, "note", number, text]).returncode


if __name__ == "__main__":
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
