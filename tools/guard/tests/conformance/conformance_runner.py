#!/usr/bin/env python3
"""Conformance run of the guard (tracker item #116): feed the recorded cases to any program through the guard's
command line and compare what comes back, byte for byte, with the recorded answers of the Python guard.

  conformance_runner.py run --guard "<command line>" [--reference "<command line>"] [--only PREFIX]...
                            [--jobs N] [--root DIR]
  conformance_runner.py record --guard "<command line>" [--jobs N] [--root DIR]   (writes the golden file)
  conformance_runner.py list [--only PREFIX]...

A case's arguments are appended to the command line; the event goes on standard input. Compared per call: exit
code, stdout and stderr; per case: every file under its telemetry folder. Taken out first: the case folder's path
(`<CASE>`), the values of `ts` and `build` in a JSON log line, the time stamp in a capture file's name.
Exit codes: 0 every case matches (record: written); 1 a case differs; 2 the run cannot start (usage, a git or
Claude folder above the case root, a listener on the fan-out rule's llama port, a program that cannot start).
Standard library only, Python 3.9 and later.
"""
import argparse
import base64
import concurrent.futures
import contextlib
import json
import os
import pathlib
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import conformance_cases as cases_mod  # noqa: E402 (the folder is no package)

HERE = pathlib.Path(__file__).resolve().parent
GOLDEN = HERE / "golden" / "guard-0.12.2.jsonl"
DEFAULT_JOBS = min(os.cpu_count() or 1, 8)
CALL_TIMEOUT_S = 30  # the guard answers within its 3.5 s hook budget; a hung program is a difference, not a hang
LLAMA_PORT = 8012  # guard.py rule_fan_out adds a note to its ask when 127.0.0.1:8012 accepts a connection
STAMP_RE = re.compile(r"-\d{8}T\d{6,}(\.json)$")  # guard.py capture(): <event>-<tool>-<UTC stamp>.json
RELAX_RE = re.compile(r'("(?:ts|build)"\s*:\s*)("(?:[^"\\]|\\.)*"|[-+.0-9eE]+|true|false|null)')


class CannotRun(Exception):
    """The run cannot start or a program cannot be started: exit 2, no verdict."""


def check_root(root: pathlib.Path) -> None:
    """Refuse a root below a git repository or a Claude folder: the guard looks up `.git`, `.claude/workflows` and
    `.claude/agents` in every folder above the event's cwd, so either would make the answers the machine's."""
    for d in [root, *root.parents]:
        for name in (".git", ".claude"):
            if os.path.lexists(d / name):
                raise CannotRun(f"{d / name} lies above the case root {root}: choose a root outside it (--root)")


def check_port() -> None:
    try:
        with socket.create_connection(("127.0.0.1", LLAMA_PORT), timeout=0.3):
            pass
    except OSError:
        return
    raise CannotRun(f"127.0.0.1:{LLAMA_PORT} accepts connections: the fan-out ask would name it; stop it first")


def call_env(case_dir: pathlib.Path, extra: dict[str, str]) -> dict[str, str]:
    """The environment of a call, built from nothing: nothing of the runner's own reaches the program but PATH."""
    env = {
        "PATH": os.environ.get("PATH", os.defpath),  # git and the program's interpreter are found on it
        "HOME": str(case_dir / "home"),
        "KZ_TELEMETRY_DIR": str(case_dir / "telemetry"),
        "CLAUDE_CONFIG_DIR": str(case_dir / "claude-config"),
        "KZ_HOST_INSTALL": "ask",  # `auto` reads CI variables and /.dockerenv: machine-dependent, left out by name
        "GIT_CEILING_DIRECTORIES": str(case_dir),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LC_ALL": "C",
        "PYTHONUTF8": "1",  # the same stdio encoding on macOS and Linux, whatever the locale
    }
    env.update(extra)
    return env


def _write(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def prepare(case: "cases_mod.Case", case_dir: pathlib.Path) -> None:
    for sub in ("repo", "home", "telemetry", "claude-config"):
        (case_dir / sub).mkdir(parents=True)
    _write(case_dir / "repo" / ".claude" / "guard.json", case.config)
    if case.local is not None:
        _write(case_dir / "repo" / ".claude" / "guard.local.json", case.local)
    if case.branch is not None:  # the three things git needs to see a repository, on an unborn branch
        git = case_dir / "repo" / ".git"
        (git / "objects").mkdir(parents=True)
        (git / "refs" / "heads").mkdir(parents=True)
        _write(git / "HEAD", f"ref: refs/heads/{case.branch}\n")
        _write(git / "config", "[core]\n\trepositoryformatversion = 0\n\tbare = false\n")
    for rel, text in case.files.items():
        _write(case_dir / rel, text)


def _text(data: bytes):
    """A string when the bytes are UTF-8, else {"base64": ...}: no byte is lost in the golden file."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(data).decode("ascii")}


def _relax(name: str, data: bytes) -> bytes:
    if not name.endswith(".jsonl"):
        return data
    text = data.decode("utf-8", "surrogateescape")
    return RELAX_RE.sub(lambda m: m.group(1) + '"<relaxed>"', text).encode("utf-8", "surrogateescape")


def telemetry(case_dir: pathlib.Path) -> list:
    folder = case_dir / "telemetry"
    out = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() or p.is_symlink():
            name = STAMP_RE.sub(r"-<stamp>\1", p.relative_to(folder).as_posix())
            data = p.read_bytes().replace(str(case_dir).encode(), b"<CASE>")
            out.append([name, _text(_relax(name, data))])
    return out


def run_case(argv: list[str], case: "cases_mod.Case", case_dir: pathlib.Path) -> dict:
    prepare(case, case_dir)
    repo = str(case_dir / "repo")
    mark, here = cases_mod.REPO.encode(), json.dumps(repo)[1:-1].encode()
    calls = []
    for call in case.calls:
        try:
            r = subprocess.run(argv + call.args, input=call.stdin.replace(mark, here), capture_output=True,
                               cwd=repo, env=call_env(case_dir, call.env), timeout=CALL_TIMEOUT_S)
            code, out, err = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired as exc:
            code, out, err = "timeout", exc.stdout or b"", exc.stderr or b""
        except OSError as exc:
            raise CannotRun(f"{shlex.join(argv)}: {exc}") from exc
        out, err = (b.replace(str(case_dir).encode(), b"<CASE>") for b in (out, err))
        calls.append({"args": call.args, "exit": code, "stdout": _text(out), "stderr": _text(err)})
    return {"id": case.id, "calls": calls, "files": telemetry(case_dir)}


def run_cases(cases: list, argv: list[str], root: pathlib.Path, jobs: int, times: Optional[dict] = None) -> dict:
    """{case id: answer} of the program on every case, each in a fresh folder below root."""
    check_root(pathlib.Path(os.path.realpath(root)))  # before anything is made there
    root.mkdir(parents=True, exist_ok=True)
    root = pathlib.Path(os.path.realpath(tempfile.mkdtemp(prefix="run-", dir=root)))  # /var is /private/var on macOS

    def one(item):
        n, case = item
        start = time.monotonic()
        answer = run_case(argv, case, root / f"{n:05d}")
        if times is not None:
            times[case.id] = time.monotonic() - start
        return answer

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        return {a["id"]: a for a in pool.map(one, enumerate(cases))}


def load_golden(path: pathlib.Path = GOLDEN) -> dict:
    lines = [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln]
    return {a["id"]: a for a in map(json.loads, lines)}


def golden_text(answers: dict) -> str:
    return "".join(json.dumps(answers[k], sort_keys=True, ensure_ascii=False) + "\n" for k in sorted(answers))


def differing(expected: dict, got: dict) -> list[str]:
    return sorted(k for k in set(expected) | set(got) if expected.get(k) != got.get(k))


def describe(case_id: str, expected: Optional[dict], got: Optional[dict]) -> str:
    """The first difference in full: each call field and each telemetry file that differs."""
    if expected is None or got is None:
        return f"{case_id}: {'no recorded answer' if expected is None else 'no such case any more'}"
    lines = [f"{case_id}:"]
    for n in range(max(len(expected["calls"]), len(got["calls"]))):
        e = expected["calls"][n] if n < len(expected["calls"]) else {}
        g = got["calls"][n] if n < len(got["calls"]) else {}
        for key in ("args", "exit", "stdout", "stderr"):
            if e.get(key) != g.get(key):
                lines += [f"  call {n + 1} {key}:", f"    expected {json.dumps(e.get(key))}",
                          f"    got      {json.dumps(g.get(key))}"]
    e_files, g_files = dict(map(tuple, expected["files"])), dict(map(tuple, got["files"]))
    if expected["files"] != got["files"]:
        for name in sorted(set(e_files) | set(g_files)):
            if e_files.get(name) != g_files.get(name):
                lines += [f"  file {name}:", f"    expected {json.dumps(e_files.get(name))}",
                          f"    got      {json.dumps(g_files.get(name))}"]
        if lines[-1] == f"{case_id}:":
            lines.append(f"  files: expected {expected['files']!r}, got {got['files']!r}")
    return "\n".join(lines)


def select(prefixes: Optional[list[str]]) -> list:
    cases = cases_mod.all_cases()
    return [c for c in cases if not prefixes or c.id.startswith(tuple(prefixes))]


def _program(command: str) -> list[str]:
    """The command line as a list; a word that names a file here is made absolute (the calls run in repo/)."""
    argv = [os.path.abspath(w) if os.path.exists(w) else w for w in shlex.split(command)]
    if not argv or not (shutil.which(argv[0]) or os.path.isfile(argv[0])):
        raise CannotRun(f"cannot start {command!r}")
    return argv


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("run", "record", "list"))
    ap.add_argument("--guard", help="the program's command line; the case's arguments are appended")
    ap.add_argument("--reference", help="compare with this program live instead of the golden file")
    ap.add_argument("--only", action="append", metavar="PREFIX", help="only the cases whose id starts so")
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    ap.add_argument("--root", help="make the case folders below this folder and keep them (default: a temporary one)")
    args = ap.parse_args(argv)
    if args.command != "list" and not args.guard:
        ap.error("--guard is needed")
    if args.command == "record" and (args.only or args.reference):
        ap.error("record writes every case from --guard: no --only, no --reference")
    if args.jobs < 1:
        ap.error("--jobs must be at least 1")
    cases = select(args.only)
    if args.command == "list":
        for case in cases:
            print(case.id)
        print(f"{len(cases)} cases", file=sys.stderr)
        return 0
    try:
        program = _program(args.guard)
        reference = _program(args.reference) if args.reference else None
        check_port()
        keep = contextlib.nullcontext(args.root) if args.root else tempfile.TemporaryDirectory(prefix="guard-conf-")
        with keep as tmp:
            times: dict = {}
            start = time.monotonic()
            got = run_cases(cases, program, pathlib.Path(tmp), args.jobs, times)
            if reference:
                expected = run_cases(cases, reference, pathlib.Path(tmp), args.jobs)
            elif args.command == "run":
                want = {c.id for c in cases}
                expected = {k: v for k, v in load_golden().items() if not args.only or k in want}
            seconds = time.monotonic() - start
    except (CannotRun, OSError) as exc:  # no golden file, a full disk: no verdict on the program
        print(f"conformance: cannot run: {exc}", file=sys.stderr)
        return 2
    slow = ", ".join(f"{k} {v:.2f}s" for k, v in sorted(times.items(), key=lambda kv: -kv[1])[:5])
    if args.command == "record":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(golden_text(got), encoding="utf-8")
        print(f"conformance: recorded {len(got)} cases in {GOLDEN} ({seconds:.1f} s; slowest: {slow})")
        return 0
    diff = differing(expected, got)
    print(f"conformance: {len(got)} cases, {len(diff)} differ ({seconds:.1f} s; slowest: {slow})")
    if not diff:
        return 0
    for case_id in diff[:50]:
        print(f"  {case_id}")
    if len(diff) > 50:
        print(f"  ... and {len(diff) - 50} more")
    print("first difference:\n" + describe(diff[0], expected.get(diff[0]), got.get(diff[0])))
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # a fault of the runner is no verdict on the program: exit 2, never the 1 of a difference
        traceback.print_exc()
        sys.exit(2)
