"""Check fold_names on a list of names read from a data file: upper case, title case, path in front, quotes."""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
names = open(sys.argv[2], encoding="utf-8").read().split()
miss = []
for n in names:
    for form, want in ((n.upper() + " x", n + " x"), (n.title() + " x", n + " x"),
                       ("/usr/bin/" + n.upper() + " x", "/usr/bin/" + n + " x")):
        got = g.fold_names(form)
        if got != want:
            miss.append((form, got))
print("names", len(names), "misses", len(miss))
for form, got in miss:
    print("MISS", repr(form), "->", repr(got))
print("fold set size", len(g._FOLD_NAMES))
