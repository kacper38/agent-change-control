#!/usr/bin/env python3
"""Why each changed cell of the close-out replay changed: where the named word stands, and what the twin does.

usage: python3 -I closeout_cells.py <g070 dir> <old guard.py> <new guard.py> <detail.json>
<detail.json> is the file closeout_detail.py writes. The output holds parts of real commands: local only.
For an egress cell: the word the new guard names, 45 characters around each place it stands (any case), and the
verdict of both guards for the same call with that word written in lower case. Runs nothing.
"""
import json
import os
import re
import sys
import tempfile


def verdict(replay, guard, tool_input, boundary):
    return replay.verdicts(guard, ["egress-guard", "git-guard"], "Bash", tool_input, "/nonexistent-scratch",
                           "feat/x", boundary)


def main(argv):
    kit, old_path, new_path, detail = argv
    sys.path.insert(0, kit)
    import replay
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["KZ_TELEMETRY_DIR"] = scratch
        old, new = replay.load(old_path, "guard_replay_old"), replay.load(new_path, "guard_replay_new")
        with open(detail, encoding="utf-8") as handle:
            data = json.load(handle)
        for number, cell in enumerate(data["boundaries"]["client"]["changed"], 1):
            command = json.loads('"' + cell["call"] + '"')
            rule = cell["rule"]
            print(f"\n#{number} {rule} {cell['old']}->{cell['new']} | {len(command)} characters")
            if rule == "egress-guard":
                word = re.search(r"`([^`]+)`", cell["why_new"]).group(1)
                places = [m.start() for m in re.finditer(re.escape(word), command, flags=re.I)]
                print(f"   word `{word}`, stands {len(places)} times")
                for at in places[:4]:
                    around = command[max(0, at - 45):at + len(word) + 45]
                    print("   … " + json.dumps(around)[1:-1] + " …")
                same = verdict(replay, old, {"command": command}, "client")["egress-guard"], \
                    verdict(replay, new, {"command": command}, "client")["egress-guard"]
                twin = re.sub(re.escape(word), word, command, flags=re.I)
                low = verdict(replay, old, {"command": twin}, "client")["egress-guard"], \
                    verdict(replay, new, {"command": twin}, "client")["egress-guard"]
                print(f"   as written: old {same[0]}, new {same[1]} | word in lower case: old {low[0]}, new {low[1]}"
                      f" | twin differs from the call: {twin != command}")
            else:
                for m in list(re.finditer(r"hooksPath", command))[:4]:
                    around = command[max(0, m.start() - 110):m.end() + 70]
                    print("   … " + json.dumps(around)[1:-1] + " …")
                print("   first 90 characters: " + json.dumps(command[:90])[1:-1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
