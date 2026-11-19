"""A second, wider look through a folder for names of other projects and for texts that look like credentials.

usage: python3 -I scan_more.py <harness projects folder> <folder to scan>

Names: every entry of the projects folder, cut after `-Users-<user>-` and before `--claude-worktrees-`; the whole
rest and the rest behind its first part (`Developer-x-y` gives `Developer-x-y` and `x-y`) are searched as whole
words, without regard to case. Names shorter than five characters and this repository's own are left out.
Credentials: a few well-known prefixes. Prints file and line number, never the line or the name.
"""
import os
import re
import sys

OWN = {"agent-change-control", "developer-agent-change-control"}
CRED = [r"ghp_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}", r"gho_[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}",
        r"sk-[A-Za-z0-9_-]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"xox[baprs]-[A-Za-z0-9-]{10,}",
        r"hf_[A-Za-z0-9]{20,}", r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"]


def names_of(folder):
    names = set()
    for entry in os.listdir(folder):
        m = re.match(r"^-Users-[^-]+-(.+)$", entry) or re.match(r"^-private-tmp-(.+)$", entry)
        if not m:
            continue
        rest = m.group(1).split("--claude-worktrees-")[0]
        for cand in (rest, rest.split("-", 1)[1] if "-" in rest else ""):
            low = cand.lower()
            if len(low) >= 5 and low not in OWN and not low.endswith("agent-change-control"):
                names.add(low)
    return names


def main(argv):
    projects, folder = argv
    names = sorted(names_of(projects))
    hits = 0
    files = 0
    for root, _dirs, fs in os.walk(folder):
        for name in sorted(fs):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, folder)
            files += 1
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            for n, line in enumerate(lines, 1):
                low = line.lower()
                for k, nm in enumerate(names):
                    if re.search(r"(?<![a-z0-9])" + re.escape(nm) + r"(?![a-z0-9])", low):
                        hits += 1
                        print(f"NAME #{k} in {rel}:{n}")
                for k, pat in enumerate(CRED):
                    if re.search(pat, line):
                        hits += 1
                        print(f"CREDENTIAL SHAPE #{k} in {rel}:{n}")
    print(f"entries {len(os.listdir(projects))} | names searched {len(names)} | files {files} | hits {hits}")
    return 1 if hits else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
