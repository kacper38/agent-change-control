"""Create one tracker item from a JSON file, so that no item text stands on a command line.

usage: python3 -I tracker_new.py <tracker.py> <owner/name> <item.json> [--show]

The JSON object has the keys title, ac (a list), scope, scope_limit, source and, optionally, type. With --show
the item is printed as it would be composed and nothing is sent.
"""
import json
import subprocess
import sys


def main(argv):
    tracker, repo, path = argv[0], argv[1], argv[2]
    with open(path, encoding="utf-8") as fh:
        item = json.load(fh)
    if "--show" in argv:
        print("TITLE (" + str(len(item["title"])) + " chars): " + item["title"])
        for n, ac in enumerate(item["ac"], 1):
            print(f"AC {n}: {ac}")
        print("SCOPE: " + item["scope"])
        print("SCOPE LIMIT: " + item["scope_limit"])
        print("SOURCE: " + item["source"])
        print("TYPE: " + item.get("type", "todo"))
        return 0
    cmd = [sys.executable, tracker, "--repo", repo, "new", "--title", item["title"]]
    for ac in item["ac"]:
        cmd += ["--ac", ac]
    cmd += ["--scope", item["scope"], "--scope-limit", item["scope_limit"], "--source", item["source"],
            "--type", item.get("type", "todo")]
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
