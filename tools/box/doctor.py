#!/usr/bin/env python3
"""doctor — inside the box, show that it is what it claims to be (plan step 1.0a); started by `bin/box doctor`.

  python3 /usr/local/share/agent-box/doctor.py [--kit DIR]

Checks, each one line: the session's uid is not 0; every tool's version equals its pin (pins.env baked into the
image); https://example.com is unreachable; no Docker socket; no host home inside (no /Users, no mount whose
source is the host home, no SSH or gh credentials); the marker is root's. With --kit, `ruff check tools` and
`pytest` on Python 3.9 and 3.13 in that checkout, as CI runs them. Exit codes: 0 every check passes, 1 otherwise.
"""
import argparse
import os
import re
import subprocess
import sys

SHARE = "/usr/local/share/agent-box"


def read_pins(path: str) -> dict:
    pins = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                pins[key] = value
    return pins


def output(argv: list) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"<{exc}>"
    return (r.stdout + r.stderr).strip()


def first_version(text: str) -> str:
    m = re.search(r"\d+\.\d+\.\d+", text)
    return m.group(0) if m else f"<none in {text[:60]!r}>"


VERSION_ARGV = {
    "node": ["node", "--version"], "python3.9": ["python3.9", "--version"],
    "python3.13": ["python3.13", "--version"], "pytest on 3.9": ["python3.9", "-m", "pytest", "--version"],
    "pytest on 3.13": ["python3.13", "-m", "pytest", "--version"], "ruff": ["ruff", "--version"],
    "gh": ["gh", "--version"], "git": ["git", "--version"], "claude": ["claude", "--version"],
}


def wanted_versions(pins: dict) -> dict:
    apt = dict(item.split("=", 1) for item in pins["APT_PINS"].split())
    return {"node": pins["NODE_VERSION"], "python3.9": pins["PYTHON_39"], "python3.13": pins["PYTHON_313"],
            "pytest on 3.9": pins["PYTEST_39"], "pytest on 3.13": pins["PYTEST_313"], "ruff": pins["RUFF"],
            "gh": pins["GH"], "git": first_version(apt["git"].split(":", 1)[-1]), "claude": pins["CLAUDE_CODE"]}


def version_checks(pins: dict) -> list:
    """[(name, wanted, found)] for every pinned tool."""
    return [(name, wanted, first_version(output(VERSION_ARGV[name]))) for name, wanted in wanted_versions(pins).items()]


def mount_sources() -> list:
    """(source root, mount point) of every mount, from /proc/self/mountinfo."""
    out = []
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) > 4:
                    out.append((parts[3], parts[4]))
    except OSError:
        pass
    return out


def checks(kit) -> list:
    """[(ok, line)]."""
    res = []
    uid = os.getuid()
    res.append((uid != 0, f"uid {uid} (not 0)"))
    try:
        pins = read_pins(os.path.join(SHARE, "pins.env"))
        for name, wanted, found in version_checks(pins):
            res.append((found == wanted, f"{name} {found} (pin {wanted})"))
    except (OSError, KeyError, IndexError) as exc:
        res.append((False, f"pins unreadable: {exc}"))
    curl = subprocess.run(["curl", "-sS", "-m", "5", "-o", "/dev/null", "https://example.com"],
                          capture_output=True, text=True)
    res.append((curl.returncode != 0, f"curl https://example.com fails (exit {curl.returncode})"))
    sock = [p for p in ("/var/run/docker.sock", "/run/docker.sock") if os.path.exists(p)]
    res.append((not sock, "no Docker socket" if not sock else f"Docker socket at {sock[0]}"))
    host_home = os.environ.get("BOX_HOST_HOME", "")
    homes = [(src, dst) for src, dst in mount_sources() if host_home and src.rstrip("/") == host_home.rstrip("/")]
    leaks = [p for p in ("/Users", os.path.expanduser("~/.ssh"), os.path.expanduser("~/.config/gh"),
                         os.path.expanduser("~/.claude/.credentials.json")) if os.path.exists(p)]
    res.append((bool(host_home) and not homes and not leaks,
                "no host home inside" if host_home and not homes and not leaks
                else f"host home check: told {host_home or 'nothing'}, mounts {homes}, paths {leaks}"))
    try:
        st = os.stat("/etc/agent-box/box.json")
        res.append((st.st_uid == 0 and not os.access("/etc/agent-box/box.json", os.W_OK),
                    f"marker owned by uid {st.st_uid}, writable: {os.access('/etc/agent-box/box.json', os.W_OK)}"))
    except OSError as exc:
        res.append((False, f"marker missing: {exc}"))
    if kit:
        pytest = ["-m", "pytest", "-p", "no:cacheprovider", "-o", "addopts=", "-q"]  # one -q: keep the summary line
        for label, argv in (("ruff check tools", ["ruff", "check", "tools"]),
                            ("pytest on 3.9", ["python3.9", *pytest]), ("pytest on 3.13", ["python3.13", *pytest])):
            r = subprocess.run(argv, cwd=kit, capture_output=True, text=True)
            lines = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.strip()]
            res.append((r.returncode == 0, f"{label}: exit {r.returncode}, {lines[-1] if lines else 'no output'}"))
    return res


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="doctor")
    ap.add_argument("--kit")
    ns = ap.parse_args(argv)
    results = checks(ns.kit)
    for ok, line in results:
        print(f"{'ok  ' if ok else 'FAIL'} {line}")
    failed = sum(not ok for ok, _ in results)
    print(f"doctor: {len(results) - failed} of {len(results)} checks pass")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
