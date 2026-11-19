"""List the cells rewrite_regress.py wrote, all shards of one label together.

usage: python3 -I regress_list.py <out-regress/label> [--class A-new|A-old|B-own|B-inherited] [--kind K]
       [--rule R] [--max N] [--width N] [--counts] [--minus <other label>]

Without --class: A-new and B-own. Prints the count per class, then per rewriting and rule the distinct commands
with their contexts and the four verdicts (old as written, new as written > old rewritten, new rewritten), then
the rewritten text. --counts prints only the table of counts per rewriting and rule. --minus drops the cells
(class, rewriting, rule, context, command) another label holds too.
"""
import collections
import glob
import json
import sys


def read(label):
    cells = []
    for path in sorted(glob.glob(label + ".*.json")):
        with open(path, encoding="utf-8") as fh:
            cells.extend(json.load(fh))
    return cells


def key(c, cls):
    return (cls, c["kind"], c["rule"], c["branch"], c["boundary"], c["command"])


def main(argv):
    label = argv[0]
    classes, kind, rule, minus = [], None, None, None
    width, most, counts_only = 150, 25, "--counts" in argv
    it = iter(argv[1:])
    for a in it:
        if a == "--class":
            classes.append(next(it))
        elif a == "--kind":
            kind = next(it)
        elif a == "--rule":
            rule = next(it)
        elif a == "--max":
            most = int(next(it))
        elif a == "--width":
            width = int(next(it))
        elif a == "--minus":
            minus = next(it)
    classes = classes or ["A-new", "B-own"]
    cells = read(label)
    gone = set()
    if minus:
        for c in read(minus):
            for cls in c["classes"]:
                gone.add(key(c, cls))
    per = collections.Counter()
    commands = collections.defaultdict(set)
    for c in cells:
        for cls in c["classes"]:
            if key(c, cls) in gone:
                continue
            per[cls] += 1
            commands[cls].add(c["command"])
    print("cells per class: " + (", ".join(f"{k} {v} ({len(commands[k])} commands)" for k, v in sorted(per.items()))
                                 or "none"))
    for cls in classes:
        groups = collections.OrderedDict()
        for c in cells:
            if cls not in c["classes"] or key(c, cls) in gone:
                continue
            if kind and c["kind"] != kind or rule and c["rule"] != rule:
                continue
            g = groups.setdefault((c["kind"], c["rule"]), collections.OrderedDict())
            e = g.setdefault(c["command"], {"ctx": [], "text": c["text"], "v": (
                f"{c['old_written']},{c['new_written']}>{c['old_rewritten']},{c['new_rewritten']}")})
            e["ctx"].append(("m" if c["branch"] == "main" else "f") + "@" + c["boundary"])
        print(f"=== {cls}: rewritings and rules {len(groups)}")
        for (k, r), g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            print(f"== {cls} | {k} | {r} | commands {len(g)}")
            if counts_only:
                continue
            for n, e in enumerate(g.values()):
                if n >= most:
                    print(f"   ... {len(g) - most} more")
                    break
                print(f"   [{','.join(e['ctx'])} {e['v']}] {json.dumps(e['text'])[:width]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
