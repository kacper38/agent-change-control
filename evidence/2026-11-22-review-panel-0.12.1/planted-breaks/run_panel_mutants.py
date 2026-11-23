"""Planted breaks for #69: apply each (name, old, new) to one file in place, run the given tests, restore.

usage: python3 -I run_panel_mutants.py <worktree> <file relative to it> <mutants.json> <test> [<test> ...]
Prints one line per mutant: caught (a test failed), SURVIVED (all passed), or NOT-APPLIED (old text not found once).
The file is restored from its saved bytes after every mutant, also on an error."""
import json
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
target = root / sys.argv[2]
mutants = json.loads(pathlib.Path(sys.argv[3]).read_text())
tests = sys.argv[4:]
original = target.read_bytes()
caught = survived = skipped = 0
try:
    for name, old, new in mutants:
        text = original.decode()
        if text.count(old) != 1:
            print(f"NOT-APPLIED {name} (found {text.count(old)} times)")
            skipped += 1
            continue
        target.write_bytes(text.replace(old, new).encode())
        r = subprocess.run(["uv", "run", "--offline", "--no-project", "--python", "3.13", "--with", "pytest", "pytest", "-x", "-q",
                            "-p", "no:cacheprovider", *tests], cwd=root, capture_output=True, text=True)
        if r.returncode == 0:
            print(f"SURVIVED {name}")
            survived += 1
        else:
            print(f"caught {name}")
            caught += 1
        target.write_bytes(original)
finally:
    target.write_bytes(original)
print(f"total {len(mutants)}: caught {caught}, survived {survived}, not applied {skipped}")
