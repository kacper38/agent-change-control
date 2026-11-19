"""An enumerating oracle for the quiet-report check of secret-shell: lines built from parts, each of which hands
the output of a report that names `.env` to a command that prints the files it is told (`xargs cat`), dressed with
words that could mislead a reading of the line. Where is a guard silent on a line whose content a real shell
prints?

usage: python3 -u -I quiet_enum.py <scratch folder> <guard.py> [<guard.py> ...] [--sample N] [--seed S]
                                   [--max-run N] [--show K] [--out FILE] [--count] [--shard K/N]

A line is  LEAD OUTER( OPEN PRE report POST CLOSE | xargs cat TRAIL )  where
  OPEN … CLOSE  is the construct around the report: a group (also closed the zsh way, without `;`), `if`, `while`,
                `until`, `for`, the same behind `time`, `repeat 1`, `!`, an `always` block, the short zsh forms;
  PRE, POST     stand inside the construct: nothing, a neutral command, or a word a reader could take for an
                opener: a quoted or escaped `{` or `if`, the same behind `&&` inside `[[ ]]`, inside `${…}` or
                `$[…]`, a group zsh closes without `;`, a quote the lexer reads otherwise than the shell;
  TRAIL         stands behind the reader: nothing, or what could pass for the closer of the construct;
  OUTER         wraps the line in one more construct.
A second, small family are reports that hand their words on by themselves (`printf -v`, `[[ =~ ]]`, `$_`).

Every line is judged by `rule_secret_shell` of each guard, as a string. Only lines some guard is silent on are run:
with `.env` replaced by `secret.txt`, a stand-in this script writes into the scratch folder with one marker line,
by `zsh -f -c` and by `bash --noprofile --norc -c`, the scratch folder as working directory. No line writes a
file; the only commands are ls, echo, test, true, `:`, break, cat, xargs cat, `[[ ]]` and words no shell finds.
A line on which a guard is silent while a shell prints the marker is a HOLE of that guard.
With --sample N the lines are N drawn at random (seed S) instead of all; --max-run caps the lines the shells run
per guard (the rest of the silent lines are counted as not run); --count prints the number of lines and stops.
"""
import importlib.util
import itertools
import json
import os
import random
import subprocess
import sys

MARKER = "MARKER-7f3a"
SHELLS = (("zsh", ["zsh", "-f", "-c"]), ("bash", ["bash", "--noprofile", "--norc", "-c"]))

REPORTS = ["ls .env", "echo .env"]
GROUPS = [
    ("", ""),
    ("{ ", "; }"), ("{ ", " }"), ("{ ", "; } 2>/dev/null"),
    ("if true; then ", "; fi"), ("if true; then ", "; else fi"), ("if false; then :; else ", "; fi"),
    ("while true; do ", "; break; done"), ("until false; do ", "; break; done"), ("for x in a; do ", "; done"),
    ("time { ", "; }"), ("repeat 1 { ", "; }"), ("! { ", "; }"), ("repeat 1 do ", "; done"),
    ("{ true; } always { ", "; }"), ("if [[ -n a ]] { ", "; }"), ("for x in a; { ", "; }"),
    ("if true; then { ", "; }; fi"), ("{ if true; then ", "; fi; }"), ("{ { ", "; }; }"), ("{ { ", "; } }"),
    ("{ { ", " } }"), ("time if true; then ", "; fi"),
    # closers behind closers, which bash takes
    ("if true; then ", "; if true; then true; fi fi"), ("{ ", "; { true; } }"),
    ("while true; do ", "; break; while false; do true; done done"),
]
FAKE_OPEN = ["'{'", '"{"', "\\{", "[[ a && { ]]", "[[ a || { ]]", "echo ${X:-a; { b}", "'if'", "[[ a && if ]]",
             ": $[ 1 | if ]", "'while'", "{ true }", "{ true; }", "if true; then true; else fi",
             ": $'\\''", ': "`: " ; { true ; : "`"', ': "${X:-" ; { true ; : "}"',
             # added for the final probe: an empty quoted part, a line break inside `[[ ]]`, a quoted substitution
             # with a word behind it, arithmetic
             "{''", "[[ a && {\n]]", ': "$(: " ; { true ; : ") x"', ': "$(( 1 " ; { true ; : " ))"',
             ': "$[ 1 " ; { true ; : " ]"',
             # `$'…'` inside a quoted substitution, where its escaped quote hides the `)` from a plain reading;
             # and a single-quoted string that only ends in `$`
             ': "$(: $\'a\\\' ) " ; { true ; : "\')"', ": 'a$' '{'",
             # sixth round: a carriage return glued to a brace (a blank for the lexer, a character for the shell)
             "{\r true", "\r{ true", "}\r; {\r true",
             # sixth round: `case` in a quoted substitution with no blank in front
             ': "$(:;case x in x) : " ; { true ; : " ;; esac)"']
PRE =["", "true; "] + [f + "; " for f in FAKE_OPEN[:8]] + ["{''; "]
POST = ["", "; true"] + ["; " + f for f in FAKE_OPEN]
FAKE_CLOSE = ["'}'", '"}"', "\\}", "[[ a && } ]]", "[[ a || } ]]", "echo ${X:-a; }", "'fi'", "[[ a && fi ]]",
              ": $[ 1 | fi ]", "'done'", "[[ a && done ]]", "{ true; }", "{ true }", "if true; then true; fi",
              "time if true; then true; fi", "repeat 1 if true; then true; fi", "time { true; }",
              "time while false; do true; done", ": \\'", "{ : \\' ; }", ': "`: " ; } ; : "`"',
              ': "${X:-" ; } ; : "}"',
              "''}", "[[ a && }\n]]", ': "$(: " ; } ; : ") y"', ': "$(( 1 " ; } ; : " ))"',
              ': "$[ 1 " ; } ; : " ]"',
              ': "$(: $\'a\\\' ) " ; } ; : "\')"', ": 'a$' '}'",
              "}\r", "\r}",
              ': "$(:;case x in x) : " ; } ; : " ;; esac)"', ': "$(:&&case x in x) : " ; } ; { : " ;; esac)"']
TRAIL =["", "; true"] + ["; " + f for f in FAKE_CLOSE]
OUTER = [("", ""), ("{ ", "; }"), ("{ ", " }"), ("time { ", "; }"), ("time { true; ", "; }"),
         ("repeat 1 { ", "; }"), ("if true; then ", "; fi"), ("{ true; } always { ", "; }")]
SELF = [  # reports that hand their words on by themselves, and what reads them
    "printf -v x %s .env; cat \"$x\"", "printf -vx %s .env; cat \"$x\"", "printf -v x '%s' .env && cat $x",
    "{ printf -v x %s .env; }; cat \"$x\"", "if printf -v x %s .env; then cat \"$x\"; fi",
    "[[ .env =~ .* ]]; cat $BASH_REMATCH $MATCH", "[[ .env =~ .* ]] && cat $BASH_REMATCH $MATCH",
    "if [[ .env =~ .* ]]; then cat $BASH_REMATCH $MATCH; fi", "[[ x.env =~ .env ]]; cat $BASH_REMATCH $MATCH",
    "ls .env; cat $_", "ls .env; cat \"${_}\"", "ls .env; cat \"${_:-x}\"", "echo .env; cat ${_%y}",
    "echo .env; cat ${_#y}", "test -f .env && cat \"${_:-x}\"", "{ ls .env; }; cat \"${_:-x}\"",
    "ls .env; cat ${_:+$_}", "echo .env; x=$_; cat \"$x\"", "ls .env; cat ${(U)_:l}",
    # sixth round: an option of printf that the shell makes; `$_` that quotes split; a report's name with a path
    "X=-v; printf $X x %s .env; cat $x", "printf ${X:--v} x %s .env; cat $x",
    "printf \"${X:--v}\" x %s .env; cat $x", "printf \"$(echo -v)\" x %s .env; cat $x",
    "printf \"`echo -v`\" x %s .env; cat $x", "printf {-v,x} %s .env; cat $x", "printf $E -v x %s .env; cat $x",
    "printf -${E}v x %s .env; cat $x", "printf \"-\"v x %s .env; cat $x", "printf \\-v x %s .env; cat $x",
    "shopt -s nullglob; printf nomatch* -v x %s .env; cat $x",
    "setopt nullglob; printf nomatch* -v x %s .env; cat $x",
    "setopt extendedglob nullglob; printf nomatch# -v x %s .env; cat $x",
    "ls .env; eval 'cat $'_", "ls .env; eval cat '$'_", "ls .env; eval \"cat \\$\"_", "ls .env; eval cat \\$''_",
    "echo .env; eval 'cat \"$'_'\"'", "test -f .env && eval 'cat $'_",
    "ln -s /bin/cat ./ls; ./ls .env", "mkdir -p script; ln -s /bin/cat script/test; script/test .env",
    "ln -s /bin/cat ./git; ./git status .env",
]


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_enum_{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verdict(g, command):
    g._nc_cached.cache_clear()
    ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                  "cwd": "/nonexistent-scratch"})
    try:
        got = g.rule_secret_shell(ev, dict(g.DEFAULTS))
    except Exception as exc:  # a crash is a finding of its own
        return f"CRASH:{type(exc).__name__}"
    return (got or ("silent",))[0]


def lines():
    for (o_open, o_close), (g_open, g_close), pre, report, post, trail in itertools.product(
            OUTER, GROUPS, PRE, REPORTS, POST, TRAIL):
        yield f"{o_open}{g_open}{pre}{report}{post}{g_close} | xargs cat{trail}{o_close}"
    yield from SELF


def run(argv, line, folder):
    try:
        r = subprocess.run(argv + [line.replace(".env", "secret.txt")], cwd=folder, capture_output=True, text=True,
                           timeout=5, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    if MARKER in r.stdout or MARKER in r.stderr:
        return "CONTENT"
    err = r.stderr.lower()
    return "SYNTAX" if ("parse error" in err or "syntax error" in err) else "no"


def main(argv):
    files, sample, seed, max_run, show, out, count_only = [], 0, 1, 20000, 20, None, False
    shard, shards = 0, 1
    it = iter(argv)
    for a in it:
        if a == "--shard":  # K/N: only every line whose number is K modulo N, so N runs side by side cover all
            shard, shards = (int(x) for x in next(it).split("/"))
        elif a == "--sample":
            sample = int(next(it))
        elif a == "--seed":
            seed = int(next(it))
        elif a == "--max-run":
            max_run = int(next(it))
        elif a == "--show":
            show = int(next(it))
        elif a == "--out":
            out = next(it)
        elif a == "--count":
            count_only = True
        else:
            files.append(a)
    total = len(OUTER) * len(GROUPS) * len(PRE) * len(REPORTS) * len(POST) * len(TRAIL) + len(SELF)
    print(f"lines in the product: {total}")
    if count_only:
        return 0
    folder, guard_files = files[0], files[1:]
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "secret.txt"), "w", encoding="utf-8") as fh:
        fh.write(MARKER + "\n")
    guards = [(os.path.basename(p), load(p, n)) for n, p in enumerate(guard_files)]
    pool = lines()
    if sample:
        every = list(pool)
        random.Random(seed).shuffle(every)
        pool = every[:sample] + SELF
    if shards > 1:
        pool = itertools.islice(pool, shard, None, shards)
    judged = 0
    silent = {name: 0 for name, _ in guards}
    ran = {name: 0 for name, _ in guards}
    holes = {name: [] for name, _ in guards}
    crashes = {name: 0 for name, _ in guards}
    shells_seen = {}
    for line in pool:
        judged += 1
        if judged % 100000 == 0:
            print(f"... {judged} lines judged", flush=True)
        for name, g in guards:
            v = verdict(g, line)
            if v.startswith("CRASH"):
                crashes[name] += 1
            if v != "silent":
                continue
            silent[name] += 1
            if line not in shells_seen:
                if ran[name] >= max_run:
                    continue
                shells_seen[line] = {sh: run(argv_, line, folder) for sh, argv_ in SHELLS}
            ran[name] += 1
            if "CONTENT" in shells_seen[line].values():
                holes[name].append((line, shells_seen[line]))
    print(f"lines judged {judged}")
    for name, _ in guards:
        found = sorted(holes[name], key=lambda h: (len(h[0]), h[0]))
        print(f"== {name} | silent {silent[name]} | run by the shells {ran[name]} | HOLES (silent, and a shell prints "
              f"the content) {len(found)} | crashes {crashes[name]}")
        for line, shells in found[:show]:
            print(f"   zsh {shells['zsh']:7} bash {shells['bash']:7} | {json.dumps(line)}")
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({name: [{"line": line, "shells": shells} for line, shells in holes[name]]
                       for name, _ in guards}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
