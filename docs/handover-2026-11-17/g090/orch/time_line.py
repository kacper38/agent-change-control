"""Time one rule on the line of the suite's cost test, for one or more guard files. Nothing is run: the line is
a string handed to the rule function.

usage: python3 -I time_line.py <guard.py> [<guard.py> ...] [--kb 20] [--runs 5]
"""
import importlib.util
import statistics
import sys
import time


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_time_{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    files, kb, runs = [], 20, 5
    it = iter(argv)
    for a in it:
        if a == "--kb":
            kb = int(next(it))
        elif a == "--runs":
            runs = int(next(it))
        else:
            files.append(a)
    unit = "grep -E 'a|ollama|b' f; "
    for n, path in enumerate(files):
        g = load(path, n)
        for tail in ("", "ollama run m"):
            command = unit * (kb * 1000 // len(unit)) + tail
            took = []
            got = None
            for _ in range(runs):
                g._nc_cached.cache_clear()
                ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                              "tool_input": {"command": command}, "cwd": "/nonexistent-scratch"})
                start = time.perf_counter()
                got = g.rule_egress_guard(ev, dict(g.DEFAULTS, boundary="client"))
                took.append(time.perf_counter() - start)
            print(f"{path.rsplit('/', 1)[-1]} | {kb} kB | tail {tail!r:16} | verdict {(got or (None,))[0]} | "
                  f"median {statistics.median(took):.3f} s | slowest {max(took):.3f} s | budget {g.HOOK_BUDGET_S} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
