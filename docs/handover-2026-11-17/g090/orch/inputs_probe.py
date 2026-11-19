"""Which secret-shell verdicts rest on the reader's input redirections, and what a crash in the judge does to
them: for each command, the verdict as the guard gives it, with nested_inputs emptied, and with the secret-store
check made to raise. Nothing is run: commands are strings handed to the rule function.

usage: python3 -I inputs_probe.py <guard.py> [<guard.py> ...]
"""
import importlib.util
import sys

COMMANDS = [
    "cat < .env",
    "cat <.env",
    "cat<.env",
    "wc -l < .env",
    "sort <.env",
    "cat run.sh | sh; cat < .env",
    "cat run.sh | sh; cat<.env",
    "cat run.sh | sh; sort <.env",
    "bash -c 'sort <.env'",
    "sort < notes.txt",
]


def load(path, n):
    spec = importlib.util.spec_from_file_location(f"guard_inputs_{n}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verdict(g, command):
    g._nc_cached.cache_clear()
    ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                  "cwd": "/nonexistent-scratch"})
    try:
        got = g.rule_secret_shell(ev, dict(g.DEFAULTS))
    except Exception as exc:  # a crash of the rule is the finding this probe looks for
        return f"CRASH {type(exc).__name__}"
    return (got or ("silent",))[0]


def boom(seg):
    raise RuntimeError("planted")


def main(argv):
    for n, path in enumerate(argv):
        print(f"== {path.rsplit('/', 1)[-1]}: as given | inputs emptied | the store check raises")
        for command in COMMANDS:
            g = load(path, n)
            plain = verdict(g, command)
            g.nested_inputs = lambda c: ()
            no_inputs = verdict(g, command)
            g = load(path, n)
            g.secret_store_what = boom
            crashed = verdict(g, command)
            print(f"  {plain:7} | {no_inputs:7} | {crashed:22} | {command}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
