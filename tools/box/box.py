#!/usr/bin/env python3
"""box — build and start the box (plan step 1.0a): a container in which a session builds with permission checks off.

  python3 tools/box/box.py build                      build the image from pins.env, tag agent-box:<git SHA>

Standard library only, Python >= 3.9; runs on the owner's Mac. The image build is the one download, and it runs
in the container runtime that is already there. Tokens come only from the two Keychain entries the owner made
(plan section 7); they are never printed, never put on a command line and never written to a file.
Exit codes: 0 done, 1 refused or failed (the message names what to fix), 2 usage error.
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PINS = os.path.join(HERE, "pins.env")
IMAGE = "agent-box"
CLAUDE_TOKEN = "agent-box-claude"
GITHUB_TOKEN = "agent-box-github"
PIN_LINE = re.compile(r"([A-Z][A-Z0-9_]*)=(\S(?:.*\S)?)")


class BoxError(Exception):
    """A refusal or failure with a message that names what to fix."""


def read_pins(path: str = PINS) -> dict:
    pins = {}
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = PIN_LINE.fullmatch(line)
            if not m:
                raise BoxError(f"{path}:{n}: not KEY=VALUE: {line!r}")
            if m.group(1) in pins:
                raise BoxError(f"{path}:{n}: {m.group(1)} is pinned twice")
            pins[m.group(1)] = m.group(2)
    return pins


def git(*args: str, cwd: str = REPO) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise BoxError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def image_tag() -> str:
    """agent-box:<SHA of HEAD>; with uncommitted changes under tools/box, <SHA>-dirty, which only the probe takes."""
    sha = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--", os.path.relpath(HERE, REPO))
    return f"{IMAGE}:{sha}{'-dirty' if dirty else ''}"


def build(tag: str, out=None) -> None:
    pins = read_pins()
    argv = ["docker", "build", "--file", os.path.join(HERE, "Dockerfile"), "--tag", tag,
            "--label", f"org.opencontainers.image.revision={tag.split(':', 1)[1]}"]
    for key, value in pins.items():
        argv += ["--build-arg", f"{key}={value}"]
    r = subprocess.run(argv + [HERE], stdout=out, stderr=subprocess.STDOUT if out else None)
    if r.returncode != 0:
        raise BoxError(f"docker build failed (exit {r.returncode}) for {tag}")


def keychain(service: str) -> str:
    """The secret stored under service for this user. Never printed; a missing entry names itself."""
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", service,
                            "-w"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BoxError(f"cannot read the Keychain entry {service}: {exc}") from exc
    value = r.stdout.strip()
    if r.returncode != 0 or not value:
        raise BoxError(f"the Keychain entry {service} is missing or empty; store it as plan section 7 says "
                       f"(security add-generic-password -U -a \"$USER\" -s {service} -w)")
    return value


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="box", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("build")
    ns = ap.parse_args(argv)
    try:
        if ns.verb == "build":
            tag = image_tag()
            build(tag)
            print(f"box: built {tag}")
    except BoxError as exc:
        sys.stderr.write(f"box: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
