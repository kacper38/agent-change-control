"""Assemble the evidence folder of guard 0.9.0 (groups B and C) from the session's scratch files.

usage: python3 -I assemble.py <plan.json> copy        copy every file of the plan into the folder (local paths replaced)
       python3 -I assemble.py <plan.json> scan        look through the folder for local paths and private names
       python3 -I assemble.py <plan.json> sums        write SHA256SUMS over every file of the folder but itself

The plan is a JSON object: {"folder": <evidence folder>, "replace": [[text, placeholder], ...],
"files": [[source, name in the folder], ...], "forbidden": [text, ...], "names_from": <folder whose entries name
other projects, or null>}. Every file is read as UTF-8 text and written with the texts of `replace` exchanged in
the order given (longest first is the caller's job). `scan` exits 1 when a forbidden text, or the name of another
project taken from `names_from`, stands in a file of the folder; it prints the file and the line number, never
the line.
"""
import hashlib
import json
import os
import re
import sys


def project_names(folder):
    """Names of other projects, from the entries of the harness's projects folder (`-Users-x-Developer-<name>`)."""
    names = set()
    if not folder or not os.path.isdir(folder):
        return names
    for entry in os.listdir(folder):
        m = re.match(r"^-Users-[^-]+-(?:Developer|Projects|Documents|src|code|work)-(.+)$", entry)
        if not m:
            continue
        tail = m.group(1)
        base = tail.split("--claude-worktrees-")[0]
        if base and base != "agent-change-control" and len(base) >= 5:
            names.add(base)
    return names


def files_of(folder):
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            yield os.path.join(root, name)


def main(argv):
    with open(argv[0], encoding="utf-8") as fh:
        plan = json.load(fh)
    folder, verb = plan["folder"], argv[1]
    if verb == "copy":
        for source, name in plan["files"]:
            with open(source, encoding="utf-8") as fh:
                text = fh.read()
            for old, new in plan["replace"]:
                text = text.replace(old, new)
            target = os.path.join(folder, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text if text.endswith("\n") or not text else text + "\n")
            print(f"copied {name} ({len(text)} chars)")
        return 0
    if verb == "scan":
        forbidden = list(plan["forbidden"])
        names = sorted(project_names(plan.get("names_from")))
        bad = 0
        for path in files_of(folder):
            rel = os.path.relpath(path, folder)
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
            except UnicodeDecodeError:
                print(f"NOT TEXT: {rel}")
                bad += 1
                continue
            for n, line in enumerate(lines, 1):
                low = line.lower()
                for text in forbidden:
                    if text.lower() in low:
                        bad += 1
                        print(f"FORBIDDEN TEXT #{forbidden.index(text)} in {rel}:{n}")
                for k, name in enumerate(names):
                    if re.search(r"(?<![A-Za-z0-9])" + re.escape(name.lower()) + r"(?![A-Za-z0-9])", low):
                        bad += 1
                        print(f"PROJECT NAME #{k} in {rel}:{n}")
        print(f"files {sum(1 for _ in files_of(folder))} | forbidden texts {len(forbidden)} | project names "
              f"checked {len(names)} | hits {bad}")
        return 1 if bad else 0
    if verb == "sums":
        rows = []
        for path in files_of(folder):
            rel = os.path.relpath(path, folder)
            if rel == "SHA256SUMS":
                continue
            with open(path, "rb") as fh:
                rows.append(f"{hashlib.sha256(fh.read()).hexdigest()}  {rel}")
        with open(os.path.join(folder, "SHA256SUMS"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(sorted(rows, key=lambda r: r.split("  ", 1)[1])) + "\n")
        print(f"SHA256SUMS: {len(rows)} files")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
