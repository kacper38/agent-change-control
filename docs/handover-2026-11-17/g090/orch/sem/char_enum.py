"""Does one character, glued to a word of a line's structure, make the quiet-report check read the line otherwise
than a shell does?

usage: python3 -u -I char_enum.py <scratch folder> <guard.py> [--show K]

For every character from U+0001 to U+007F and a few above, lines are built from fixed templates in which the
character stands beside a brace, a separator or the report (a report that names `.env`, `true`, `:` and
`xargs cat` are the only commands). Each line is judged by rule_secret_shell of the guard, as a string. Only a
line the guard is silent on is run: with `.env` replaced by `secret.txt`, a stand-in this script writes into the
scratch folder with one marker line, by `zsh -f -c` and `bash --noprofile --norc -c`, the scratch folder as
working directory, standard input closed. A silent line on which a shell prints the marker is a HOLE.
"""
import importlib.util
import json
import os
import subprocess
import sys

MARKER = "MARKER-7f3a"
SHELLS = (("zsh", ["zsh", "-f", "-c"]), ("bash", ["bash", "--noprofile", "--norc", "-c"]))
TEMPLATES = [
    "{ ls .env; }@; {@ true; } | xargs cat",
    "{ ls .env; @}; {@ true; } | xargs cat",
    "{ ls .env; }@; @{ true; } | xargs cat",
    "{ ls .env; @}; @{ true; } | xargs cat",
    "{ ls .env@} | xargs cat",
    "{ ls .env;@} | xargs cat",
    "{@ls .env; } | xargs cat",
    "ls .env@| xargs cat",
    "ls .env |@xargs cat",
    "ls .env@|@xargs cat",
    "ls .env @ | xargs cat",
    "ls .env; true@| xargs cat",
    "{ ls .env; }@| xargs cat",
    "{ ls .env; } @ | xargs cat",
    "if true; then ls .env; fi@; if@ true; then true; fi | xargs cat",
    "{ ls .env; }@ ; { @ true; } | xargs cat",
    "{ echo .env; } @>/dev/null; { true; } | xargs cat",
    "{ echo .env@; } | xargs cat",
    "{ echo .env @; } | xargs cat",
    "{ echo .env; : @} | xargs cat",
    "{ echo .env; : @ } | xargs cat",
    "echo .env @\n| xargs cat",
    "echo .env |@\nxargs cat",
    "echo .env@\n{ true; } | xargs cat",
    "{ echo .env@\n} | xargs cat",
]
CHARS = [chr(n) for n in range(1, 128)] + ["\u0085", " ", " ", "　", "﻿"]


def load(path):
    return load_as(path, "guard_char_enum")


def load_as(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
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


def main(argv):
    scratch, guard = argv[0], load(argv[1])
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 20
    # --base <guard.py>: a line this older guard is silent on as well is no hole of the quiet check (the name is
    # not seen at all, as in `ls .env*`); such lines are counted apart
    base = load_as(argv[argv.index("--base") + 1], "guard_char_base") if "--base" in argv else None
    older = 0
    os.makedirs(scratch, exist_ok=True)
    with open(os.path.join(scratch, "secret.txt"), "w", encoding="utf-8") as fh:
        fh.write(MARKER + "\n")
    judged = silent = crashes = 0
    holes = []
    for template in TEMPLATES:
        for c in CHARS:
            line = template.replace("@", c)
            judged += 1
            got = verdict(guard, line)
            if got.startswith("CRASH"):
                crashes += 1
                continue
            if got != "silent":
                continue
            silent += 1
            if base is not None and verdict(base, line) == "silent":
                older += 1
                continue
            run = line.replace(".env", "secret.txt")
            printed = []
            for name, argv_shell in SHELLS:
                try:
                    res = subprocess.run(argv_shell + [run], cwd=scratch, stdin=subprocess.DEVNULL,
                                         capture_output=True, timeout=10)
                    if MARKER.encode() in res.stdout + res.stderr:
                        printed.append(name)
                except subprocess.TimeoutExpired:
                    printed.append(name + ":timeout")
            if printed:
                holes.append((line, printed))
    print(f"lines judged {judged} | silent {silent} | of these silent at the base too {older} | HOLES {len(holes)}"
          f" | crashes {crashes}")
    by_char = {}
    for line, printed in holes:
        for c in set(line) - set("".join(TEMPLATES)):
            by_char.setdefault(f"U+{ord(c):04X}", 0)
            by_char[f"U+{ord(c):04X}"] += 1
    if by_char:
        print("holes by character: " + ", ".join(f"{k} {v}" for k, v in sorted(by_char.items())))
    for line, printed in holes[:show]:
        print(f"   {'+'.join(printed):9} | {json.dumps(line)}")
    return 1 if holes or crashes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
