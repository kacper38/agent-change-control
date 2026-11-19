"""Show, for every row of a rows file, what each guard answers and whether a shell prints a stand-in file,
without a terminal and under a pseudo-terminal (git starts a pager only when its standard output is one).

usage: python3 -I pty_probe.py <rows file> <scratch folder> <guard.py> [<guard.py> ...]

A row is `id | branch[@client] | rule | expected | command`; a command that starts with a double quote is a JSON
string. Every command is judged by rule_secret_shell of every guard, as a string (never run by the guard). Then
`.env` in it is replaced by `secret.txt` and it is run four times, each in a fresh folder under the scratch
folder that holds a new git repository with `secret.txt` (one marker line) added to its index: by `zsh -f -c`
and by `bash --noprofile --norc -c`, once with pipes as standard output and error and once with a
pseudo-terminal. Standard input is closed; git reads no user or system configuration; a run is cut after 8
seconds (a pager that waits for a key). Printed per row: the id, the expectation, one letter per guard (s silent,
a ask, d deny), `pipe:` and `pty:` with `Z` when zsh showed the marker and `B` when bash did (`t` for a run that
was cut), and the command.
"""
import importlib.util
import json
import os
import pty
import select
import signal
import subprocess
import sys
import time

MARKER = "MARKER-7f3a"
SHELLS = (("Z", ["zsh", "-f", "-c"]), ("B", ["bash", "--noprofile", "--norc", "-c"]))
LIMIT = 8.0


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_rows_{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verdict(g, command):
    if hasattr(g, "_nc_cached"):
        g._nc_cached.cache_clear()
    ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                  "cwd": "/nonexistent-scratch"})
    try:
        got = g.rule_secret_shell(ev, dict(g.DEFAULTS))
    except Exception as exc:  # a crash is a finding of its own
        return "!" + type(exc).__name__
    return (got or ("silent",))[0][0]


def clean_env(home):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k not in ("PAGER", "LESS", "LV", "CLAUDECODE")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", TERM="xterm", HOME=home)
    return env


def fresh_repo(folder, env):
    os.makedirs(folder, exist_ok=False)
    with open(os.path.join(folder, "secret.txt"), "w", encoding="utf-8") as fh:
        fh.write(MARKER + "\n")
    subprocess.run(["git", "init", "-q", folder], env=env, check=True, capture_output=True)
    subprocess.run(["git", "-C", folder, "add", "secret.txt"], env=env, check=True, capture_output=True)
    with open(os.path.join(folder, ".git", "info", "exclude"), "a", encoding="utf-8") as fh:
        fh.write("secret.txt\n")  # for `check-ignore --no-index`: in the index and ignored


def run_pipe(argv, cwd, env):
    try:
        res = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=LIMIT,
                             start_new_session=True)
    except subprocess.TimeoutExpired as exc:
        return (exc.stdout or b"") + (exc.stderr or b""), True
    return res.stdout + res.stderr, False


def run_pty(argv, cwd, env):
    master, slave = pty.openpty()
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave,
                            start_new_session=True)
    os.close(slave)
    chunks = []
    deadline = time.monotonic() + LIMIT
    cut = False
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            cut = True
            break
        ready, _, _ = select.select([master], [], [], min(left, 0.2))
        if not ready:
            continue
        try:
            data = os.read(master, 65536)
        except OSError:  # the last writer closed the terminal
            break
        if not data:
            break
        chunks.append(data)
    if cut:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait()
    os.close(master)
    return b"".join(chunks), cut


def main(argv):
    rows_file, scratch, guards = argv[0], os.path.abspath(argv[1]), [load(p, n) for n, p in enumerate(argv[2:])]
    os.makedirs(scratch, exist_ok=True)
    env = clean_env(scratch)
    with open(rows_file, encoding="utf-8") as fh:
        lines = [x.rstrip("\n") for x in fh if x.strip() and not x.lstrip().startswith("#")]
    for n, line in enumerate(lines):
        rid, _branch, _rule, expected, command = [p.strip() for p in line.split(" | ", 4)]
        if command.startswith('"'):
            command = json.loads(command)
        answers = "".join(verdict(g, command)[0] for g in guards)
        run = command.replace(".env", "secret.txt")
        shown = {}
        for mode, runner in (("pipe", run_pipe), ("pty", run_pty)):
            letters = ""
            for letter, shell in SHELLS:
                folder = os.path.join(scratch, f"r{n:03d}-{mode}-{letter}")
                fresh_repo(folder, env)
                out, cut = runner(shell + [run], folder, env)
                letters += letter if MARKER.encode() in out else ("t" if cut else "-")
            shown[mode] = letters
        print(f"{rid:4} {expected:6} {answers} pipe:{shown['pipe']} pty:{shown['pty']} | {command}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(sys.argv[1:])
