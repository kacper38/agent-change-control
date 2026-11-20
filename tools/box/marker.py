#!/usr/bin/env python3
"""marker — write /etc/agent-box/box.json, the box's marker (plan step 1.0a), as root, after the firewall is set.

  python3 marker.py [--path /etc/agent-box/box.json]

The marker is the one signal that loosens a rule (plan section 6, decision 5; read by the guard from step 1.0b
on), so it is owned by root, mode 0444, and written by the entrypoint before it drops to the user; a session
inside cannot write or remove it. Its values come from the wrapper's environment (BOX_NAME, BOX_SEAT, BOX_IMAGE,
BOX_JUDGE) and must be plain tokens: anything else stops the start. Exit codes: 0 written, 1 refused or failed.
"""
import argparse
import datetime as _dt
import json
import os
import re
import sys

SCHEMA = "agent-box/1"
FIELDS = ("BOX_NAME", "BOX_SEAT", "BOX_IMAGE", "BOX_JUDGE")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}")


def marker(env: dict, now: _dt.datetime) -> dict:
    values = {}
    for key in FIELDS:
        value = env.get(key, "")
        if not TOKEN.fullmatch(value):
            raise ValueError(f"{key} is missing or not a plain token: {value!r}")
        values[key[4:].lower()] = value
    return {"schema": SCHEMA, **values, "boundary": "own", "firewall": "set",
            "started": now.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="marker")
    ap.add_argument("--path", default="/etc/agent-box/box.json")
    ns = ap.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise ValueError("the marker is written by root only")
        data = marker(dict(os.environ), _dt.datetime.now(_dt.timezone.utc))
        if os.path.lexists(ns.path):
            raise ValueError(f"{ns.path} exists already; a box writes its marker once")
        fd = os.open(ns.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.chown(ns.path, 0, 0)
        os.chmod(ns.path, 0o444)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"marker: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
