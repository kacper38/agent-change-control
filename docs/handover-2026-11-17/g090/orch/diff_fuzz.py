"""Look for a line that tells a mutated guard from the head: every sequence of up to N fragments of a small
shell grammar around a report that names a secret file, judged by secret-shell in both guards. A difference is a
candidate row; none over the whole space is evidence that the planted break changes no verdict on such lines.
Nothing is run: every line is a string handed to the rule function.

usage: python3 -I diff_fuzz.py <head guard.py> <mutant guard.py> [--max 5] [--show 12] [--valid-only]

With --valid-only a line counts only when `bash -n` and `zsh -n` (syntax check, nothing executed) accept it in
at least one of the two shells; the check reads the line from standard input and runs no command of it.
"""
import importlib.util
import itertools
import subprocess
import sys

FRAGMENTS = ["{ ", "} ", "if true; then ", "fi ", "while true; do ", "for i in 1; do ", "done ", "time ", "! ",
             "function f ", "coproc ", "ls .env", "echo .env", "true", "; ", " | xargs cat", " && ", "\n",
             "f", "cat \"$(f)\""]


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_fuzz_{n}", path)
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


def parses(line):
    """True when bash or zsh accepts the line's syntax (-n: read, do not execute)."""
    for shell in (["bash", "-n"], ["zsh", "-n"]):
        try:
            done = subprocess.run(shell, input=line, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):  # no such shell here, or it hangs: not counted as accepted
            continue
        if done.returncode == 0:
            return True
    return False


def main(argv):
    files, top, show, valid_only = [], 5, 12, False
    it = iter(argv)
    for a in it:
        if a == "--max":
            top = int(next(it))
        elif a == "--show":
            show = int(next(it))
        elif a == "--valid-only":
            valid_only = True
        else:
            files.append(a)
    head, mutant = load(files[0], 0), load(files[1], 1)
    lines = differ = shown = valid_differ = 0
    seen = set()
    for n in range(1, top + 1):
        for combo in itertools.product(FRAGMENTS, repeat=n):
            if not any(".env" in f for f in combo):
                continue
            line = "".join(combo).strip(" ")
            if line in seen:
                continue
            seen.add(line)
            lines += 1
            a, b = verdict(head, line), verdict(mutant, line)
            if a == b:
                continue
            differ += 1
            ok = parses(line) if (valid_only or shown < show) else None
            if ok:
                valid_differ += 1
            if (ok or not valid_only) and shown < show:
                shown += 1
                print(f"  head {a:6} | mutant {b:6} | a shell accepts it: {ok} | {line!r}")
    print(f"{files[1].rsplit('/', 1)[-1]} | lines {lines} | verdicts that differ {differ}"
          + (f" | of them accepted by bash or zsh {valid_differ}" if valid_only else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
