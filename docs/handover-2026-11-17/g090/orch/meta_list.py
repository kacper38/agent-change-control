"""List the weaker cells multiline_meta.py wrote, grouped by rewriting and rule, one line per command.

usage: python3 -I meta_list.py <weaker.json> [--kind K] [--rule R] [--minus <other weaker.json>] [--width N]
       [--max N]

--minus drops every cell (rewriting, rule, context, command) that the other file holds too: with the file of
an older guard, what is left is weaker only at the newer one. Prints, per rewriting and rule, the distinct
commands with the contexts and the verdicts (as written > rewritten), then the rewritten text.
"""
import collections
import json
import sys


def main(argv):
    path = argv[0]
    kind = rule = minus = None
    width, most = 150, 40
    it = iter(argv[1:])
    for a in it:
        if a == "--kind":
            kind = next(it)
        elif a == "--rule":
            rule = next(it)
        elif a == "--minus":
            minus = next(it)
        elif a == "--width":
            width = int(next(it))
        elif a == "--max":
            most = int(next(it))
    with open(path, encoding="utf-8") as fh:
        cells = json.load(fh)
    if minus:
        with open(minus, encoding="utf-8") as fh:
            old = {(c["kind"], c["rule"], c["branch"], c["boundary"], c["command"]) for c in json.load(fh)}
        cells = [c for c in cells if (c["kind"], c["rule"], c["branch"], c["boundary"], c["command"]) not in old]
    turns = collections.Counter((c["as_written"], c["rewritten"]) for c in cells)
    print("turns: " + ", ".join(f"{a}>{b} {n}" for (a, b), n in sorted(turns.items())))
    only = None
    if "--turn" in argv:  # --turn deny>ask: only cells with that turn
        only = tuple(argv[argv.index("--turn") + 1].split(">"))
    groups = collections.OrderedDict()
    for c in cells:
        if kind and c["kind"] != kind or rule and c["rule"] != rule:
            continue
        if only and (c["as_written"], c["rewritten"]) != only:
            continue
        key = (c["kind"], c["rule"])
        per = groups.setdefault(key, collections.OrderedDict())
        entry = per.setdefault(c["command"], {"ctx": [], "verdict": f"{c['as_written']}>{c['rewritten']}",
                                              "text": c["text"]})
        entry["ctx"].append(("m" if c["branch"] == "main" else "f") + "@" + c["boundary"])
    print(f"weaker cells {len(cells)} | distinct commands {len({c['command'] for c in cells})}")
    for (k, r), per in groups.items():
        print(f"== {k} | {r} | commands {len(per)}")
        for n, (command, e) in enumerate(per.items()):
            if n >= most:
                print(f"   ... {len(per) - most} more")
                break
            print(f"   [{','.join(e['ctx'])} {e['verdict']}] {json.dumps(e['text'])[:width]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
