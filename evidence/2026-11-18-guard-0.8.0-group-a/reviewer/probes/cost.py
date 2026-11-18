"""Time the eight shell rules on generated ~100 kB commands, plain and with one tool name in capitals.
usage: python3 -I cost.py <probe.py> <pieces.json> <guard.py> [<guard.py> ...] [--only name]"""
import importlib.util
import json
import sys
import time


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"m{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(head, body, tail, size=100_000):
    parts, i, n = [head], 0, len(head) + len(tail)
    while n < size:
        p = body.replace("{i}", str(i))
        parts.append(p)
        n += len(p)
        i += 1
    parts.append(tail)
    return "".join(parts)


def main(argv):
    only = None
    if "--only" in argv:
        k = argv.index("--only")
        only = argv[k + 1]
        argv = argv[:k] + argv[k + 2 :]
    probe = load(argv[1], "probe")
    pieces = json.load(open(argv[2], encoding="utf-8"))
    guards = [load(p, n) for n, p in enumerate(argv[3:])]
    for name, (head, body, tail) in pieces.items():
        if only and name != only:
            continue
        plain = build(head, body, tail)
        # one tool name in capitals in front: every rule reads the command twice
        caps = build("ECHO x; " + head, body, tail)
        for label, cmd in (("plain", plain), ("caps", caps)):
            cells = []
            for g in guards:
                t0 = time.perf_counter()
                v = probe.verdicts(g, cmd, "feat/x", "client")
                cells.append(f"{time.perf_counter() - t0:6.2f}s {v[:60]}")
            print(f"{name:18} {label:5} {len(cmd):7}  " + "  ||  ".join(cells), flush=True)


main(sys.argv)
