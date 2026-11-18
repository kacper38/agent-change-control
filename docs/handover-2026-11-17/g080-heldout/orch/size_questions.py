#!/usr/bin/env python3
"""Size open questions 5 and 6 on the real calls: how often `az` and a pull request merge occur in the replayed
transcripts, and what today's guard answers for them.

usage: python3 -I size_questions.py <g070 dir> <guard.py> <days>
Reads transcripts only, runs nothing. Prints the sub-command words of `az` and `gh` calls (no arguments, no
values) with counts.
"""
import collections
import os
import sys
import tempfile

AZ_READS = ("list", "show", "exists", "check", "version", "help", "wait", "find", "query", "download", "export",
            "diff", "validate", "what-if", "browse", "logs", "tail", "history")
LOCAL = (("login",), ("logout",), ("account", "set"), ("config", "set"), ("bicep",), ("aks", "get-credentials"),
         ("extension",), ("upgrade",), ("configure",), ("interactive",), ("feedback",), ("rest",))


def plain_words(tokens):
    """The words behind the tool name up to the first option."""
    out = []
    for token in tokens:
        if token.startswith("-"):
            break
        out.append(token)
    return out


def main(argv):
    kit, guard_path, days = argv[0], argv[1], int(argv[2])
    sys.path.insert(0, kit)
    import replay
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["KZ_TELEMETRY_DIR"] = scratch
        guard = replay.load(guard_path, "guard_replay_new")
        root = os.path.join(os.path.expanduser("~"), ".claude", "projects")
        distinct, per_tool, _nb = replay.collect(replay.transcripts(root, days))
        az = collections.Counter()
        az_today = collections.Counter()
        merges = collections.Counter()
        merge_today = collections.Counter()
        unread = 0
        for count, tool, tool_input, cwd, branch in distinct.values():
            if tool != "Bash":
                continue
            command = str(tool_input.get("command", ""))
            if " az " not in " " + command.replace("\n", " ") + " " and "pr merge" not in command \
                    and "/merge" not in command:
                continue
            try:
                segs = guard.segments(command)
            except Exception:  # a command the first pass cannot split is counted, not judged
                unread += count
                continue
            where = cwd if cwd and os.path.isdir(cwd) else "/nonexistent-scratch"
            got = None
            for seg in segs:
                names = [os.path.basename(t) for t in seg]
                if "az" in names:
                    words = plain_words(seg[names.index("az") + 1:])
                    if not words:
                        continue
                    verb = words[-1]
                    kind = "read" if verb.startswith(("get-", "list-", "show-")) or verb in AZ_READS else "other"
                    if any(tuple(words[:len(p)]) == p for p in LOCAL):
                        kind = "local"
                    az[(kind, " ".join(words[:3]))] += count
                    if got is None:
                        got = replay.verdicts(guard, ["deploy-ask", "tracker-guard"], tool, tool_input, where,
                                              branch, "own")
                    az_today[(kind, got["deploy-ask"], got["tracker-guard"])] += count
                if "gh" in names:
                    rest = seg[names.index("gh") + 1:]
                    joined = " ".join(rest)
                    if "pr merge" in joined or ("api" in rest and "/merge" in joined):
                        form = "gh pr merge" if "pr merge" in joined else "gh api …/merge"
                        if "--admin" in rest:
                            form += " --admin"
                        if "--auto" in rest:
                            form += " --auto"
                        merges[form] += count
                        if got is None:
                            got = replay.verdicts(guard, ["deploy-ask", "tracker-guard"], tool, tool_input, where,
                                                  branch, "own")
                        merge_today[got["tracker-guard"]] += count
        print(f"Bash calls {per_tool['Bash']} | not split by the first pass: {unread}")
        print(f"\n== az: {sum(az.values())} calls")
        for kind in ("read", "local", "other"):
            rows = sorted(((n, w) for (k, w), n in az.items() if k == kind), reverse=True)
            print(f"{kind}: {sum(n for n, _w in rows)} calls, {len(rows)} sub-commands")
            for n, words in rows[:25]:
                print(f"   {n:4}  az {words}")
        print("today's verdict per kind (kind, deploy-ask, tracker-guard): "
              + ", ".join(f"{k}: {n}" for k, n in sorted(az_today.items())))
        print(f"\n== a merge of a pull request: {sum(merges.values())} calls")
        for form, n in sorted(merges.items()):
            print(f"   {n:4}  {form}")
        print("today's tracker-guard verdict: " + ", ".join(f"{k}: {n}" for k, n in sorted(merge_today.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
