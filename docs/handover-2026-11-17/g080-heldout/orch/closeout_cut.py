#!/usr/bin/env python3
"""Find the smallest part of one replayed call that still makes the new guard's git-guard ask.

usage: python3 -I closeout_cut.py <g070 dir> <new guard.py> <detail.json> <index in own/changed> [--show]
Cuts whole lines from the end, then from the start, while the verdict stays `ask`. Runs nothing. It shows which
part of a long call a rule answers for: on 2026-11-18 a call that opens with a here-document for `python3`
asked because of a real command behind the here-document, not because of the words in it. The output holds
the text of a real command: local only.
"""
import json
import os
import sys
import tempfile


def main(argv):
    kit, new_path, detail, index = argv[0], argv[1], argv[2], int(argv[3])
    sys.path.insert(0, kit)
    import replay
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["KZ_TELEMETRY_DIR"] = scratch
        new = replay.load(new_path, "guard_replay_new")
        with open(detail, encoding="utf-8") as handle:
            cell = json.load(handle)["boundaries"]["own"]["changed"][index]
        command = json.loads('"' + cell["call"] + '"')

        def asks(text):
            got = replay.verdicts(new, ["git-guard"], "Bash", {"command": text}, "/nonexistent-scratch", "feat/x",
                                  "own")
            return got["git-guard"] == "ask"

        lines = command.split("\n")
        print(f"lines {len(lines)} | asks as recorded: {asks(command)}")
        if "--show" in argv:
            for number, line in enumerate(lines, 1):
                print(f"{number:3} {line[:230]}")
        end = len(lines)
        while end > 1 and asks("\n".join(lines[:end - 1])):
            end -= 1
        start = 0
        while start < end - 1 and asks("\n".join(lines[start + 1:end])):
            start += 1
        print(f"smallest run of lines that still asks: {start + 1} to {end}")
        for number in range(start, end):
            print(f"{number + 1:3} {lines[number][:300]}")
        kept = lines[start:end]
        changed = True
        while changed:
            changed = False
            for at in range(len(kept)):
                trial = kept[:at] + kept[at + 1:]
                if trial and asks("\n".join(trial)):
                    kept = trial
                    changed = True
                    break
        print(f"after dropping every line the ask does not need: {len(kept)} lines")
        for line in kept:
            print("    " + line[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
