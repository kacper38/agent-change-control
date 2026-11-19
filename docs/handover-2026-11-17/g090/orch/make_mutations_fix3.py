"""Write the mutation list for the review fixes and the fourth fix round of guard 0.9.0 (groups B and C): one
break per code path these two rounds added or rewrote, among them new forms of the breaks of the second round's
list whose text has moved (g05, g45, g46).

usage: python3 -I make_mutations_fix3.py <guard.py of the head> <out.json>

Each entry replaces one exact text that must stand in the guard once; the script checks that and prints the
ones that do not. The list is data for orch/mutate.py, which applies each in a scratch copy and runs the tests.
"""
import json
import sys

M = []


def add(ident, what, old, new):
    M.append({"id": ident, "what": what, "old": old, "new": new})


# --- review fixes, topic 1: the list for the marks of an unread pipe
add("h01", "an unread pipe inside a nested script leaves its mark in a list nobody reads (was g45)",
    "            _nc_read(script, depth + 1, out, seen, local, inputs, bodies, envs, script_env, unread=unread)",
    "            _nc_read(script, depth + 1, out, seen, local, inputs, bodies, envs, script_env, unread=[])")
add("h02", "a pipe with a group or compound on one side and a shell on the other leaves no mark",
    "    if cmds is not None and _nc_compound_pipe(rows, seps, fed_bars):\n        unread.append(True)",
    "    if cmds is not None and _nc_compound_pipe(rows, seps, fed_bars):\n        pass")
add("h03", "a shell behind a plain pipe whose script is not on the line leaves no mark",
    "    if _nc_pipe_shell(piped):\n        unread.append(True)",
    "    if _nc_pipe_shell(piped):\n        pass")
# --- review fixes, topic 2: secret-shell learns from the reader pass that the read went through
add("h04", "the reader pass leaves no mark that the read went through",
    "        if read is not None:\n            read.append(True)",
    "        if read is not None:\n            pass")
add("h05", "secret-shell adds the input redirections only when the pass answers nothing (was g46)",
    "    if read:\n        reads.extend(",
    "    if failed is None:\n        reads.extend(")
add("h06", "secret-shell hands no list to the reader pass, so it never learns that the read went through",
    '    failed = reader_pass(ev.command, judge, "secret-shell", read=read)',
    '    failed = reader_pass(ev.command, judge, "secret-shell")')
add("h07", "the mark is set before the line is read, so a line the reader could not read counts as read",
    "        commands = nested_commands(text, local)\n        if read is not None:\n            read.append(True)",
    "        if read is not None:\n            read.append(True)\n        commands = nested_commands(text, local)")
# --- fourth fix round: a key per construct
add("h08", "constructs opened by one command share the key of that command again",
    "                stack.append((opened, _GROUP_CLOSER[t]))",
    "                stack.append((k, _GROUP_CLOSER[t]))")
add("h09", "every construct of a line shares one key",
    "                opened += 1\n",
    "                opened += 0\n")
add("h10", "a construct that closes never counts as handed on, whatever stands behind its closer (was g05)",
    '            handed_on[stack.pop()[0]] = not _plain_sep(cmds[k + 1][0] if k + 1 < len(cmds) else "")',
    "            handed_on[stack.pop()[0]] = False")
add("h11", "a construct that closes always counts as handed on",
    '            handed_on[stack.pop()[0]] = not _plain_sep(cmds[k + 1][0] if k + 1 < len(cmds) else "")',
    "            handed_on[stack.pop()[0]] = True")


def main(argv):
    guard, out = argv[0], argv[1]
    with open(guard, encoding="utf-8") as handle:
        text = handle.read()
    bad = 0
    for m in M:
        count = text.count(m["old"])
        if count != 1:
            bad += 1
            print(f"old text stands {count} times: {m['id']} {m['what']}")
        if m["old"] == m["new"]:
            bad += 1
            print(f"old and new are the same text: {m['id']}")
        try:
            compile(text.replace(m["old"], m["new"]), "guard-mutant", "exec")
        except SyntaxError as exc:
            bad += 1
            print(f"the changed text does not compile: {m['id']} ({exc})")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(M, handle, indent=1)
    print(f"mutations {len(M)} | not applicable {bad} | written {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
