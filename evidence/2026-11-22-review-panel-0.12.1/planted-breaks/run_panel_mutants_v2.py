"""Planted breaks for #69, second version (review 5b): the tests run first on the unbroken file, and nothing else runs
unless they pass. Then each (name, old, new) is applied to one file in place, the tests run, and the file is restored.

usage: python3 -I run_panel_mutants_v2.py <worktree> <file relative to it> <mutants.json> <pytest args ...>
Prints one line per break:
  caught NAME by TEST  pytest exited 1 and names the failed test (its id without parameters)
  SURVIVED NAME        every selected test passed
  ERROR NAME           any other exit (collection error, no test selected, missing package); never counted as caught
  NOT-APPLIED NAME     the old text is not in the file exactly once
The file is restored from its saved bytes after every break, also on an error."""
import json
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
target = root / sys.argv[2]
mutants = json.loads(pathlib.Path(sys.argv[3]).read_text())
tests = sys.argv[4:]
original = target.read_bytes()
# no -q here: the project's addopts already gives one, and a second one drops the summary line the baseline reads
CMD = ["uv", "run", "--offline", "--no-project", "--python", "3.13", "--with", "pytest", "pytest", "-x", "-rf",
       "-p", "no:cacheprovider"]
FAILED = re.compile(r"^FAILED ([^\s\[]+)", re.M)


def run():
    return subprocess.run(CMD + tests, cwd=root, capture_output=True, text=True)


base = run()
passed = re.search(r"(\d+) passed", base.stdout)
if base.returncode != 0 or not passed:
    print(f"baseline: exit {base.returncode} on the unbroken file; no break was run")
    print(base.stdout[-2000:] + base.stderr[-2000:])
    sys.exit(1)
print(f"baseline: exit 0, {passed.group(1)} passed on the unbroken file")
caught = survived = skipped = errors = 0
try:
    for name, old, new in mutants:
        text = original.decode()
        count = text.count(old)
        if count != 1:
            print(f"NOT-APPLIED {name} (found {count} times)")
            skipped += 1
            continue
        target.write_bytes(text.replace(old, new).encode())
        r = run()
        target.write_bytes(original)
        failed = FAILED.findall(r.stdout)
        if r.returncode == 0:
            print(f"SURVIVED {name}")
            survived += 1
        elif r.returncode == 1 and failed:
            print(f"caught {name} by {failed[0]}")
            caught += 1
        else:
            print(f"ERROR {name} (exit {r.returncode}, no failed test named)")
            errors += 1
finally:
    target.write_bytes(original)
print(f"total {len(mutants)}: caught {caught}, survived {survived}, not applied {skipped}, error {errors}")
