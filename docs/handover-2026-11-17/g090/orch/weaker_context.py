"""For each cell of the close-out replay that answers less than before: where the word the old reason names
stands in the call, and whether the old guard's own reader finds a call of another vendor's LLM tool there.

usage: python3 -I weaker_context.py <g070 dir> <old guard.py> <detail.json> [--around N]

Reads the file closeout_detail.py writes; runs nothing. Prints N characters (default 70) on each side of every
place the named word stands, any case, at most four places per cell. The output holds parts of real commands:
local only; the counts and the kinds are what goes into the repository.
"""
import json
import os
import re
import sys
import tempfile

RANK = {"silent": 0, "ask": 1, "deny": 2}


def named_words(cell):
    reason = cell["why_old"]
    if cell["rule"] == "egress-guard":
        return re.findall(r"`([^`]{1,60})`", reason)[:1]
    found = re.search(r"rule 6\): (.*?) may hold credentials", reason, re.S)
    if not found:
        return []
    words = [w for w in re.split(r"\s+", found.group(1)) if re.search(r"\.env|\.pem|secret|credential|id_rsa|\.key", w, re.I)]
    return words[:2] or [found.group(1)[:40]]


def main(argv):
    kit, old_path, detail = argv[0], argv[1], argv[2]
    around = int(argv[argv.index("--around") + 1]) if "--around" in argv else 70
    sys.path.insert(0, kit)
    import replay
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["KZ_TELEMETRY_DIR"] = scratch
        old = replay.load(old_path, "guard_replay_old")
        with open(detail, encoding="utf-8") as handle:
            data = json.load(handle)
        seen = set()
        for boundary in ("own", "client"):
            for index, cell in enumerate(data["boundaries"][boundary]["changed"]):
                if RANK[cell["new"]] >= RANK[cell["old"]]:
                    continue
                key = (cell["rule"], cell["call"])
                if key in seen:
                    continue
                seen.add(key)
                try:
                    call = json.loads('"' + cell["call"] + '"')
                except ValueError:
                    call = cell["call"]
                line = f"[{boundary} {index}] {cell['rule']} {cell['old']}->{cell['new']} x{cell['count']} | call length {len(call)}"
                if cell["rule"] == "egress-guard":
                    try:
                        read = old.reader_pass(call, old._egress_seg, "egress-guard")
                        line += f" | old reader alone: {'silent' if not read else read[0]}"
                    except Exception as exc:  # a reader that cannot read the call is a fact to print, not to hide
                        line += f" | old reader alone: {type(exc).__name__}"
                print(line)
                for word in named_words(cell):
                    places = [m.start() for m in re.finditer(re.escape(word), call, re.I)][:4]
                    for at in places:
                        part = call[max(0, at - around): at + len(word) + around].replace("\n", " \\n ")
                        print(f"      …{part}…")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
