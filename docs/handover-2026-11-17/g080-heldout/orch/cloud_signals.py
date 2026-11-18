"""Print what tells a process that it runs in a container or a cloud session. Names only, no values.

Usage: python3 -I cloud_signals.py
"""
import os

FILES = ("/.dockerenv", "/run/.containerenv")
FLAGS = ("GITHUB_ACTIONS", "TF_BUILD", "CODESPACES", "REMOTE_CONTAINERS", "CLAUDE_CODE_REMOTE")
# switches of the harness whose value is a flag or a counter, never a name, a token or an address
SWITCHES = (
    "CLAUDE_CODE_HOLD_UNANSWERED_PARKED_PERMISSION",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_WORKER_EPOCH",
)


def main():
    for path in FILES:
        print("file", path, "exists" if os.path.exists(path) else "absent")
    for name in FLAGS:
        value = os.environ.get(name)
        state = "unset" if value is None else ("set, empty" if value == "" else f"set, {len(value)} chars")
        if name == "CLAUDE_CODE_REMOTE" and value is not None:
            state += f", value {value!r}"
        print("flag", name, state)
    for name in SWITCHES:
        value = os.environ.get(name)
        print("switch", name, "unset" if value is None else repr(value[:40]))
    names = sorted(n for n in os.environ if n.startswith(("CLAUDE_CODE_", "CLAUDE_PROJECT", "CCR_")))
    print("names that start with CLAUDE_CODE_, CLAUDE_PROJECT or CCR_:", len(names))


if __name__ == "__main__":
    main()
