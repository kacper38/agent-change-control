"""An oracle for the quiet-report check of secret-shell: where is a guard silent on a line that, run by a real
shell, prints the content of the file the line names?

usage: python3 -u -I quiet_oracle.py <scratch folder> <guard.py> [<guard.py> ...] [--samples N] [--seed S]
                                     [--show K] [--out FILE]

Lines are drawn at random from a small grammar: reports that name `.env` (`ls`, `echo`, `test`, `[[`, `printf`),
commands that read names from their input or from `$_` and print the files (`xargs cat`, `cat $_`, `read f` with
`cat "$f"`), neutral commands, the separators, groups (also the zsh form without `;` in front of the `}`),
subshells, `if`, `while`, `for`, `!` and `time`, and redirections of the error stream. No line writes a file,
and no command other than these stands in one.

Each line is judged by `rule_secret_shell` of every guard, as a string. Only a line some guard is silent on is
then run: with `.env` replaced by `secret.txt`, a stand-in this script writes into the scratch folder with one
marker line, by `zsh -f -c` and by `bash --noprofile --norc -c`, with the scratch folder as the working directory.
A line on which a guard is silent while a shell prints the marker is a HOLE of that guard.
"""
import importlib.util
import json
import os
import random
import subprocess
import sys

MARKER = "MARKER-7f3a"
SHELLS = (("zsh", ["zsh", "-f", "-c"]), ("bash", ["bash", "--noprofile", "--norc", "-c"]))
REPORTS = ["ls .env", "echo .env", "test -f .env", "[[ -f .env ]]", "printf '%s\\n' .env"]
REPORT_TAILS = ["", "", "", " 2>/dev/null", " 2>&1", " >&2"]
SINKS = ["xargs cat", "xargs -n 1 cat", "cat $_", 'cat "$_"', "read f", 'cat "$f"']
NEUTRAL = ["true", ":", "false", "echo ok"]
SEPS = ["; ", "; ", " && ", " || ", " | ", " | ", " |& ", "\n", " & "]
CLOSE_TAILS = ["", "", "", " 2>/dev/null", " 2>&1"]


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_oracle_{n}", path)
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


def item(rng, depth):
    roll = rng.random()
    if depth <= 0 or roll < 0.42:
        kind = rng.random()
        if kind < 0.45:
            return rng.choice(REPORTS) + rng.choice(REPORT_TAILS)
        if kind < 0.8:
            return rng.choice(SINKS)
        return rng.choice(NEUTRAL)
    inner = seq(rng, depth - 1)
    tail = rng.choice(CLOSE_TAILS)
    pick = rng.randrange(10)
    if pick == 0:
        return "{ " + inner + "; }" + tail
    if pick == 1:
        return "{ " + inner + " }" + tail  # zsh closes the group at a `}` without `;`
    if pick == 2:
        return "( " + inner + " )" + tail
    if pick == 3:
        return "if " + seq(rng, depth - 1) + "; then " + inner + "; fi" + tail
    if pick == 4:
        return "if " + inner + "; then " + seq(rng, depth - 1) + "; else " + seq(rng, depth - 1) + "; fi" + tail
    if pick == 5:
        return "while " + seq(rng, depth - 1) + "; do " + inner + "; break; done" + tail
    if pick == 6:
        return "for x in a; do " + inner + "; done" + tail
    if pick == 7:
        return "! " + item(rng, depth - 1)
    if pick == 8:
        return "time " + item(rng, depth - 1)
    return "{ " + inner + "; " + rng.choice(NEUTRAL) + " }" + tail  # a zsh group that ends in a neutral command


def seq(rng, depth):
    parts = [item(rng, depth)]
    for _ in range(rng.choice((0, 0, 1, 1, 2))):
        parts.append(rng.choice(SEPS))
        parts.append(item(rng, depth))
    return "".join(parts)


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
    files, samples, seed, show, out = [], 20000, 1, 15, None
    it = iter(argv)
    for a in it:
        if a == "--samples":
            samples = int(next(it))
        elif a == "--seed":
            seed = int(next(it))
        elif a == "--show":
            show = int(next(it))
        elif a == "--out":
            out = next(it)
        else:
            files.append(a)
    folder, guard_files = files[0], files[1:]
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "secret.txt"), "w", encoding="utf-8") as fh:
        fh.write(MARKER + "\n")
    guards = [(os.path.basename(p), load(p, n)) for n, p in enumerate(guard_files)]
    rng = random.Random(seed)
    seen = set()
    judged = ran = 0
    silent = {name: 0 for name, _ in guards}
    holes = {name: [] for name, _ in guards}
    crashes = {name: 0 for name, _ in guards}
    content_lines = 0
    while judged < samples:
        line = seq(rng, 3)
        if ".env" not in line or not any(s in line for s in ("xargs", "$_", '"$f"')) or line in seen:
            continue
        seen.add(line)
        judged += 1
        got = {name: verdict(g, line) for name, g in guards}
        for name, v in got.items():
            if v.startswith("CRASH"):
                crashes[name] += 1
        quiet = [name for name, v in got.items() if v == "silent"]
        if not quiet:
            continue
        for name in quiet:
            silent[name] += 1
        ran += 1
        shells = {name: run(argv_, line, folder) for name, argv_ in SHELLS}
        if "CONTENT" in shells.values():
            content_lines += 1
            for name in quiet:
                holes[name].append((line, shells))
    print(f"lines judged {judged} | run by the shells (some guard silent) {ran} | of them a shell prints the content {content_lines}")
    for name, _ in guards:
        found = sorted(holes[name], key=lambda h: (len(h[0]), h[0]))
        print(f"== {name} | silent {silent[name]} | HOLES (silent, and a shell prints the content) {len(found)} | crashes {crashes[name]}")
        for line, shells in found[:show]:
            print(f"   zsh {shells['zsh']:7} bash {shells['bash']:7} | {json.dumps(line)}")
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({name: [{"line": line, "shells": shells} for line, shells in holes[name]] for name, _ in guards},
                      fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
