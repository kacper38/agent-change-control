"""Time each shell rule of a guard, called directly (no hook, no budget), on long commands built from units.

usage: python3 -I cost_rules.py <units.txt> <size> <branch> <boundary> <limit seconds> <guard.py> [only-unit ...]

units.txt: tab-separated name, prefix, unit, suffix; the command is prefix + unit repeated to the size + suffix.
The commands are data handed to the rule functions; nothing in them runs. A rule that runs past the limit is
stopped by an alarm and shown as `> limit`. Prints per unit: the total, and every rule slower than 0.3 s.
"""
import importlib.util
import signal
import sys
import time

RULES = ["delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
         "tracker-guard", "host-install"]


class TooLong(Exception):
    pass


def stop(_signum, _frame):
    raise TooLong()


def main(argv):
    units, size, branch, boundary, limit, guard = argv[0], int(argv[1]), argv[2], argv[3], int(argv[4]), argv[5]
    only = set(argv[6:])
    spec = importlib.util.spec_from_file_location("g", guard)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    g.current_branch = lambda cwd: branch
    signal.signal(signal.SIGALRM, stop)
    print(f"{guard.rsplit('/', 1)[-1]} | size {size} | branch {branch} | boundary {boundary} | limit {limit} s per rule")
    with open(units, encoding="utf-8") as handle:
        rows = [line.rstrip("\n").split("\t") for line in handle if line.strip()]
    for name, prefix, unit, suffix in rows:
        if only and name not in only:
            continue
        count = max(1, (size - len(prefix) - len(suffix)) // len(unit))
        command = prefix + unit * count + suffix
        cfg = dict(g.DEFAULTS)
        cfg["host_install"] = "ask"
        cfg["boundary"] = boundary
        ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                      "cwd": "/nonexistent-scratch"})
        slow, got, total = [], [], 0.0
        for rule in RULES:
            start = time.perf_counter()
            signal.alarm(limit)
            try:
                verdict = g.RULES[rule](ev, cfg)
            except TooLong:
                verdict = ("> limit",)
            except Exception as exc:  # a crash is a result of the check, shown by name
                verdict = ("CRASH " + type(exc).__name__,)
            finally:
                signal.alarm(0)
            took = time.perf_counter() - start
            total += took
            if took > 0.3:
                slow.append(f"{rule} {took:.1f}s")
            if verdict:
                got.append(f"{rule}={verdict[0]}")
        print(f"{name:18} {len(command):7} B  total {total:6.1f}s  slow[{'; '.join(slow)}]  {', '.join(got) or 'silent'}"[:250],
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
