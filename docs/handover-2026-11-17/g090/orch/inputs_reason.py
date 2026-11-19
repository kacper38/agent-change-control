"""The reason text secret-shell gives for a secret file behind an input redirection when the reader pass asks
for another cause too: an unread pipe, or a crash in the judge after the read went through. Nothing is run.

usage: python3 -I inputs_reason.py <guard.py> [<guard.py> ...]
"""
import importlib.util
import sys

CASES = [("as given", "cat<.env", False), ("an unread pipe on the line", "cat run.sh | sh; cat<.env", False),
         ("the store check raises", "cat<.env", True), ("pipe and the store check raises", "cat run.sh | sh; cat<.env", True),
         ("too deep to read", None, False)]


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_reason_{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def boom(seg):
    raise RuntimeError("planted")


def main(argv):
    for n, path in enumerate(argv):
        print(f"== {path.rsplit('/', 1)[-1]}")
        for label, command, crash in CASES:
            g = load(path, n)
            if command is None:  # a nest one level deeper than the reader goes, with the redirection at the top
                inner = "echo x"
                for _ in range(g._HI_MAX_DEPTH + 1):
                    inner = "bash -c " + g.shlex.quote(inner) if hasattr(g, "shlex") else "bash -c '" + inner.replace("'", "'\\''") + "'"
                command = inner + "; cat<.env"
            if crash:
                g.secret_store_what = boom
            g._nc_cached.cache_clear()
            ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                          "cwd": "/nonexistent-scratch"})
            try:
                got = g.rule_secret_shell(ev, dict(g.DEFAULTS))
            except Exception as exc:
                got = ("CRASH", type(exc).__name__)
            verdict, reason = got or ("silent", "")
            print(f"  {label:32} | {verdict:6} | names .env: {'.env' in reason!s:5} | {reason[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
