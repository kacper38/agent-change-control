"""For each line of a data file: what egress-guard's two passes answer on their own.

usage: python3 -I egress_passes.py <guard.py> <file of commands>      (the forms of 2026-11-18: egress-passes.txt)

The first pass splits the text at every `|`, `;` and `&&`, also inside a quoted word; the reader pass knows the
quotes. Group C's eleventh kind (K11) drops a hit of the first pass inside a search tool's pattern, and this
shows why the pass itself stays: a quoted script handed to a tool the guard does not know asks through it
alone. The commands are data handed to rule functions; nothing runs.
"""
import importlib.util
import sys


def load(path):
    spec = importlib.util.spec_from_file_location("guard_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["guard_under_test"] = module
    spec.loader.exec_module(module)
    return module


def main(argv):
    guard = load(argv[0])
    with open(argv[1], encoding="utf-8") as handle:
        lines = [line.rstrip("\n") for line in handle if line.strip()]
    for line in lines:
        first = None
        for seg in guard.segments(guard.strip_heredocs(line)):
            first = guard._egress_seg(seg)
            if first:
                break
        try:
            second = guard.reader_pass(line, guard._egress_seg, "egress-guard")
        except Exception as exc:  # a probe: show the error instead of hiding it
            second = ("error", type(exc).__name__)
        one, two = (first[0] if first else "silent"), (second[0] if second else "silent")
        print(f"first pass {one:<6} | reader pass {two:<6} | {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
