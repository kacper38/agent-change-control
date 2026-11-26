#!/usr/bin/env python3
"""box — build and start the box (plan step 1.0a): a container in which a session builds with permission checks off.

  bin/box build                       build the image from pins.env, tag agent-box:<git SHA of HEAD>
  bin/box run NAME                    a terminal session in box NAME (needs a terminal)
  bin/box run NAME --brief FILE       one headless session on FILE; writes a result file and prints its path
  bin/box doctor                      show the box is what it claims, and run CI's checks inside it

Standard library only, Python >= 3.9; runs on the owner's Mac. The image build is the one download, and it runs
in the container runtime that is already there. Everything a box keeps lives under ~/.agent-box (never the
owner's own Claude home): claude-home/ (CLAUDE_CONFIG_DIR for every box, transcripts kept 90 days), judge/<SHA>/
(a read-only copy of main, taken at each start, whose hooks are the only ones that run), boxes/NAME/clone/ (the
box's own clone of the repository, made inside the box over HTTPS) and boxes/NAME/results/. The container gets
none of the owner's home, no Docker socket and only these mounts. Tokens come only from the Keychain entries
agent-box-claude and agent-box-github (plan section 7): never printed, never on a command line, never in the image
or the repository; a missing, expired or revoked token stops the start with the entry's name, and nothing falls
back to the owner's own gh login. A clone whose committed policy (.claude/guard.json at HEAD) does not say
boundary own starts no box. Inside, the judge's guard runs its profile `box` (guard 0.11.0): it logs or denies
and never asks, so the wrapper no longer sets KZ_RULES_OFF (plan section 5, row 1, ended by step 1.0b).
Exit codes: 0 done, 1 refused or failed (the message names what to fix), 2 usage.
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PINS = os.path.join(HERE, "pins.env")
IMAGE = "agent-box"
CLAUDE_TOKEN = "agent-box-claude"
GITHUB_TOKEN = "agent-box-github"
TOKEN_ENV = {CLAUDE_TOKEN: "CLAUDE_CODE_OAUTH_TOKEN", GITHUB_TOKEN: "GH_TOKEN"}
MODEL = "claude-opus-5-5"  # plan section 6, decision 13: the wrapper pins the model; a brief cannot change it
TRANSCRIPT_DAYS = 90  # decision 10
PROJECT_DIR_FORM = '"${CLAUDE_PROJECT_DIR:-.}"'
PIN_LINE = re.compile(r"([A-Z][A-Z0-9_]*)=(\S(?:.*\S)?)")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SLUG = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?")


class BoxError(Exception):
    """A refusal or failure with a message that names what to fix."""


def box_root() -> str:
    return os.path.expanduser("~/.agent-box")


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


def git(*args: str, cwd: str = REPO, stdout=subprocess.PIPE) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, stdout=stdout, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise BoxError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return (r.stdout or "").strip()


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


def clean_image() -> str:
    """The image for HEAD, built if it is not there; a tree with uncommitted box files starts no box."""
    tag = image_tag()
    if tag.endswith("-dirty"):
        raise BoxError("tools/box has uncommitted changes; a box runs only an image tagged with a commit")
    r = subprocess.run(["docker", "image", "inspect", tag], capture_output=True, text=True)
    if r.returncode != 0:
        build(tag, out=sys.stderr)
    return tag


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


def repo_slug(url: str) -> str:
    m = SLUG.fullmatch(url.strip())
    if not m:
        raise BoxError(f"origin is not a GitHub repository: {url!r}")
    return m.group(1)


def check_github(token: str, slug: str, opener=urllib.request.urlopen) -> None:
    """The GitHub token must open this repository; it is sent in a header, never in a URL or on a command line, and
    in one urllib does not carry across a redirect, so it reaches no host but api.github.com."""
    req = urllib.request.Request(f"https://api.github.com/repos/{slug}",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "agent-box"})
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with opener(req, timeout=20) as resp:
            if resp.status == 200:
                return
            raise BoxError(f"the token in {GITHUB_TOKEN} got HTTP {resp.status} for {slug}")
    except urllib.error.HTTPError as exc:
        what = {401: "is expired or revoked", 403: "is refused", 404: "cannot see the repository"}
        raise BoxError(f"the token in {GITHUB_TOKEN} {what.get(exc.code, f'got HTTP {exc.code}')} ({slug}); "
                       f"make a new one as plan section 7 says") from exc
    except OSError as exc:
        raise BoxError(f"cannot check the token in {GITHUB_TOKEN}: {exc}") from exc


def token_env(slug: str) -> dict:
    env = {TOKEN_ENV[service]: keychain(service) for service in (CLAUDE_TOKEN, GITHUB_TOKEN)}
    check_github(env["GH_TOKEN"], slug)
    return env


def committed_boundary(repo: str, rev: str = "HEAD") -> str:
    """boundary in .claude/guard.json as committed at rev; "" when the file or the key is missing."""
    r = subprocess.run(["git", "show", f"{rev}:.claude/guard.json"], cwd=repo, capture_output=True, text=True)
    return boundary_of(r.stdout) if r.returncode == 0 else ""


CLONE_FACTS = ("git -C /work rev-parse HEAD && git -C /work rev-parse --abbrev-ref HEAD && "
               "{ git -C /work show HEAD:.claude/guard.json 2>/dev/null || true; }")


def parse_clone_facts(code: int, stdout: str, stderr: str = "") -> dict:
    lines = stdout.splitlines()
    if code != 0 or len(lines) < 2 or not re.fullmatch(r"[0-9a-f]{40}", lines[0].strip()):
        raise BoxError(f"cannot read the box's clone (exit {code}: {stderr.strip()[:200]}); look at it, "
                       f"nothing is deleted")
    return {"head": lines[0].strip(), "branch": lines[1].strip(), "boundary": boundary_of("\n".join(lines[2:]))}


def clone_facts(image: str, clone: str) -> dict:
    """HEAD, branch and the committed boundary of the box's clone, read by git inside a throwaway container with
    no network and the clone read-only: the session controls that clone, .git/config included, so the owner's
    own git never runs in it."""
    argv = ["docker", "run", "--rm", "--network", "none", "--user", "1000:1000", "--entrypoint", "sh",
            "--security-opt", "no-new-privileges", "--mount", f"type=bind,src={clone},dst=/work,readonly",
            image, "-c", CLONE_FACTS]
    r = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return parse_clone_facts(r.returncode, r.stdout, r.stderr)


VERIFIED = os.path.join(os.path.dirname(HERE), "orchestration", "verified.json")
GATE = "hook-deny-checks-off"


def box_changed_since(sha: str) -> bool:
    """True when tools/box differs between sha and HEAD, or sha is not a commit here."""
    r = subprocess.run(["git", "diff", "--quiet", sha, "HEAD", "--", os.path.relpath(HERE, REPO)], cwd=REPO,
                       capture_output=True)
    return r.returncode != 0


def probe_gate(pins: dict, path: str = VERIFIED, changed=box_changed_since) -> None:
    """No session with permission checks off before the probe has shown that a hook's deny blocks the call, for
    this CLI version and for the image as tools/box is now: the answer also rests on the image's settings and the
    wrapper's rewrite of them, so any change under tools/box since the probed image asks for a new probe run
    (criterion 2 of #63). A record made on an image with uncommitted changes never counts."""
    try:
        with open(path, encoding="utf-8") as fh:
            box = json.load(fh).get("box") or {}
    except (OSError, ValueError, AttributeError) as exc:
        raise BoxError(f"no probe record at {path}: {exc}") from exc
    status = ((box.get("questions") or {}).get(GATE) or {}).get("status")
    if box.get("cli_version") != pins.get("CLAUDE_CODE") or status != "holds":
        raise BoxError(f"the probe has not shown that a hook's deny holds with permission checks off for CLI "
                       f"{pins.get('CLAUDE_CODE')} (record: CLI {box.get('cli_version')}, {GATE} {status}); "
                       f"run python3 tools/box/box_probe.py first")
    probed = str(box.get("image", "")).split(":", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{40}", probed) or changed(probed):
        raise BoxError(f"tools/box changed since the probed image {box.get('image')}; run python3 "
                       f"tools/box/box_probe.py again before a session starts")


def boundary_of(text: str) -> str:
    """boundary in the text of a guard.json; "" when unreadable or missing."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    return str(data.get("boundary", "")) if isinstance(data, dict) else ""


def own_or_refuse(boundary: str, what: str) -> None:
    if boundary != "own":
        raise BoxError(f"{what}: the committed .claude/guard.json says boundary {boundary or 'nothing'}, not own; "
                       f"a box starts only for a boundary own repository")


def require_own(repo: str, rev: str, what: str) -> None:
    """For the owner's own checkout (main); the box's clone is read inside a container (clone_facts)."""
    own_or_refuse(committed_boundary(repo, rev), what)


def take_judge(root: str) -> tuple:
    """(SHA, folder): main as of now, fetched, exported once per SHA, read-only."""
    git("fetch", "--quiet", "origin", "main")
    sha = git("rev-parse", "origin/main")
    require_own(REPO, sha, "main")
    folder = os.path.join(root, "judge", sha)
    if not os.path.isdir(folder):
        os.makedirs(os.path.dirname(folder), exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=f".{sha[:12]}-", dir=os.path.dirname(folder))
        archive = subprocess.Popen(["git", "archive", "--format=tar", sha], cwd=REPO, stdout=subprocess.PIPE)
        untar = subprocess.run(["tar", "-x", "-C", tmp], stdin=archive.stdout, capture_output=True, text=True)
        archive.stdout.close()
        if archive.wait() != 0 or untar.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)  # our own half-written export, never anything else
            raise BoxError(f"cannot export main {sha[:12]}: {untar.stderr.strip()[:200]}")
        try:
            os.rename(tmp, folder)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
            if not os.path.isdir(folder):  # another start exported the same SHA at the same time: take that one
                raise BoxError(f"cannot move the export of main {sha[:12]} to {folder}") from None
    return sha, folder


def managed_settings(judge: str) -> dict:
    """The judge's hooks as managed settings, the only hooks that run in the box; fails closed on a hook that does
    not resolve to the judge."""
    with open(os.path.join(judge, ".claude", "settings.json"), encoding="utf-8") as fh:
        project = json.load(fh)
    hooks = json.loads(json.dumps(project.get("hooks") or {}).replace(json.dumps(PROJECT_DIR_FORM)[1:-1], "/judge"))
    commands = [h.get("command", "") for groups in hooks.values() for group in groups for h in group.get("hooks", [])]
    if not commands or any("/judge/" not in c or "CLAUDE_PROJECT_DIR" in c for c in commands):
        raise BoxError("the judge's .claude/settings.json has a hook that does not resolve to the judge")
    return {"_about": "Generated by tools/box/box.py from the judge's .claude/settings.json at the box's start.",
            "allowManagedHooksOnly": True, "hooks": hooks, "permissions": project.get("permissions") or {},
            "cleanupPeriodDays": TRANSCRIPT_DAYS, "model": MODEL}


def mounts(root: str, name: str, judge: str, managed: str) -> list:
    """[(host source, container target, read-only)]: the only mounts a box gets."""
    box = os.path.join(root, "boxes", name)
    return [(os.path.join(box, "clone"), "/work", False),
            (os.path.join(root, "claude-home"), "/box-home", False),
            (judge, "/judge", True),
            (managed, "/etc/claude-code/managed-settings.json", True)]


def docker_argv(image: str, name: str, seat: str, judge_sha: str, mount_list: list, command: list,
                tty: bool = False) -> list:
    argv = ["docker", "run", "--rm", "--init", "--name", f"agent-box-{name}", "--hostname", f"box-{name}",
            "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW", "--security-opt", "no-new-privileges"]
    argv += ["-it"] if tty else ["-i"]
    for key, value in (("BOX_NAME", name), ("BOX_SEAT", seat), ("BOX_IMAGE", image.split(":", 1)[1]),
                       ("BOX_JUDGE", judge_sha), ("BOX_HOST_HOME", os.path.expanduser("~")),
                       ("CLAUDE_CONFIG_DIR", "/box-home"), ("KZ_TELEMETRY_DIR", "/box-home/telemetry")):
        argv += ["-e", f"{key}={value}"]
    for var in TOKEN_ENV.values():
        argv += ["-e", var]  # by name: the value comes from the docker process's environment
    for src, dst, ro in mount_list:
        argv += ["--mount", f"type=bind,src={src},dst={dst}{',readonly' if ro else ''}"]
    return argv + [image] + command


def check_mounts(mount_list: list) -> None:
    """No mount of the owner's home folder itself, of a folder holding his credentials, or of a Docker socket."""
    home = os.path.realpath(os.path.expanduser("~"))
    for src, _, _ in mount_list:
        real = os.path.realpath(src)
        if real == home or real.endswith(".sock") or "docker.sock" in real:
            raise BoxError(f"refused mount {src}")
        for secret in (".ssh", ".claude", ".config/gh", ".aws", ".kube", ".docker", ".gnupg"):
            path = os.path.join(home, secret)
            if real == path or real.startswith(path + os.sep):
                raise BoxError(f"refused mount {src}: it is under {path}")


# At every start, so a clone made by an older wrapper gets it too (item #85); a clone without the hook is left alone.
HOOKS_PATH = "if [ -f /work/.githooks/commit-msg ]; then git -C /work config core.hooksPath .githooks; fi"


def set_hooks_path(image: str, clone: str, name: str) -> None:
    """core.hooksPath in the box's clone, set by git inside a throwaway container as clone_facts reads it: no
    network, no token and no entrypoint, so no firewall start spends a fetch of GitHub's ranges on it."""
    argv = ["docker", "run", "--rm", "--network", "none", "--user", "1000:1000", "--entrypoint", "sh",
            "--security-opt", "no-new-privileges", "--mount", f"type=bind,src={clone},dst=/work",
            image, "-c", HOOKS_PATH]
    r = subprocess.run(argv, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise BoxError(f"setting core.hooksPath in the clone of box {name} failed (exit {r.returncode})")


def prepare(name: str, seat: str) -> tuple:
    """Gate, folders, judge, managed settings, image and tokens for box name; (image, judge SHA, mounts, env)."""
    if not NAME.fullmatch(name):
        raise BoxError(f"not a box name: {name!r} (lower-case letters, digits and dashes, at most 40)")
    if not NAME.fullmatch(seat):
        raise BoxError(f"not a seat: {seat!r}")
    probe_gate(read_pins())
    root = box_root()
    slug = repo_slug(git("remote", "get-url", "origin"))
    env = dict(os.environ, **token_env(slug))
    image = clean_image()
    judge_sha, judge = take_judge(root)
    box = os.path.join(root, "boxes", name)
    for folder in (os.path.join(box, "clone"), os.path.join(box, "results"), os.path.join(root, "claude-home")):
        os.makedirs(folder, exist_ok=True)
    managed = os.path.join(box, "managed-settings.json")
    with open(managed + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(managed_settings(judge), fh, indent=2)
    os.replace(managed + ".tmp", managed)
    mount_list = mounts(root, name, judge, managed)
    check_mounts(mount_list)
    clone = os.path.join(box, "clone")
    if not os.path.isdir(os.path.join(clone, ".git")):
        if os.listdir(clone):
            raise BoxError(f"{clone} is not empty and not a clone; look at it, nothing is deleted")
        r = subprocess.run(docker_argv(image, name, seat, judge_sha, mount_list,
                                       ["git", "clone", "--quiet", f"https://github.com/{slug}.git", "/work"]),
                           env=env, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise BoxError(f"the clone inside the box failed (exit {r.returncode}); check the token in {GITHUB_TOKEN}")
    own_or_refuse(clone_facts(image, clone)["boundary"], f"the clone of box {name}")
    set_hooks_path(image, clone, name)
    return image, judge_sha, mount_list, env


# The CLI's JSON goes to the container's stdout, which the host captures into a folder no container sees.
HEADLESS = ["claude", "-p", "--dangerously-skip-permissions", "--model", MODEL, "--output-format", "json"]


def write_new(path: str, data: dict) -> None:
    """Create path with data; never follows a link and never replaces a file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def run(name: str, seat: str, brief=None, out=None) -> int:
    out = out or sys.stdout
    if brief is None and not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise BoxError("a terminal session needs a terminal; without one, give --brief FILE")
    if brief is not None and not os.path.isfile(brief):
        raise BoxError(f"no brief at {brief}")
    image, judge_sha, mount_list, env = prepare(name, seat)
    clone = mount_list[0][0]
    if brief is None:
        argv = docker_argv(image, name, seat, judge_sha, mount_list,
                           ["claude", "--dangerously-skip-permissions", "--model", MODEL], tty=True)
        return subprocess.run(argv, env=env).returncode
    started = _dt.datetime.now(_dt.timezone.utc)
    results = os.path.join(box_root(), "boxes", name, "results", started.strftime("%Y%m%dT%H%M%SZ"))
    os.makedirs(results)
    with open(brief, "rb") as fh:
        brief_bytes = fh.read()
    brief_copy = os.path.join(results, "brief.md")
    with open(brief_copy, "wb") as fh:
        fh.write(brief_bytes)
    before = clone_facts(image, clone)
    argv = docker_argv(image, name, seat, judge_sha, mount_list, HEADLESS)  # the brief goes in on stdin
    with open(brief_copy, "rb") as stdin, open(os.path.join(results, "out.json"), "wb") as stdout, \
            open(os.path.join(results, "stderr.txt"), "wb") as stderr:
        code = subprocess.run(argv, env=env, stdin=stdin, stdout=stdout, stderr=stderr).returncode
    try:
        with open(os.path.join(results, "out.json"), encoding="utf-8") as fh:
            cli = json.loads(fh.read().strip().splitlines()[-1])
    except (OSError, ValueError, IndexError):
        cli = None
    try:
        after = clone_facts(image, clone)
    except BoxError as exc:
        after = {"head": None, "branch": None, "error": str(exc)}
    record = {"schema": "agent-box-result/1", "name": name, "seat": seat, "image": image, "judge": judge_sha,
              "model": MODEL, "brief_sha256": hashlib.sha256(brief_bytes).hexdigest(),
              "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "ended": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "exit": code,
              "head_before": before["head"], "head_after": after.get("head"), "branch_after": after.get("branch"),
              "result": ({k: cli.get(k) for k in ("subtype", "is_error", "total_cost_usd", "num_turns", "session_id",
                                                  "result")} if isinstance(cli, dict) else None),
              "_about": "result comes from inside the box: the session's word, not evidence against it"}
    path = os.path.join(results, "result.json")
    write_new(path, record)
    out.write(f"box: result {path}\n")
    ok = code == 0 and isinstance(cli, dict) and not cli.get("is_error")
    return 0 if ok else 1


def doctor(out=None) -> int:
    """Start a box with no tokens and run doctor.py inside, on a fresh clone of HEAD."""
    out = out or sys.stdout
    image = clean_image()
    sha = image.split(":", 1)[1]
    kit = os.path.join(box_root(), "doctor", sha)
    if not os.path.isdir(kit):
        os.makedirs(os.path.dirname(kit), exist_ok=True)
        git("clone", "--quiet", "--no-hardlinks", REPO, kit, cwd=os.path.dirname(kit))
        git("checkout", "--quiet", "--detach", sha, cwd=kit)
    check_mounts([(kit, "/kit", False)])
    argv = ["docker", "run", "--rm", "--init", "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW",
            "--security-opt", "no-new-privileges", "-e", "BOX_NAME=doctor", "-e", "BOX_SEAT=doctor",
            "-e", f"BOX_IMAGE={sha}", "-e", f"BOX_JUDGE={sha}", "-e", f"BOX_HOST_HOME={os.path.expanduser('~')}",
            "--mount", f"type=bind,src={kit},dst=/kit", image,
            "python3", "/usr/local/share/agent-box/doctor.py", "--kit", "/kit"]
    out.write(f"box: doctor on {image}, kit at {kit}\n")
    out.flush()
    return subprocess.run(argv, stdin=subprocess.DEVNULL).returncode


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="box", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("build")
    p_run = sub.add_parser("run")
    p_run.add_argument("name")
    p_run.add_argument("--brief")
    p_run.add_argument("--seat", help="defaults to the box name")
    sub.add_parser("doctor")
    ns = ap.parse_args(argv)
    try:
        if ns.verb == "build":
            tag = image_tag()
            build(tag)
            print(f"box: built {tag}")
            return 0
        if ns.verb == "run":
            return run(ns.name, ns.seat or ns.name, ns.brief)
        return doctor()
    except BoxError as exc:
        sys.stderr.write(f"box: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
