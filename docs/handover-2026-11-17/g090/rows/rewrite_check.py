#!/usr/bin/env python3
"""One guard, one command written two ways: the second way must not be judged weaker than the first.

usage: python3 -u -I rewrite_check.py <expect.py> <rewrite_readers.py> <guard.py> <out.json> <file> [<file> ...]
       (list what it wrote with: python3 -I rewrite_list.py <out.json> [--kind K] [--rule R] [--max N])

A file is a rows file or a list of commands, as rewrite_readers.py reads them. Every command that is one line is
judged as written and in each rewriting below, in three contexts (feat/x own, main own, feat/x client). The
rewritings keep what the command does:
  pre     a harmless first line:            true<NL>CMD
  post    a harmless last line:             CMD<NL>true
  and     behind a list operator:           true && CMD
  or      in front of a list operator:      CMD || true
  group   in a brace group:                 { CMD; }
  sub     in a subshell:                    ( CMD )
  if      in a compound:                    if true; then CMD; fi
and, for a command without a backtick, `#`, backslash or substitution, at the operators outside quotes:
  nlpipe  a line break behind each pipe:    A |<NL>B
  nland   a line break behind && and ||:    A &&<NL>B
  nlsemi  a line break for each `; `:       A<NL>B            (no `;;`)
  and around the last pipe `L | R`, when R is one simple command:
  pipesub L | (R)    pipebrace L | { R; }    errpipe L 2>/dev/null | R    duppipe L 2>&1 | R    ampipe L |& R
  and, when L is one simple command too:
  subpipe (L) | R    bracepipe { L; } | R    suberrpipe (L) 2>/dev/null | R    subnlpipe (L) |<NL>R
A cell is weaker when a rule that denies the command as written asks or is silent for the rewriting, or one
that asks is silent. Commands with a here-document or a line break of their own are left out; so are the
wrappings for a command that ends in `&` or a comment.
Prints the count of weaker cells per rewriting and rule, and writes every weaker cell to out.json. Commands
are strings handed to rule functions; nothing runs.
"""
import collections
import importlib.util
import json
import sys

RANK = {"silent": 0, "ask": 1, "deny": 2}
CONTEXTS = [("feat/x", "own"), ("main", "own"), ("feat/x", "client")]
WRAPPERS = False  # --wrappers as the first argument: only the wrapper rewritings are judged


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wrapper_rewritings(cmd):
    """For one simple command without a redirection: a tool that runs the command after it, an assignment in
    front, a redirection of its error output, a closing semicolon, spaces, a carriage return, a tab."""
    out = collections.OrderedDict()
    if any(c in cmd for c in ";|&(){}<>`#\\") or cmd.lstrip().startswith(("if ", "for ", "while ", "until ",
                                                                           "case ", "[[", "[ ", "test ")):
        return out
    out["sudo"] = "sudo " + cmd
    out["env"] = "env " + cmd
    out["command"] = "command " + cmd
    out["nohup"] = "nohup " + cmd
    out["timeout"] = "timeout 5 " + cmd
    out["assign"] = "FOO=1 " + cmd
    out["err"] = cmd + " 2>/dev/null"
    out["dup"] = cmd + " 2>&1"
    out["semi"] = cmd + ";"
    out["space"] = "  " + cmd + "  "
    out["crlf"] = cmd + "\r\n"
    out["tab"] = cmd.replace(" ", "\t", 1)
    return out


def rewritings(cmd):
    out = collections.OrderedDict()
    if "\n" in cmd or "<<" in cmd:
        return out
    if WRAPPERS:
        return wrapper_rewritings(cmd)
    out["pre"] = "true\n" + cmd
    out["post"] = cmd + "\ntrue"
    tail = cmd.rstrip()
    if not tail.endswith("&") and "#" not in cmd and not tail.endswith("\\"):
        out["and"] = "true && " + cmd
        out["or"] = cmd + " || true"
        out["group"] = "{ " + cmd + "; }"
        out["sub"] = "( " + cmd + " )"
        out["if"] = "if true; then " + cmd + "; fi"
    if any(c in cmd for c in "`#\\") or "$(" in cmd or "<(" in cmd or ">(" in cmd:
        return out  # the scan below knows quotes only
    bars = top_level(cmd, " | ")
    if bars:
        out["nlpipe"] = replace_at(cmd, bars, " | ", " |\n")
        left, right = cmd[: bars[-1]], cmd[bars[-1] + 3 :]
        if not any(c in right for c in ";&|(){}<>") and right.strip():
            out["pipesub"] = f"{left} | ({right})"
            out["pipebrace"] = f"{left} | {{ {right}; }}"
            out["errpipe"] = f"{left} 2>/dev/null | {right}"
            out["duppipe"] = f"{left} 2>&1 | {right}"
            out["ampipe"] = f"{left} |& {right}"
            if not any(c in left for c in ";&|(){}") and left.strip():
                out["subpipe"] = f"({left}) | {right}"
                out["bracepipe"] = f"{{ {left}; }} | {right}"
                out["suberrpipe"] = f"({left}) 2>/dev/null | {right}"
                out["subnlpipe"] = f"({left}) |\n{right}"
    ands, ors = top_level(cmd, " && "), top_level(cmd, " || ")
    if ands or ors:
        text = replace_at(cmd, ands, " && ", " &&\n")
        out["nland"] = replace_at(text, top_level(text, " || "), " || ", " ||\n")
    semis = top_level(cmd, "; ")
    if semis and ";;" not in cmd:
        out["nlsemi"] = replace_at(cmd, semis, "; ", "\n")
    return out


def top_level(cmd, needle):
    """The places of `needle` outside single and double quotes."""
    out = []
    quote = None
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif cmd.startswith(needle, i):
            out.append(i)
            i += len(needle)
            continue
        i += 1
    return out


def replace_at(cmd, places, needle, new):
    """`cmd` with `needle` replaced by `new` at each of `places` (ascending)."""
    parts = []
    last = 0
    for at in places:
        parts.append(cmd[last:at])
        parts.append(new)
        last = at + len(needle)
    parts.append(cmd[last:])
    return "".join(parts)


def main(argv):
    global WRAPPERS
    if argv[1:2] == ["--wrappers"]:
        WRAPPERS = True
        argv = argv[:1] + argv[2:]
    expect = load(argv[1], "expect_helper")
    readers = load(argv[2], "weaker_cells_helper")
    guard = expect.load(argv[3])
    out_path = argv[4]
    commands = collections.OrderedDict()
    for path in argv[5:]:
        for command, _row in readers.lines_of(path):
            commands.setdefault(command, None)
    weaker = []
    counts = collections.Counter()
    judged = collections.Counter()
    crashes = 0
    for n, command in enumerate(commands, 1):
        forms = rewritings(command)
        if not forms:
            continue
        for branch, boundary in CONTEXTS:
            base = expect.answer(guard, branch, boundary, "shell", command)
            for kind, text in forms.items():
                got = expect.answer(guard, branch, boundary, "shell", text)
                judged[kind] += 1
                for rule, verdict in base.items():
                    new = got[rule]
                    if new.startswith("CRASH"):
                        crashes += 1
                        print(f"CRASH {kind} [{branch}@{boundary}] {rule}: {new} | {json.dumps(text)[:160]}")
                        continue
                    if verdict.startswith("CRASH") or RANK.get(new, 3) >= RANK.get(verdict, 3):
                        continue
                    counts[(kind, rule)] += 1
                    weaker.append({"kind": kind, "branch": branch, "boundary": boundary, "rule": rule,
                                   "as_written": verdict, "rewritten": new, "command": command, "text": text})
        if n % 500 == 0:
            print(f"... {n} of {len(commands)} commands, weaker cells so far {len(weaker)}")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(weaker, fh, indent=0)
    print(f"guard {guard.VERSION} | commands {len(commands)} | rewritings judged: "
          + ", ".join(f"{k} {v}" for k, v in judged.items()))
    print(f"weaker cells {len(weaker)} | distinct commands {len({w['command'] for w in weaker})} | crashes {crashes}")
    for (kind, rule), count in sorted(counts.items()):
        print(f"  {kind:7} {rule:17} {count}")
    return 1 if weaker or crashes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
