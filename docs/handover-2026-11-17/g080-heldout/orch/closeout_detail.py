#!/usr/bin/env python3
"""Detail behind the close-out replay: base rate per rule under both guards, and the reason of each changed cell.

usage: python3 -I closeout_detail.py <g070 dir> <old guard.py> <new guard.py> <days> <out.json>
Reads transcripts only, runs nothing. The JSON file holds the text of every changed call: it stays in a local
scratch folder, like the logs of replay.py. Written on the owner's machine on 2026-11-18 for the close-out of #50.
"""
import collections
import json
import os
import sys
import tempfile


def reason(guard, name, tool, tool_input, cwd, branch, boundary):
    """The full decision of one rule, set up as replay.verdicts sets it up."""
    cfg = dict(guard.DEFAULTS)
    cfg["host_install"] = "ask"
    cfg["boundary"] = boundary
    guard.current_branch = lambda _cwd, b=branch: b
    event = guard.Event({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                         "cwd": cwd, "session_id": "replay", "transcript_path": "replay"})
    decision = guard.RULES[name](event, cfg)
    return list(decision) if decision else ["silent", ""]


def main(argv):
    kit, old_path, new_path, days, out_path = argv[0], argv[1], argv[2], int(argv[3]), argv[4]
    sys.path.insert(0, kit)
    import replay
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["KZ_TELEMETRY_DIR"] = scratch
        old, new = replay.load(old_path, "guard_replay_old"), replay.load(new_path, "guard_replay_new")
        names = [n for n in new.RULES if n in old.RULES and n not in replay.STATEFUL]
        root = os.path.join(os.path.expanduser("~"), ".claude", "projects")
        paths = replay.transcripts(root, days)
        distinct, per_tool, _no_branch = replay.collect(paths)
        total = sum(per_tool.values())
        print(f"transcripts {len(paths)} | calls {total} | distinct {len(distinct)} | rules {len(names)}")
        result = {"transcripts": len(paths), "calls": total, "distinct": len(distinct), "rules": names,
                  "boundaries": {}}
        for boundary in ("own", "client"):
            tally = {side: collections.Counter() for side in ("old", "new")}
            cells = 0
            changed = []
            for count, tool, tool_input, cwd, branch in distinct.values():
                where = cwd if cwd and os.path.isdir(cwd) else "/nonexistent-scratch"
                before = replay.verdicts(old, names, tool, tool_input, where, branch, boundary)
                after = replay.verdicts(new, names, tool, tool_input, where, branch, boundary)
                for name in names:
                    cells += 1
                    a, b = before[name], after[name]
                    if a != "silent":
                        tally["old"][(name, a)] += count
                    if b != "silent":
                        tally["new"][(name, b)] += count
                    if a != b:
                        why_old = reason(old, name, tool, tool_input, where, branch, boundary)
                        why_new = reason(new, name, tool, tool_input, where, branch, boundary)
                        changed.append({"count": count, "rule": name, "old": a, "new": b, "tool": tool,
                                        "cwd_exists": where == cwd, "why_old": why_old[1], "why_new": why_new[1],
                                        "call": replay.head(tool, tool_input, 100000)})
            print(f"\n== boundary {boundary}: {cells} verdict cells compared, {len(changed)} changed")
            print("rule | verdict | occurrences at old | occurrences at new")
            keys = sorted(set(tally["old"]) | set(tally["new"]))
            for key in keys:
                print(f"{key[0]} | {key[1]} | {tally['old'][key]} | {tally['new'][key]}")
            print(f"non-silent occurrences: old {sum(tally['old'].values())} | new {sum(tally['new'].values())}")
            for cell in changed:
                print(f"-- {cell['rule']} {cell['old']}->{cell['new']} x{cell['count']} {cell['tool']} "
                      f"(cwd exists: {cell['cwd_exists']}, call length {len(cell['call'])})")
                print(f"   why now: {cell['why_new'][:420]}")
            result["boundaries"][boundary] = {
                "cells": cells,
                "tally_old": {f"{k[0]}|{k[1]}": v for k, v in tally["old"].items()},
                "tally_new": {f"{k[0]}|{k[1]}": v for k, v in tally["new"].items()},
                "changed": changed,
            }
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
