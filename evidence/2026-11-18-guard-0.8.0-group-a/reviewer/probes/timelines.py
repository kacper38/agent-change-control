"""Time the eight shell rules per command; commands are built from a data file: each line is
`<count> <head>|<repeat>|<tail>` and {i} in repeat is the index.
usage: python3 -I timelines.py <probe.py> <data> <guard.py> [...]"""
import importlib.util
import sys
import time


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"m{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = load(sys.argv[1], "probe")
guards = [load(p, n) for n, p in enumerate(sys.argv[3:])]
for ln in open(sys.argv[2], encoding="utf-8"):
    ln = ln.rstrip("\n")
    if not ln or ln.startswith("#"):
        continue
    count, spec = ln.split(" ", 1)
    head, rep, tail = spec.split("~")
    head, rep, tail = (s.replace("\\n", "\n") for s in (head, rep, tail))
    cmd = head + "".join(rep.replace("{i}", str(i)) for i in range(int(count))) + tail
    cells = []
    for g in guards:
        t0 = time.perf_counter()
        v = probe.verdicts(g, cmd, "feat/x", "own")
        cells.append(f"{time.perf_counter() - t0:7.2f}s {v[:40]}")
    print(f"{ln[:50]:52} " + " || ".join(cells), flush=True)
