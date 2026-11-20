#!/usr/bin/env python3
"""guard — deterministic hook engine for Claude Code and GitHub Copilot.

Standard library only, Python >= 3.9. Reads one hook event as JSON on stdin,
normalizes it across harnesses, runs the registered rules and answers with a
permission decision. It never emits "allow": staying silent leaves the
harness's own permission flow untouched (an explicit "allow" would bypass it).

Exit codes: 0 = no objection or "ask" (JSON on stdout); 2 = deny (JSON on
stdout, reason on stderr); 1 = guard itself failed (nothing on stdout).

Usage:
  guard.py hook pre [--wrapper claude|github]   run every PreToolUse rule
  guard.py hook <rule> [--wrapper ...]          run one rule (tests, debugging, SubagentStart -> fan-out)
  guard.py hook capture [--wrapper ...]         record redacted raw input, never blocks
  guard.py hook post [--wrapper claude]         after a call (PostToolUse[Failure]): log that an asked call ran
  guard.py rules | help | version
"""

import bisect
import collections
import copy
import datetime as _dt
import functools
import json
import os
import re
import select
import shlex
import signal
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Mapping
from typing import Callable, Optional

VERSION = "0.10.0"

# ----------------------------------------------------------------------------
# Harness normalization
# ----------------------------------------------------------------------------

CLAUDE_TOOLS = {
    "Bash": "shell",
    "Read": "read",
    "Write": "write",
    "Edit": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Agent": "spawn",
    "Task": "spawn",
    "Glob": "search",
    "Grep": "search",
    "WebFetch": "web",
    "WebSearch": "web",
    "Monitor": "shell",  # runs a shell command, judged as Bash's
    "ExitWorktree": "worktree",
    "Skill": "skill",
    "Workflow": "workflow",
    "RemoteTrigger": "cloud",
    "DesignSync": "design",
}
# The built-in tools of a Claude Code session and how the guard treats each: `judged` (a rule reads the call, so
# the PreToolUse matcher must name it), `cloud-launch` (it can start cloud work, D3 of item #65) or `harmless`
# (it starts no cloud work and no rule reads it: WebFetch and WebSearch have the kind `web` in CLAUDE_TOOLS, but
# no rule judges that kind and the matcher does not name them, so what they send out is unguarded, a named limit
# of item #65). Filled from the init message of the probe's
# tool-list canary (CLI 2.1.323, 2026-11-20, the box and the owner's Mac); the canary fails when the session's list
# differs from these names.
KNOWN_CLAUDE_TOOLS = {
    "Bash": "judged",
    "CronCreate": "harmless",  # local: a prompt queued in this session (durable: .claude/scheduled_tasks.json)
    "CronDelete": "harmless",
    "CronList": "harmless",
    "DesignSync": "cloud-launch",  # sends material to a service of the account: every call asks
    "Edit": "judged",
    "EnterWorktree": "harmless",  # a new worktree under .claude/worktrees/ on a new branch
    "ExitWorktree": "judged",  # action remove deletes the worktree and its branch: delete-guard asks
    "ListAgents": "harmless",
    "Monitor": "judged",  # runs a shell command, as Bash does
    "NotebookEdit": "judged",
    "Read": "judged",
    "RemoteTrigger": "cloud-launch",  # manages and runs the account's cloud routines: every call denied
    "ReportFindings": "harmless",
    "ScheduleWakeup": "harmless",  # local: the /loop of this session
    "SendMessage": "harmless",  # messages a running session; it starts none
    "Skill": "cloud-launch",  # the schedule skill creates cloud routines
    "Task": "judged",  # fan-out; the init list says Task, hooks get Agent: both names stay in the matcher
    "TaskStop": "harmless",
    "ToolSearch": "harmless",
    "WebFetch": "harmless",
    "WebSearch": "harmless",
    "Workflow": "cloud-launch",  # a script whose agent() asks for isolation remote
    "Write": "judged",
}
COPILOT_TOOLS = {
    "bash": "shell",
    "powershell": "shell",
    "view": "read",
    "create": "write",
    "edit": "edit",
    "task": "spawn",
    "glob": "search",
    "grep": "search",
    "web_fetch": "web",
    "web_search": "web",
}
EVENT_NAMES = {
    "pretooluse": "PreToolUse",
    "posttooluse": "PostToolUse",
    "posttoolusefailure": "PostToolUseFailure",
    "sessionstart": "SessionStart",
    "sessionend": "SessionEnd",
    "userpromptsubmit": "UserPromptSubmit",
    "userpromptsubmitted": "UserPromptSubmit",
    "stop": "Stop",
    "agentstop": "Stop",
    "subagentstart": "SubagentStart",
    "subagentstop": "SubagentStop",
    "precompact": "PreCompact",
    "notification": "Notification",
    "permissionrequest": "PermissionRequest",
}


class Event:
    """One hook invocation, the same shape whichever harness sent it."""

    def __init__(self, raw: dict):
        self.raw = raw
        name = raw.get("hook_event_name") or raw.get("hookEventName") or ""
        self.event = EVENT_NAMES.get(str(name).lower(), str(name))
        self.tool = str(raw.get("tool_name") or raw.get("toolName") or "")
        args = raw.get("tool_input") if "tool_input" in raw else raw.get("toolArgs")
        self.unreadable = False  # arguments present but not a JSON object: no rule can see the call, run_hook asks
        if isinstance(args, str):  # Copilot CLI may JSON-encode toolArgs (testguard and latest_tag parse it too)
            try:
                decoded = json.loads(args) if args.strip() else {}  # an empty string is "no arguments"
            except (ValueError, RecursionError):  # a crash here would fail open on a Copilot timeout
                decoded = None
            self.unreadable = not isinstance(decoded, dict)  # a list, a bare string or null hide the call too
            args = decoded
        elif args is not None and not isinstance(args, dict):
            self.unreadable = True
        self.args: dict = args if isinstance(args, dict) else {}
        if self.tool in CLAUDE_TOOLS:
            self.harness = "claude"
        elif self.tool in COPILOT_TOOLS:
            self.harness = "copilot"
        elif "toolName" in raw or "toolArgs" in raw or "timestamp" in raw:
            self.harness = "copilot"
        elif "transcript_path" in raw or "permission_mode" in raw:
            self.harness = "claude"
        else:
            self.harness = "unknown"
        self.kind = CLAUDE_TOOLS.get(self.tool) or COPILOT_TOOLS.get(self.tool) or (
            "github" if self.tool.startswith(GITHUB_TOOL_PREFIXES) else "other")
        self.cwd = str(raw.get("cwd") or os.getcwd())
        self.session = str(raw.get("session_id") or raw.get("sessionId") or "")
        self.command = _first_str(self.args, "command", "cmd", "commandLine", "script")
        self.path = _first_str(self.args, "file_path", "path", "filePath", "file", "notebook_path")
        self.content = _first_str(self.args, "content", "file_text", "new_source", "text")

    def abspath(self) -> Optional[str]:
        if not self.path:
            return None
        p = os.path.expanduser(self.path)
        if not os.path.isabs(p):
            p = os.path.join(self.cwd, p)
        return os.path.normpath(p)


def _first_str(d: dict, *keys: str) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return None


# ----------------------------------------------------------------------------
# Config and knobs
# ----------------------------------------------------------------------------

DEFAULTS = {
    "telemetry_dir": "~/.claude/telemetry",
    "protected_branches": ["main"],
    "boundary": "own",
    "scratch_md_mode": "ask",  # ask | deny | off
    "host_install": "auto",  # auto (silent only in a container or CI) | ask | off
    "rules_off": [],  # rules whose asks are silenced (own repos only): guard.json, guard.local.json, KZ_RULES_OFF
    "scratch_md_allow": [
        "docs/", ".claude/", ".github/", "skills/", "agents/", ".agents/", "evidence/",
        "README.md", "DECISIONS.md", "AGENTS.md", "CLAUDE.md", "CHANGELOG.md", "CONTRIBUTING.md",
        "SECURITY.md", "LICENSE.md", "**/README.md", "**/SKILL.md", "**/AGENTS.md",
    ],
}


BOUNDARIES = ("own", "client")


def load_config(start: str, facts: Optional[dict] = None) -> dict:
    """Merge DEFAULTS <- nearest .claude/guard.json (walking up) <- its sibling guard.local.json <- KZ_* env.

    guard.local.json is the owner's uncommitted override (gitignored): only its `rules_off` is read, so a
    session can silence rules without a diff in the reviewable policy and nothing else moves. rules_off is
    dropped unless guard.json sits beside `.git` and says `boundary: own` itself (not the default) and the
    effective boundary is own. The boundary only tightens (0.10.0): an unknown value counts as client, and
    KZ_BOUNDARY=own leaves a committed client in force. In a box (0.11.0, `in_box` of the facts, read when none
    are handed in) the configuration is _box_config's instead."""
    if in_box(box_facts() if facts is None else facts):
        return _box_config(start)
    cfg = dict(DEFAULTS)
    d = os.path.abspath(start)
    relaxable = False  # rules_off counts only under a repo root whose committed guard.json says boundary own
    while True:
        candidate = os.path.join(d, ".claude", "guard.json")
        if os.path.isfile(candidate):
            for path in (candidate, os.path.join(d, ".claude", "guard.local.json")):
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict):
                        if path == candidate:
                            relaxable = data.get("boundary") == "own" and os.path.exists(os.path.join(d, ".git"))
                            if data.get("boundary", "own") not in BOUNDARIES:  # an unknown value tightens
                                print(f"guard: boundary {data['boundary']!r} in {path} is not own or client; "
                                      "it counts as client", file=sys.stderr)
                                data["boundary"] = "client"
                        else:  # the local file carries rules_off and nothing else
                            data = {k: v for k, v in data.items() if k == "rules_off"}
                        cfg.update(data)
                except (OSError, ValueError) as exc:  # a broken config must not silently vanish
                    print(f"guard: ignoring unreadable {path}: {exc}", file=sys.stderr)
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    env = os.environ.get("KZ_TELEMETRY_DIR")
    if env:
        cfg["telemetry_dir"] = env
    env = os.environ.get("KZ_PROTECTED_BRANCHES")
    if env:
        cfg["protected_branches"] = [b.strip() for b in env.split(",") if b.strip()]
    _env_boundary(cfg)
    relaxable = relaxable and cfg["boundary"] == "own"
    env = os.environ.get("KZ_SCRATCH_MD")
    if env:
        cfg["scratch_md_mode"] = env.strip()
    env = os.environ.get("KZ_HOST_INSTALL")
    if env:
        cfg["host_install"] = env.strip()
    env = os.environ.get("KZ_RULES_OFF")
    if env is not None:
        cfg["rules_off"] = [r.strip() for r in env.split(",") if r.strip()]
    if not relaxable:
        if cfg["rules_off"]:
            print("guard: rules_off ignored: the root's committed guard.json must say boundary own", file=sys.stderr)
        cfg["rules_off"] = []  # no committed policy at the repo root that says own: nothing to relax
    off = cfg["rules_off"]
    if not (isinstance(off, list) and all(isinstance(r, str) for r in off)):
        print("guard: ignoring rules_off: expected a list of rule names", file=sys.stderr)
        cfg["rules_off"] = []  # a malformed override switches nothing off
    else:
        for name in sorted(set(off) - set(RULES)):
            print(f"guard: rules_off names no rule {name!r}", file=sys.stderr)
    return cfg


def _env_boundary(cfg: dict) -> None:
    """KZ_BOUNDARY can only tighten: client sets client, own changes nothing, anything else counts as client."""
    env = os.environ.get("KZ_BOUNDARY")
    if env:
        env = env.strip()
        if env == "own" and cfg["boundary"] != "own":
            print("guard: KZ_BOUNDARY=own does not loosen the committed boundary client", file=sys.stderr)
        elif env != "own":
            if env != "client":
                print(f"guard: KZ_BOUNDARY {env!r} is no boundary (own or client); it counts as client",
                      file=sys.stderr)
            cfg["boundary"] = "client"


# the environment knobs that can loosen; a box ignores each (D3 of item #66) and says so
BOX_IGNORED_ENV = ("KZ_RULES_OFF", "KZ_PROTECTED_BRANCHES", "KZ_SCRATCH_MD", "KZ_HOST_INSTALL")


def _read_policy(path: str) -> Optional[dict]:
    """A guard.json as a dict; None when it is missing, and, with a note, when it is unreadable or no object."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError) as exc:  # a broken config must not silently vanish
        print(f"guard: ignoring unreadable {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"guard: ignoring {path}: not a JSON object", file=sys.stderr)
        return None
    return data


def _box_config(start: str) -> dict:
    """The configuration in a box (D3), valid marker or not, since all of it only tightens: DEFAULTS <- the
    committed guard.json beside the guard (<guard root>/.claude/guard.json, never its guard.local.json, never its
    rules_off) <- client when the nearest guard.json above `start` (the work clone's) names any boundary but own
    <- KZ_BOUNDARY (only tightens) and KZ_TELEMETRY_DIR. rules_off is always empty; the knobs that can loosen
    (BOX_IGNORED_ENV) are ignored, each with a note."""
    cfg = dict(DEFAULTS)
    path = os.path.join(guard_root(), ".claude", "guard.json")
    data = _read_policy(path)
    if data:
        cfg.update({k: v for k, v in data.items() if k != "rules_off"})
        if cfg["boundary"] not in BOUNDARIES:  # an unknown value tightens
            print(f"guard: boundary {cfg['boundary']!r} in {path} is not own or client; it counts as client",
                  file=sys.stderr)
            cfg["boundary"] = "client"
    d = os.path.abspath(start)
    while True:
        candidate = os.path.join(d, ".claude", "guard.json")
        if os.path.isfile(candidate):
            data = _read_policy(candidate)
            if data and "boundary" in data and data["boundary"] != "own":  # a tightening, believed from anywhere
                cfg["boundary"] = "client"
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    env = os.environ.get("KZ_TELEMETRY_DIR")
    if env:
        cfg["telemetry_dir"] = env
    for name in BOX_IGNORED_ENV:
        if name in os.environ:
            print(f"guard: {name} is ignored in a box", file=sys.stderr)
    _env_boundary(cfg)
    cfg["rules_off"] = []
    return cfg


def protected_branches(cfg: dict) -> set:
    v = cfg.get("protected_branches")
    if v is None:
        v = DEFAULTS["protected_branches"]
    return {str(b) for b in v}  # an explicit empty list means: no protected branch here


def telemetry_dir(cfg: dict) -> str:
    return os.path.expanduser(str(cfg.get("telemetry_dir") or DEFAULTS["telemetry_dir"]))


# ----------------------------------------------------------------------------
# Decisions
# ----------------------------------------------------------------------------

Decision = tuple[str, str]  # ("ask"|"deny", reason)
RANK = {"ask": 1, "deny": 2}


def respond(decision: Optional[Decision], event_name: str) -> int:
    """Print the decision in the shape both harnesses read; return the exit code."""
    if decision is None:
        return 0
    verdict, reason = decision
    payload = {
        "permissionDecision": verdict,
        "permissionDecisionReason": reason,
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "permissionDecision": verdict,
            "permissionDecisionReason": reason,
        },
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
    if verdict == "deny":
        sys.stderr.write(reason + "\n")
        return 2
    return 0


def combine(decisions: list[Decision]) -> Optional[Decision]:
    """Strongest verdict wins; reasons of the winning class are joined."""
    if not decisions:
        return None
    top = max(RANK[d[0]] for d in decisions)
    reasons = [r for v, r in decisions if RANK[v] == top]
    verdict = "deny" if top == 2 else "ask"
    return verdict, " | ".join(dict.fromkeys(reasons))


# ----------------------------------------------------------------------------
# Rule: delete-guard (ported from ~/.claude/hooks/ask-on-delete.sh, owner rule
# 2026-09-24: never auto-approve deletions, scripts included, no exceptions)
# ----------------------------------------------------------------------------

_ASSIGN = r"[A-Za-z_][A-Za-z0-9_]*=\S*\s+"
SHELL_RE = (
    r"(^|[;&|(`]|\$\()\s*(" + _ASSIGN + r")*((sudo|env|exec|command|time|nohup|doas)\s+("
    + _ASSIGN + r")*)*(/bin/|/usr/bin/)?(rm|rmdir|unlink|trash|shred|truncate)(\s|$)"
)
FIND_RE = (
    r"find\s.*(-delete|-exec\s+(/bin/)?rm)|xargs(\s+\S+)*\s+(/bin/)?(rm|rmdir|unlink|trash)(\s|$)"
    r"|parallel(\s+\S+)*\s+(/bin/)?rm(\s|$)"
)
_GIT = r"git\s+(-C\s+\S+\s+)?"
GIT_RE = (
    _GIT + r"(rm|clean|reset|restore|filter-branch|filter-repo)(\s|$)"
    + r"|" + _GIT + r"checkout\s+(--|-f|--force)"
    + r"|" + _GIT + r"branch\s+.*(-D|-d|--delete)(\s|$)"
    + r"|" + _GIT + r"worktree\s+(remove|prune)"
    + r"|" + _GIT + r"push\s.*(--force|-f(\s|$)|--force-with-lease|--delete|\s:\S)"
    + r"|" + _GIT + r"stash\s+(drop|clear)"
    + r"|git\s+update-ref\s+-d|git\s+tag\s+(-d|--delete)"
)
TOOL_RE = (
    r"mise\s+(uninstall|prune)|npm\s+(uninstall|rm|un|r|unlink)(\s|$)|pnpm\s+(remove|rm|uninstall)"
    r"|yarn\s+remove|brew\s+(uninstall|remove|rm)|pip3?\s+uninstall|cargo\s+uninstall"
    r"|docker\s+(rm|rmi|system\s+prune|volume\s+(rm|prune)|image\s+prune|container\s+prune"
    r"|builder\s+prune|compose\s+(down|rm))|kubectl\s+delete|helm\s+(uninstall|delete)|dropdb"
    r"|prisma\s+migrate\s+reset|--force-reset|(DROP|drop)\s+(TABLE|DATABASE|SCHEMA|table|database|schema)"
    # SQL TRUNCATE: the upper-case keyword wherever it stands, as before 0.7.0; the lower-case word only where a
    # statement can start (line start, also written \n in a string, ; quote paren backtick) or in front of
    # `table`, so that prose such as "may truncate the description" does not ask (0.7.0). For a command line
    # _delete_judge adds the word outside quotes and the lines that name a SQL client; the coreutils `truncate`
    # command asks through SHELL_RE
    r"|TRUNCATE\s|(?:^|[;\"'(`]|\\n)(?:\s|\\[ntr])*truncate\s|truncate\s+table\s"
    r"|(DELETE|delete)\s+(FROM|from)\s|rclone\s+(delete|purge|sync)|rsync\s.*--delete"
)
CODE_RE = (
    r"os\.(remove|unlink|rmdir|removedirs)|shutil\.rmtree|\.unlink\(|\.rmdir\(|send2trash"
    r"|fs\.(rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)|fsPromises\.(rm|unlink|rmdir)|rimraf"
    # `del (x)` and `cache_del(k)`, not the tail of a word: "model (" and "load_model(x)" stay silent (0.7.0)
    r"|(?<![A-Za-z0-9])del\s*\("
    r"|remove_dir_all|remove_file|std::fs::remove|File\.(delete|unlink)|FileUtils\.(rm|remove)"
    r"|Remove-Item|Directory\.Delete|(^|\s)del\s+/[sq]|(^|\s)rd\s+/s"
)
DELETE_RE = re.compile("|".join([SHELL_RE, FIND_RE, GIT_RE, TOOL_RE, CODE_RE]), re.MULTILINE)
# on a command line that names one of these clients, the lower-case word is SQL wherever it stands
# (`echo truncate audit | psql`); the list holds the clients whose TRUNCATE needs no TABLE keyword. The name counts
# as a word of its own, whatever stands next to it (`"… | psql"`, `psql;`, `\psql`, `psql.exe`), not inside
# another word (`mysqldump`, `pymysql`, `.psqlrc`)
_SQL_TRUNCATE_RE = re.compile(r"truncate\s")
_SQL_CLIENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:psql|mysql|mariadb|cqlsh|snowsql|duckdb|cockroach|hbase|clickhouse)(?![A-Za-z0-9_])"
)
# the lower-case word as a word of its own in a simple command (`truncate`, `gtruncate`, `-truncate`): a quoted
# string with the word in it is one token with white space, and does not match
_OPEN_WORD_RE = re.compile(r"^\S*truncate$")
SCRIPT_RE = re.compile(
    r"(python3?|node|bun|deno|bash|sh|zsh|tsx|ts-node|ruby|perl|php)\s+(-\S+\s+)*(\S+\.(py|js|mjs|cjs|ts|sh|zsh|bash|rb|pl|php))"
)
DELETE_MSG = (
    "Deletion guard (owner rule: never auto-approve deletions, scripts included): {what}. "
    "Ask the owner explicitly."
)
# the token pass (0.6.1): the same tools and verbs as the expressions above, read from the command's tokens;
# 0.7.0 adds verbs the expressions never had (docker pairs, podman, nerdctl, pipx, uv, helm repo|plugin)
_RM_CLASS = frozenset("rm rmdir unlink trash shred truncate".split())
_GIT_DELETE_RE = re.compile(GIT_RE)
_DOCKER_DELETE_PAIRS = {
    "system": frozenset({"prune"}), "volume": frozenset({"rm", "prune"}), "image": frozenset({"prune", "rm"}),
    "container": frozenset({"prune", "rm"}), "builder": frozenset({"prune"}), "compose": frozenset({"down", "rm"}),
    "network": frozenset({"rm", "prune"}), "buildx": frozenset({"rm", "prune"}), "context": frozenset({"rm"}),
}
_DOCKER_DELETE = (frozenset({"rm", "rmi"}), _DOCKER_DELETE_PAIRS)
# tool basename -> (verbs, pairs as first word -> second words); pip3.12-style names count as pip
# 0.9.0: the verbs that remove a package or a tool version, empty a download cache or the installed set (the
# offline checks of this kit run from these caches), each from the tool's own help: npm 10 (`prune`, `cache
# clean`), pnpm 9 (`prune`, `store prune`), yarn 1 (`global remove`, `cache clean`), Homebrew 4 (`untap`, `cleanup`,
# `autoremove`), pip 24 (`cache purge|remove`), cargo 1.8x (`remove`), uv 0.5 (`remove`, `cache clean|prune`,
# `python uninstall`); the tools below them are new
_DELETE_TOOLS: dict = {
    "mise": (frozenset({"uninstall", "prune"}), {}),
    "npm": (frozenset({"uninstall", "rm", "un", "r", "unlink", "prune"}), {"cache": frozenset({"clean"})}),
    "pnpm": (frozenset({"remove", "rm", "uninstall", "prune"}), {"store": frozenset({"prune"})}),
    "yarn": (frozenset({"remove"}), {"global": frozenset({"remove"}), "cache": frozenset({"clean"})}),
    "brew": (frozenset({"uninstall", "remove", "rm", "untap", "cleanup", "autoremove"}), {}),
    "pip": (frozenset({"uninstall"}), {"cache": frozenset({"purge", "remove"})}),
    "cargo": (frozenset({"uninstall", "remove", "rm"}), {}),
    "poetry": (frozenset({"remove"}), {"env": frozenset({"remove"}), "cache": frozenset({"clear"})}),  # poetry 1.8
    "conda": (frozenset({"remove", "uninstall", "clean"}), {"env": frozenset({"remove"})}),  # conda 24
    "mamba": (frozenset({"remove", "uninstall", "clean"}), {"env": frozenset({"remove"})}),  # mamba 1.5
    "micromamba": (frozenset({"remove", "uninstall", "clean"}), {"env": frozenset({"remove"})}),
    "gem": (frozenset({"uninstall", "cleanup"}), {}),  # RubyGems 3.5
    "bundle": (frozenset({"remove", "clean"}), {}),  # Bundler 2.5
    "bun": (frozenset({"remove", "rm"}), {}),  # bun 1.1
    "pdm": (frozenset({"remove"}), {"cache": frozenset({"clear", "remove"})}),  # pdm 2
    "pipenv": (frozenset({"uninstall", "clean"}), {}),  # pipenv 2024
    "pyenv": (frozenset({"uninstall"}), {}),  # pyenv 2.4
    "nvm": (frozenset({"uninstall"}), {"cache": frozenset({"clear"})}),  # nvm 0.40
    "fnm": (frozenset({"uninstall"}), {}),  # fnm 1.37
    "volta": (frozenset({"uninstall"}), {}),  # volta 2
    "asdf": (frozenset({"uninstall"}), {"plugin": frozenset({"remove"})}),  # asdf 0.14
    "rustup": (frozenset({"uninstall"}), {"toolchain": frozenset({"uninstall", "remove"}),  # rustup 1.27
                                          "self": frozenset({"uninstall"}), "target": frozenset({"remove"}),
                                          "component": frozenset({"remove"})}),
    "apt-get": (frozenset({"remove", "purge", "autoremove", "autopurge", "clean", "autoclean"}), {}),  # apt 2.6
    "apt": (frozenset({"remove", "purge", "autoremove", "autopurge"}), {}),
    "dnf": (frozenset({"remove", "erase", "autoremove"}), {}),  # dnf 4
    "yum": (frozenset({"remove", "erase", "autoremove"}), {}),
    "apk": (frozenset({"del"}), {}),  # apk-tools 2
    "snap": (frozenset({"remove"}), {}),  # snapd 2.6
    "go": (frozenset({"clean"}), {}),  # go 1.23: only with -modcache (_DELETE_ONLY_WITH)
    "uv": (frozenset({"remove"}), {"pip": frozenset({"uninstall"}), "tool": frozenset({"uninstall"}),
                                   "cache": frozenset({"clean", "prune"}), "python": frozenset({"uninstall"})}),
    "docker": _DOCKER_DELETE,
    "podman": _DOCKER_DELETE,
    "nerdctl": _DOCKER_DELETE,
    "docker-compose": (frozenset({"down", "rm"}), {}),
    "kubectl": (frozenset({"delete"}), {}),
    "helm": (frozenset({"uninstall", "delete"}),
             {"repo": frozenset({"remove", "rm"}), "plugin": frozenset({"uninstall", "remove", "rm"})}),
    "rclone": (frozenset({"delete", "purge", "sync"}), {}),
    "prisma": (frozenset(), {"migrate": frozenset({"reset"})}),
    "pipx": (frozenset({"uninstall", "uninstall-all"}), {}),
}
# a verb of _DELETE_TOOLS that deletes only with one of these options (`go clean` cleans the build output; Go's
# flag package takes one dash or two)
_DELETE_ONLY_WITH = {"go": frozenset({"-modcache", "--modcache"})}
# F27: Go's flag package takes a boolean flag with a value too (`-modcache=true`); strconv.ParseBool reads these
# as false, and any other value (true, 1, T, or one the line does not show) is read as true
_GO_BOOL_FALSE = frozenset({"0", "f", "F", "false", "FALSE", "False"})


def _delete_only_with(name: str, args: list[str]) -> bool:
    """The options of _DELETE_ONLY_WITH for `name` are given: bare, or as `-flag=value` with a value that is not
    false (F27)."""
    flags = _DELETE_ONLY_WITH[name]
    for t in args:
        flag, eq, value = t.partition("=")
        if t in flags or (eq and flag in flags and value not in _GO_BOOL_FALSE):
            return True
    return False


_SWITCH_DISCARDS = frozenset({"--discard-changes", "-f", "--force"})


def _checkout_new_branch(t: str) -> bool:
    """A checkout option that names a new branch: -b, -B (also glued, `-bfeat`), --orphan, -t, --track."""
    return (t.startswith(("-b", "-B")) or t in ("-t", "--track", "--orphan")
            or t.startswith(("--track=", "--orphan=")))


def _git_discards(sub: str, rest: list[str]) -> bool:
    """`git checkout` and `git switch` forms that overwrite uncommitted work: checkout with `-- <path>`, `-f`,
    the operand `.`, or two plain operands (`git checkout <ref> <path…>`) unless an option names a new branch;
    switch with --discard-changes or -f."""
    if sub == "switch":
        return bool(_SWITCH_DISCARDS & set(rest))
    if sub != "checkout":
        return False
    if "-f" in rest or "--force" in rest or "." in rest:
        return True
    if "--" in rest and rest.index("--") + 1 < len(rest):  # `git checkout main --` names no path
        return True
    plain = [t for t in rest if not t.startswith("-")]
    return len(plain) >= 2 and not any(_checkout_new_branch(t) for t in rest)


def _git_push_deletes(sub: str, rest: list[str]) -> bool:
    """`git push` that removes remote branches: -d in a cluster, --delete, --prune (it removes remote branches
    without a local counterpart) or a prefix git takes for one (`--delet`, `--de`) (0.8.0)."""
    if sub != "push":
        return False
    longs, shorts = _git_options(sub, rest)
    return "d" in shorts or _git_prefix(longs, ("delete", "prune"))


def delete_what(command: str) -> Optional[str]:
    """What a command line would delete, read from the tokens of every simple command it runs, or None."""
    for toks in nested_commands(command):
        at_word = command_word_indexes(toks)
        named = 0
        for i, t in enumerate(toks):
            name = tool_name(t)
            if name in _RM_CLASS and i in at_word:
                return f"`{name}` deletes files"
            entry = _DELETE_TOOLS.get("pip" if _PIP_RE.match(name) else name)
            if name != "git" and not entry:
                continue
            named += 1
            if named > _MAX_TOOL_WORDS:  # each call reads the rest of the line: bound the cost, ask instead
                raise CommandNotRead(_TOO_MANY_TOOLS)
            if name == "git":
                sub, rest = _git_subcommand(list(toks[i:]))
                if sub and (_GIT_DELETE_RE.match(" ".join(["git", sub, *rest])) or _git_discards(sub, rest)
                            or _git_push_deletes(sub, rest)):
                    return f"`git {sub}` discards work"
                continue
            hit = subcommand_hit(caps_verbs(name, list(toks[i + 1 :])), *entry)
            if hit and (name not in _DELETE_ONLY_WITH or _delete_only_with(name, list(toks[i + 1 :]))):
                return f"`{name} {hit}` deletes"
    return None


def _truncate_in_the_open(command: str) -> bool:
    """The lower-case word `truncate` in a here-document, or outside quotes: a word of its own in a simple
    command of the line or of a script it nests. There it asks wherever it stands, as before 0.7.0
    (`gtruncate -s 0 f`, `hdfs dfs -truncate 0 /f`, `echo truncate users | pgcli`): prose stands in quotes,
    and no list names every tool that takes the text. The reader of the token pass decides what a word is, so
    an escaped quote, a comment and a `$( … )` inside double quotes are read as the shell reads them."""
    if any(_SQL_TRUNCATE_RE.search(m.group(4)) for m in _HEREDOC_RE.finditer(command)):
        return True
    # the reader takes the here-document bodies out itself (0.8.0); a second strip would read the line after a
    # stripped operator as a body
    return any(_OPEN_WORD_RE.match(t) for toks in nested_commands(command) for t in toks)


_DELETE_HELP = frozenset({"--help", "-h", "--version"})


def _long_dry(t: str) -> Optional[str]:
    """How a long option of git's dry-run family reads (git 2.55 parse-options, measured: a long option may be
    shortened to any unambiguous prefix, `--no-` takes it back): "dry" for `--dry-run` and its prefixes (`--d`,
    `--dry-r`), "wet" for `--no-dry-run` and its prefixes down to `--no-d`, "unplaced" for `--n`, `--no` and
    `--no-` (which negation they mean the line does not show), None for any other word."""
    if len(t) < 3 or not t.startswith("--") or "=" in t:
        return None
    if "--dry-run".startswith(t):
        return "dry"
    if "--no-dry-run".startswith(t):
        return "wet" if len(t) >= len("--no-d") else "unplaced"
    return None


def _git_dry(rest: list[str], flag_shorts: str, value_shorts: str, flag_longs: tuple, value_longs: tuple) -> bool:
    """A git call of the dry-run family (`git clean`, `git worktree prune`) that previews only: the last of
    -n / --dry-run and --no-dry-run wins (git 2.55, measured: `git clean -n --no-dry-run` deletes), and the scan
    stops at `--`. A short cluster ends at a letter of `value_shorts` (its value follows, glued or as the next
    word); the word after a long option of `value_longs` is its value (`--exclude=x` holds it). Any option this
    cannot place reads as no preview: a word of the dry-run family it cannot tell apart, and (F24) any other long
    option or short letter outside the lists, since git takes a unique prefix (`--excl -n` is `--exclude -n`)."""
    dry = False
    skip = False
    for t in rest:
        if skip:
            skip = False
            continue
        if t == "--":
            break
        state = _long_dry(t)
        if state == "unplaced":
            return False
        if state is not None:
            dry = state == "dry"
        elif t.startswith("--"):
            name, glued, _value = t.partition("=")
            if name in value_longs:
                skip = not glued
            elif name not in flag_longs or glued:
                return False
        elif t.startswith("-") and len(t) > 1:
            letters = t[1:]
            for i, c in enumerate(letters):
                if c in value_shorts:
                    skip = i == len(letters) - 1
                    break
                if c not in flag_shorts:
                    return False
                if c == "n":
                    dry = True
    return dry


def _git_clean_dry(rest: list[str]) -> bool:
    """`git clean` with -n or --dry-run (also in a cluster, `-fdn`) that no later --no-dry-run takes back; the
    letters after an `e` in a cluster, and the word after `-e`, are an exclude pattern (`-f -e -n` deletes).
    Options: git-clean(1), git 2.55: -d, -f/--force, -i/--interactive, -n/--dry-run, -q/--quiet,
    -e/--exclude <pattern>, -x, -X."""
    return _git_dry(rest, "dfinqxX", "e", ("--force", "--interactive", "--quiet"), ("--exclude",))


def _restore_index_only(rest: list[str]) -> bool:
    """`git restore` that touches the index only: --staged (or -S) and no word that can mean the work tree.
    git 2.55 parse-options (measured) takes any unambiguous prefix of a long option, so `--w`, `--work`, `--wor`
    are --worktree; `--n`, `--no`, `--no-` and the prefixes of `--no-staged` may take --staged back. The words
    after `--` are paths."""
    staged = False
    for t in rest:
        if t == "--":
            break
        if t.startswith("--"):
            name = t.split("=", 1)[0]
            if len(name) >= 3 and ("--worktree".startswith(name) or "--no-staged".startswith(name)):
                return False
            staged = staged or name == "--staged"
        elif t.startswith("-") and len(t) > 1:
            letters = t[1:].split("s", 1)[0]  # -s takes the source as its value, glued or as the next word
            if "W" in letters:
                return False
            staged = staged or "S" in letters
    return staged


def _delete_preview(toks) -> bool:
    """Group C (decision 3a, rows K2, K4, K5): a simple command that names a deleting tool and deletes nothing:
    `git restore --staged` (the index only), a preview (`git clean -n`, `git worktree prune -n`, `kubectl delete
    --dry-run=client`), or a help probe as the sole argument after the tool and its deleting verb (`rm --help`,
    `git clean -h`, `docker system prune --help`)."""
    toks = list(toks)
    if not toks:
        return False
    name = tool_name(toks[0])
    if toks[-1] in _DELETE_HELP and not any(t.startswith("-") for t in toks[1:-1]):
        if name in _RM_CLASS:
            return len(toks) == 2
        if name == "git":
            return len(toks) == 3
        entry = _DELETE_TOOLS.get(name)
        hit = subcommand_hit(toks[1:-1] + ["x"], *entry) if entry else None
        return bool(hit) and hit.split() == toks[1:-1]
    if name == "git":
        sub, rest = _git_subcommand(toks)
        if sub == "restore":
            return _restore_index_only(rest)
        if sub == "clean":
            return _git_clean_dry(rest)
        if sub == "worktree" and rest[:1] == ["prune"]:
            # git-worktree(1), git 2.55: prune takes -n/--dry-run, -v/--verbose, --expire <time>
            return _git_dry(rest[1:], "nv", "", ("--verbose",), ("--expire",))
        return False
    if name == "kubectl":
        return _dry_run("kubectl", toks[1:])
    return False


def _single_preview(command: str) -> bool:
    """The whole line is one simple command, with nothing nested, that _delete_preview finds harmless: then the
    text pass, which cannot tell a preview, is not asked either. Any other line is read as before."""
    try:
        cmds = nested_commands(command)
    except CommandNotRead:  # an unread line is judged by the passes below, which ask for it
        return False
    return len(cmds) == 1 and _delete_preview(cmds[0])


def _delete_judge(ev: Event) -> Optional[str]:
    """What the command would delete: the text pass, the scan of a script it names, then the token pass."""
    if _single_preview(ev.command):
        return None
    if DELETE_RE.search(ev.command) or (
        _SQL_TRUNCATE_RE.search(ev.command)
        and (_SQL_CLIENT_RE.search(ev.command) or _truncate_in_the_open(ev.command))
    ):
        return "command contains a delete/discard pattern"
    for m in SCRIPT_RE.finditer(ev.command):
        script = m.group(3)
        p = script if os.path.isabs(script) else os.path.join(ev.cwd, script)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            if DELETE_RE.search(content) or DELETE_RE.search(fold_names(content)):  # as written and folded (0.8.0)
                return f"script {script} contains a delete/discard pattern"
        except (OSError, ValueError):
            continue  # not a readable file (missing, a directory, a NUL byte in the name): nothing to scan
    return delete_what(ev.command)  # the reader takes the here-document bodies out itself (0.8.0)


def rule_delete_guard(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event == "PreToolUse" and ev.kind == "worktree":  # 0.10.0: ExitWorktree with action remove
        action = ev.args.get("action")
        if action == "keep":
            return None
        what = ("`ExitWorktree` removes the worktree and its branch" if action == "remove"
                else "`ExitWorktree` with an action the guard cannot read")
        return "ask", DELETE_MSG.format(what=what)
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    pipe = None
    try:
        what = _delete_judge(ev)
        pipe = _PIPE_NOT_READ if _unread_pipe(ev.command) else None  # read past it, asked for with the rest
    except CommandNotRead as exc:  # too deep or too many tools: ask rather than pass it unread
        what = str(exc)
    except Exception as exc:  # main() turns a crash into exit 1, which both harnesses let run silently: ask instead
        what = f"the command could not be read ({type(exc).__name__})"
    return combine([("ask", DELETE_MSG.format(what=w)) for w in (what, pipe) if w])



# ----------------------------------------------------------------------------
# Shell helpers
# ----------------------------------------------------------------------------

_SEP_RE = re.compile(r"\|\||&&|[;|]|\n")
_WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "doas", "builtin"}
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# 0.9.0: Homebrew installs the GNU tools with a `g` in front (`grm`, `gfind`, `gsed`); `g` + one of these names is
# that tool. The names are the file lists of the formulae coreutils 9.5, findutils 4.10, grep 3.11, gnu-sed 4.9,
# gnu-tar 1.35 and gnu-time 1.9. Only these: `gh`, `git`, `go`, `gem`, `grep`, `gzip` and `gdb` are tools of
# their own, and none of them is `g` + a name of this list.
_GNU_NAMES = frozenset(
    "[ b2sum base32 base64 basename basenc cat chcon chgrp chmod chown chroot cksum comm cp csplit cut date dd df"
    " dir dircolors dirname du echo env expand expr factor false fmt fold groups head hostid id install join kill"
    " link ln logname ls md5sum mkdir mkfifo mknod mktemp mv nice nl nohup nproc numfmt od paste pathchk pinky pr"
    " printenv printf ptx pwd readlink realpath rm rmdir runcon seq sha1sum sha224sum sha256sum sha384sum"
    " sha512sum shred shuf sleep sort split stat stdbuf stty sum sync tac tail tee test timeout touch tr true"
    " truncate tsort tty uname unexpand uniq unlink uptime users vdir wc who whoami yes"
    " find xargs locate updatedb grep egrep fgrep sed tar time".split()
)
_GNU_G_NAMES = frozenset("g" + n for n in _GNU_NAMES)


# 0.9.0: these tools take a verb written all in capitals as the verb (`brew UNINSTALL jq`, measured:
# SC semantics4.log); gh, npm, uv, poetry, go, kubectl and pip refuse one, so their verbs are compared as written
_CAPS_VERB_TOOLS = frozenset({"brew", "gem"})


def caps_verbs(name: str, args: list[str]) -> list[str]:
    """The arguments of a call of `name`, with a plain word that holds a capital in lower case when the tool
    takes such a verb (F20: any capitals, measured: `brew Uninstall --help` and `gem Uninstall --help` print the
    help of uninstall); options and every other tool's words stay as written."""
    if name not in _CAPS_VERB_TOOLS:
        return args
    return [t.lower() if t != t.lower() and not t.startswith("-") else t for t in args]


def tool_name(word: str) -> str:
    """The tool a command word names: its basename, with Homebrew's `g` taken off a GNU tool (`grm` -> `rm`)."""
    name = os.path.basename(word)
    return name[1:] if name in _GNU_G_NAMES else name


def tokens(text: str) -> list[str]:
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def segments(command: str) -> list[list[str]]:
    """Token lists for each simple command of a compound line, wrappers and assignments stripped.

    Fresh lists from a memo: five rules read the same line in one hook run, and none can change the cache."""
    return [list(seg) for seg in _segments_cached(command)]


@functools.lru_cache(maxsize=8)
def _segments_cached(command: str) -> tuple[tuple[str, ...], ...]:
    """segments' memo; one index walks past wrappers and options, so a long line costs one pass."""
    out = []
    for part in _SEP_RE.split(command):
        toks = tokens(part)
        i = 0
        while i < len(toks) and (_ASSIGN_RE.match(toks[i]) or toks[i] in _WRAPPERS):
            if toks[i] == "command" and toks[i + 1 : i + 2] in (["-v"], ["-V"]):
                i = len(toks)  # 0.9.0 (K10): `command -v codex` is a lookup and runs nothing, as the reader reads it
                break
            i += 1
            while i < len(toks) and toks[i].startswith("-") and toks[i] != "--":
                i += 1
        if i < len(toks):
            out.append(tuple(toks[i:]))
    return tuple(out)


def _expand(tok: str, cwd: str) -> str:
    t = os.path.expanduser(tok.replace("$HOME", "~"))
    return t if os.path.isabs(t) else os.path.normpath(os.path.join(cwd, t))


# groups: 1 the dash of `<<-`, 2 the quote, 3 the delimiter, 4 the body. 0.8.0: a `<<-` body ends at a closing
# line indented by tabs, as the shell ends it
_HEREDOC_RE = re.compile(
    r"<<(-)?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2[^\n]*\n(.*?)(?:\n(?(1)\t*)\3(?:\n|$)|\Z)", re.DOTALL
)


def strip_heredocs(command: str) -> str:
    """Drop here-document bodies: they are data for a command, not commands (the delete-guard keeps them)."""
    return _HEREDOC_RE.sub(lambda m: m.group(0)[: m.start(4) - m.start(0)], command)


# ----------------------------------------------------------------------------
# Secret-bearing paths (AGENTS.md rule 6: secrets in a vault, never in code, repo or state)
# ----------------------------------------------------------------------------

_SECRET_NAME_RE = re.compile(
    r"^(\.env(\..+)?|.*\.(pem|key|p12|pfx|jks|keystore|tfstate|tfstate\.backup)"
    r"|id_(rsa|dsa|ecdsa|ed25519)|\.netrc|\.pypirc|\.git-credentials)$"
)
_EXAMPLE_RE = re.compile(r"\.(example|sample|template|dist)$")
_TFVARS_RE = re.compile(r"\.tfvars$")
_SECRET_IN_DIR = {
    (".aws", "credentials"): "~/.aws/credentials",
    (".kube", "config"): "~/.kube/config",
    ("gh", "hosts.yml"): "~/.config/gh/hosts.yml",
    (".docker", "config.json"): "~/.docker/config.json",
}
# the directory itself and everything under it: Azure CLI token caches (msal_token_cache.*), service principal
# entries, the azure-devops extension's PAT fallback store; any `.azure` directory, as for the pairs above
_SECRET_DIRS = {".azure"}


def secret_class(path: Optional[str]) -> Optional[str]:
    """'secret' (deny on write, ask on read), 'tfvars' (ask on write), or None: the stricter class of the path
    as written and of the path in lower case, secret over tfvars over none (0.8.0). A file system that ignores
    case opens `.env` for `.ENV`; `.env.EXAMPLE` keeps asking (as written a secret name), `.ENV.EXAMPLE` is an
    example file, and `~/.AZURE/prod.tfvars` is in a secret directory."""
    cls = _secret_class_as_written(path)
    if cls != "secret" and path and path != path.lower():
        lower = _secret_class_as_written(path.lower())
        if lower == "secret" or cls is None:  # the stricter of the two readings: secret over tfvars over none
            cls = lower
    return cls


def _secret_class_as_written(path: Optional[str]) -> Optional[str]:
    """secret_class for the path exactly as given (the tables compare case)."""
    if not path:
        return None
    base = os.path.basename(path.rstrip("/"))
    parent = os.path.basename(os.path.dirname(path))
    if _EXAMPLE_RE.search(base):
        return None
    if (parent, base) in _SECRET_IN_DIR:
        return "secret"
    if _SECRET_DIRS.intersection(path.replace("\\", "/").split("/")):
        return "secret"
    if _SECRET_NAME_RE.match(base):
        return "secret"
    if _TFVARS_RE.search(base):
        return "tfvars"
    return None


SECRET_WRITE_MSG = (
    "Secret boundary (AGENTS.md rule 6): {path} is a secret-bearing file; it is never written by the agent. "
    "Keep values in the vault or the environment; a *.example with names only is fine."
)
SECRET_READ_MSG = (
    "Secret boundary (AGENTS.md rule 6): {path} may hold credentials. Confirm this read is intended; "
    "prefer names-only samples or redacted copies."
)
TFVARS_MSG = (
    "{path} is a tfvars file; such files often carry secrets. "
    "Confirm it holds no secret values before editing."
)


def rule_secret_write(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind not in ("write", "edit"):
        return None
    cls = secret_class(ev.abspath())
    if cls == "secret":
        return "deny", SECRET_WRITE_MSG.format(path=ev.path)
    if cls == "tfvars":
        return "ask", TFVARS_MSG.format(path=ev.path)
    return None


def rule_secret_read(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "read":
        return None
    if github_login_file(ev.abspath()):
        return "deny", GITHUB_LOGIN_MSG.format(rule="secret-read", what=f"`{ev.tool}` of {ev.path}")
    if secret_class(ev.abspath()) == "secret":
        return "ask", SECRET_READ_MSG.format(path=ev.path)
    return None


_REDIRECT_RE = re.compile(r"(?<![<>])>{1,2}\s*([^\s;&|]+)")
_WRITERS_LAST = {"cp", "mv", "install", "scp", "rsync", "ln"}
_WRITERS_ALL = {"tee", "truncate", "touch", "chmod", "chown"}


# options whose value is a pattern to leave out or to match, not a file that is read (the manuals of tar, rsync,
# grep, rg, fd, ag, git ls-files): `tar --exclude=.env` stays silent
_PATTERN_VALUE_OPTIONS = frozenset("--exclude --exclude-dir --exclude-from --include --glob --iglob --ignore"
                                   " --filter".split())
# 0.9.0 (K8): the options whose value, in the next word, is a name to leave out; an option that selects the files
# a tool reads (`--include`, `--glob`) or names a file it reads (`--exclude-from`) names a path
_EXCLUDE_VALUE_OPTIONS = frozenset({"--exclude", "--exclude-dir"})
# the reader marks an unquoted input redirection `<` with \x01 (_hi_prepare), so a quoted `'<.env'` is none:
# `<f`, `0<f`, `<>f` (read and write); not `<<`, `<<<`, `<&3`, `<(…)`
_INPUT_REDIRECT_RE = re.compile(r"^\d*<\x01>?(\S+)$")
_BARE_INPUT_RE = re.compile(r"^\d*<\x01>?$")  # `< f`: the file is the next word


def _path_candidates(t: str) -> list[str]:
    """The paths one argument word can name (0.8.0): the bare word; the value of `--name=value` or `-n=value`
    unless the option names a pattern; the rest of a short option glued to its value (`-T.env`, `-d@.env`);
    the path behind `@` (`@f`, `name@f`, `name=@f`, `;type=…` cut off: curl, httpie). A word with `://` is a
    URL and is read as before: the bare word only."""
    if "://" in t:
        return [] if t.startswith("-") else [t]
    if t.startswith("-"):
        name, eq, value = t.partition("=")
        if eq:
            if name in _PATTERN_VALUE_OPTIONS:
                return []
            word = value
        elif t.startswith("--") or len(t) < 3:
            return []
        else:
            word = t[2:]
    else:
        word = t
    out = [word]
    _name, at, path = word.partition("@")
    if at and path:
        out.append(path.split(";", 1)[0].strip("\"'"))  # curl takes a quoted name too: `file=@".env"` (0.8.0)
    return out


def _secret_reads(seg: list[str], cwd: str, skip: list[str]) -> list[str]:
    """The secret files the argument words of one simple command name, past those in `skip` (written ones)."""
    out = []
    for k, t in enumerate(seg[1:], 1):
        if seg[k - 1] in _EXCLUDE_VALUE_OPTIONS:  # 0.9.0 (K8): `tar --exclude .env`, the value in the next word
            continue
        for p in _path_candidates(t):
            if p and p not in skip and secret_class(_expand(p, cwd)) == "secret":
                out.append(p)
    return out


def _secret_seg(seg: list[str], cwd: str, writes: list[str], reads: list[str]) -> None:
    """Add the secret files one simple command writes and reads to the two lists."""
    head = tool_name(seg[0])
    paths = [t for t in seg[1:] if not t.startswith("-") and t != "--"]
    targets: list[str] = []
    if head in _WRITERS_LAST and paths:
        targets = paths[-1:]
    elif head in _WRITERS_ALL:
        targets = paths
    elif head == "sed" and any(t.startswith("-i") for t in seg):
        targets = paths
    elif head == "git":
        sub, rest = _git_subcommand(seg)  # past git's own options: `git -C sub add .env` (0.8.0)
        if sub in ("add", "stage"):
            targets = [t for t in rest if not t.startswith("-") and t != "--"]
    for t in targets:
        if secret_class(_expand(t, cwd)) == "secret":
            writes.append(t)
    reads.extend(_secret_reads(seg, cwd, targets))


_SEARCH_TOOLS = frozenset("grep egrep fgrep zgrep rg ag ack".split())
_PATTERN_OPTIONS = ("-e", "--regexp", "-f", "--file")  # these name the pattern; no operand is one then


def _search_pattern(seg: list[str], k: int) -> tuple[Optional[int], list[str]]:
    """For the search tool at seg[k] (grep and kin, `git grep`): the index of its pattern operand, or None when
    -e, --regexp, -f or --file names the pattern (also glued, with `=`, or among other short options as in
    `-rnf`), and the glued values of -f/--file (files it reads). The pattern is the first word that is not an
    option; an option's value taken for it (`-A 3`) leaves the real pattern read as a path, which errs towards
    asking."""
    name = tool_name(seg[k])
    start = k + 1
    if name == "git":
        sub, rest = _git_subcommand(seg[k:])
        if sub != "grep":
            return None, []
        start = len(seg) - len(rest)
    elif name not in _SEARCH_TOOLS:
        return None, []
    named = False
    files = []
    for t in seg[start:]:
        if t in _PATTERN_OPTIONS:
            named = True
        elif t.startswith(("--regexp=", "--file=")):
            named = True
            if t.startswith("--file="):
                files.append(t[len("--file=") :])
        elif t.startswith("-") and not t.startswith("--"):
            # short options in one word (`-rnf`): the first e or f names the pattern, the text after an f is its file
            at = min((n for n in (t.find("e"), t.find("f")) if n > 0), default=0)
            if at:
                named = True
                if t[at] == "f" and t[at + 1 :]:
                    files.append(t[at + 1 :])
    if named:
        return None, files
    table = _SEARCH_OPTIONS.get("grep" if name in ("egrep", "fgrep", "zgrep") else name)
    value_next = False  # 0.9.0: the word after an option that takes a value is that value, not the pattern
    for m in range(start, len(seg)):
        t = seg[m]
        if value_next:
            value_next = False
            continue
        if t == "--":  # grep: the pattern follows; git grep: paths follow, the pattern came before
            return (m + 1 if name != "git" and m + 1 < len(seg) else None), files
        if not t.startswith("-") or t == "-":
            return m, files
        reading = _search_option(t, table) if table else "unknown"
        if reading == "unknown":  # F22: what it takes is not known, so neither is the pattern (as 0.8.0)
            return None, files
        value_next = reading == "next"
    return None, files


class _SearchTable:
    """The options of one search tool: short letters and long names that take no value (flags; an option whose
    value can only be glued, `--color[=WHEN]`, is one), short letters and long names that take a value (glued
    or the next word), and short letters whose optional value can only be glued (git grep -O)."""

    def __init__(self, flag_shorts: str, value_shorts: str, flag_longs: str, value_longs: str,
                 glued_shorts: str = "", glued_longs: str = "") -> None:
        self.flag_shorts = flag_shorts
        self.value_shorts = value_shorts
        self.glued_shorts = glued_shorts
        self.flag_longs = frozenset(flag_longs.split())
        self.value_longs = frozenset(value_longs.split())
        # long options known with a glued value only; written bare, the tools read them two ways
        self.glued_longs = frozenset(glued_longs.split())


# Fix pass, F22: three readings of an option, not two. Sources: each tool's own --help, as listed in the fix
# order's options.tsv: ripgrep 15, GNU grep 3.12 (`ggrep`, also for grep, egrep, fgrep, zgrep), git grep 2.55. An
# option in neither list (a newer flag, a unique prefix such as `--no-mess`, a flag of the BSD grep of macOS such as
# -S) leaves the pattern of the call unknown: no word is left out of the secret check, no pattern is protected for
# egress-guard (what 0.8.0 did). For ag and ack the order holds no help text: the flags of the 0.9.0 build stay
# (the silver searcher 2.2, ack 3.7) and no value option is known, so any other option leaves the pattern unknown.
_SEARCH_OPTIONS: dict = {
    "grep": _SearchTable(
        "EFGPiwxzsvVbnHhoqaIrRLlcTZU0123456789", "efmdDBAC",
        "--extended-regexp --fixed-strings --basic-regexp --perl-regexp --ignore-case --no-ignore-case"
        " --word-regexp --line-regexp --null-data --no-messages --invert-match --version --help --byte-offset"
        " --line-number --line-buffered --with-filename --no-filename --only-matching --quiet --silent --text"
        " --recursive --dereference-recursive --files-without-match --files-with-matches --count --initial-tab"
        " --null --no-group-separator --binary --color --colour",
        "--regexp --file --max-count --label --binary-files --directories --devices --include --exclude"
        " --exclude-from --exclude-dir --before-context --after-context --group-separator",
        # F25: GNU grep 3.12 takes `--context NUM`, the BSD grep 2.6.0 of macOS only `--context[=num]` (the next
        # word is its pattern, measured): bare, the pattern is not known
        glued_longs="--context"),
    "rg": _SearchTable(
        "zsFivxUPSawLubhnN0opqHIclV", "efEmjgdtTABCMr",
        "--search-zip --case-sensitive --crlf --fixed-strings --ignore-case --invert-match --line-regexp --mmap"
        " --multiline --multiline-dotall --no-unicode --null-data --pcre2 --smart-case --stop-on-nonmatch --text"
        " --word-regexp --auto-hybrid-regex --no-pcre2-unicode --binary --follow --glob-case-insensitive --hidden"
        " --ignore-file-case-insensitive --no-ignore --no-ignore-dot --no-ignore-exclude --no-ignore-files"
        " --no-ignore-global --no-ignore-parent --no-ignore-vcs --no-require-git --one-file-system --unrestricted"
        " --block-buffered --byte-offset --column --heading --help --include-zero --line-buffered --line-number"
        " --no-line-number --max-columns-preview --null --only-matching --passthru --pretty --quiet --trim"
        " --vimgrep --with-filename --no-filename --sort-files --count --count-matches --files-with-matches"
        " --files-without-match --json --debug --no-ignore-messages --no-messages --stats --trace --files"
        " --no-config --pcre2-version --type-list --version",
        "--regexp --file --pre --pre-glob --dfa-size-limit --encoding --engine --max-count --regex-size-limit"
        " --threads --glob --iglob --ignore-file --max-depth --max-filesize --type --type-not --type-add"
        " --type-clear --after-context --before-context --color --colors --context --context-separator"
        " --field-context-separator --field-match-separator --hostname-bin --hyperlink-format --max-columns"
        " --path-separator --replace --sort --sortr --generate"),
    "git": _SearchTable(
        "viwaIrEGFPnhHlLzocpWq0123456789", "CBAfem",
        "--cached --no-cached --no-index --index --untracked --no-untracked --exclude-standard"
        " --no-exclude-standard --recurse-submodules --no-recurse-submodules --invert-match --no-invert-match"
        " --ignore-case --no-ignore-case --word-regexp --no-word-regexp --text --no-text --textconv --no-textconv"
        " --recursive --no-recursive --extended-regexp --no-extended-regexp --basic-regexp --no-basic-regexp"
        " --fixed-strings --no-fixed-strings --perl-regexp --no-perl-regexp --line-number --no-line-number"
        " --column --no-column --full-name --no-full-name --files-with-matches --no-files-with-matches"
        " --name-only --no-name-only --files-without-match --no-files-without-match --null --no-null"
        " --only-matching --no-only-matching --count --no-count --break --no-break --heading --no-heading"
        " --show-function --no-show-function --function-context --no-function-context --and --or --not --quiet"
        " --no-quiet --all-match --no-all-match --ext-grep --no-ext-grep"
        # optional values, glued only (`--[no-]color[=<when>]`, `--[no-]open-files-in-pager[=<pager>]`), and the
        # negations of options with a value, which take none (git parse-options: `--[no-]context <n>`)
        " --color --no-color --open-files-in-pager --no-open-files-in-pager --no-context --no-threads"
        " --no-max-count",
        "--max-depth --context --before-context --after-context --threads --max-count",
        glued_shorts="O"),
    "ag": _SearchTable(
        "acfHilLnQsStuUvwz0", "",
        "--hidden --literal --nocolor --case-sensitive --smart-case --files-with-matches --files-without-matches"
        " --follow --skip-vcs-ignores --unrestricted --search-binary --stats --nobreak --noheading --heading"
        " --column --numbers --nonumbers --vimgrep --one-device --search-zip --print-long-lines --filename"
        " --nofilename --all-types --all-text --print0 --silent --ignore-case --word-regexp --invert-match"
        " --count --version --help",
        ""),
    "ack": _SearchTable(
        "cfhHiIlLnosvwx1", "",
        "--smart-case --nocolor --nocolour --column --nocolumn --heading --noheading --break --nobreak --group"
        " --nogroup --follow --nofollow --flush --literal --passthru --print0 --sort-files --show-types --noenv"
        " --nopager --known-types --nofilter --ignore-case --word-regexp --invert-match --count --version --help",
        ""),
}


def _search_option(t: str, table: _SearchTable) -> str:
    """How a search tool reads one option word: "flag" (passed over; also any option whose value is glued to it,
    `--color=always`, `-A3`, `-rnA3`), "next" (its value is the next word: `-A 3`, `-rnA 3`, `--glob x`), or
    "unknown" (an option, or a letter of a short cluster, in neither list)."""
    if t.startswith("--"):
        name, glued, _value = t.partition("=")
        if name in table.glued_longs:
            return "flag" if glued else "unknown"
        if name in table.value_longs:
            return "flag" if glued else "next"
        return "flag" if name in table.flag_longs else "unknown"
    for n, c in enumerate(t[1:], 1):
        if c in table.flag_shorts:
            continue
        if c in table.glued_shorts:
            return "flag"
        if c in table.value_shorts:
            return "next" if n == len(t) - 1 else "flag"
        return "unknown"
    return "flag"


def _secret_reader_seg(seg: list[str], cwd: str, writes: list[str], reads: list[str]) -> None:
    """The reader pass of secret-shell: _secret_seg without the pattern operand of a search tool at any
    command word of the words, plus the files a glued -f/--file reads."""
    drop = set()
    if any(tool_name(t) in _SEARCH_TOOLS or os.path.basename(t) == "git" for t in seg):
        for k in command_word_indexes(seg):
            pattern, files = _search_pattern(seg, k)
            if pattern is not None:
                drop.add(pattern)
            reads.extend(f for f in files if secret_class(_expand(f, cwd)) == "secret")
    _secret_seg([t for m, t in enumerate(seg) if m not in drop], cwd, writes, reads)


def _secret_verdict(writes: list[str], reads: list[str], cwd: str = "/") -> Optional[Decision]:
    if writes:
        return "deny", SECRET_WRITE_MSG.format(path=", ".join(dict.fromkeys(writes)))
    login = [p for p in reads if github_login_file(_expand(p, cwd))]
    if login:
        return "deny", GITHUB_LOGIN_MSG.format(rule="secret-shell", what=f"a read of {', '.join(dict.fromkeys(login))}")
    if reads:
        return "ask", SECRET_READ_MSG.format(path=", ".join(dict.fromkeys(reads)))
    return None


# 0.9.0 (decision af): commands that print a stored secret. Tool -> (leading words, condition on the arguments);
# a leading word is a string or a predicate, found past the tool's options as subcommand_hit finds a verb. The
# list, status and metadata calls of the same tools stay silent. Sources: the CLIs' own help: HashiCorp Vault
# 1.17, 1Password CLI 2, kubectl 1.31, gh 2.6x, AWS CLI v2, gcloud 49x, macOS security(1), pass 1.7, Doppler CLI
# 3, sops 3.9, ansible-vault 2.17; az and git are read by their own functions below.
_KUBECTL_QUIET_OUTPUT = frozenset({"name", "wide"})  # these print no secret data


def _has(*names: str) -> Callable[[list[str]], bool]:
    """A condition: one of these options is given, bare or with a value (`--fields x`, `--fields=x`)."""
    return lambda args: any(t in names or t.split("=", 1)[0] in names for t in args)


def _short_has(letters: str) -> Callable[[list[str]], bool]:
    """A condition: one of these short options is given, alone or in a cluster (`-w`, `-ws`: security(1), macOS
    15, takes its short options in one word; F06)."""
    return lambda args: any(t.startswith("-") and not t.startswith("--") and any(c in letters for c in t[1:])
                            for t in args)


def _kubectl_raw_secrets(args: list[str]) -> bool:
    """`kubectl get --raw PATH` with a path of the secrets API (F06: `--raw` asks the API path; kubectl 1.36)."""
    for k, t in enumerate(args):
        if t == "--raw":
            value = args[k + 1] if k + 1 < len(args) else ""
        elif t.startswith("--raw="):
            value = t[len("--raw=") :]
        else:
            continue
        return "secret" in value.lower()
    return False


# Doppler CLI 3 (`doppler secrets --help`): the verbs under `secrets`; with none, `doppler secrets` prints the
# names and values (Doppler's docs, "Names and values"), with --only-names the names only (F06)
_DOPPLER_SECRETS_VERBS = frozenset("get set upload download delete substitute notes".split())


def _doppler_secrets_bare(args: list[str]) -> bool:
    """`doppler secrets` with no verb after it (an option's value is no verb) and without --only-names."""
    if _has("--only-names")(args):
        return False
    rest = args[args.index("secrets") + 1 :] if "secrets" in args else []
    return not any(t in _DOPPLER_SECRETS_VERBS for t in rest if not t.startswith("-"))


def _kubectl_output(args: list[str]) -> bool:
    """kubectl prints the data of the objects: an output format other than name and wide (`-o yaml`, `-ojson`,
    `--output=jsonpath=…`), or a Go template (`--template=…`, F06)."""
    if _has("--template")(args):
        return True
    for k, t in enumerate(args):
        if t in ("-o", "--output"):
            value = args[k + 1] if k + 1 < len(args) else ""
        elif t.startswith("--output="):
            value = t[len("--output=") :]
        elif t.startswith("-o") and not t.startswith("--"):
            value = t[2:].lstrip("=")
        else:
            continue
        return value.split("=", 1)[0] not in _KUBECTL_QUIET_OUTPUT
    return False


def _names_secret(word: str) -> bool:
    """A kubectl resource word that names secrets: `secret`, `secrets/app`, `pods,secrets`; F06: in any case
    (`Secret`, `SECRETS`) and with its version or group (`secret.v1`), as kubectl 1.36 reads them."""
    return any(r.split("/", 1)[0].lower().split(".", 1)[0] in ("secret", "secrets") for r in word.split(","))


_SECRET_STORES: dict = {
    "vault": [(("kv", "get"), None), (("read",), None)],
    # F06: every `op item get` of an item asks (the table of docs/HANDOVER-2026-11-17.md)
    "op": [(("read",), None), (("inject",), None), (("item", "get"), None)],
    "kubectl": [(("get", _names_secret), _kubectl_output), (("get",), _kubectl_raw_secrets),
                (("config", "view"), _has("--raw", "--flatten"))],
    "gh": [(("auth", "token"), None), (("auth", "status"), _has("--show-token", "-t"))],
    "aws": [(("secretsmanager", "get-secret-value"), None), (("secretsmanager", "batch-get-secret-value"), None),
            (("ssm", "get-parameter"), _has("--with-decryption")),
            (("ssm", "get-parameters"), _has("--with-decryption")),
            (("ssm", "get-parameters-by-path"), _has("--with-decryption")),
            (("configure", "export-credentials"), None),
            # F06: also the dotted names of the same value (`default.aws_secret_access_key`, `profile.p.…`)
            (("configure", "get", lambda w: w.lower().rsplit(".", 1)[-1] in ("aws_secret_access_key",
                                                                          "aws_session_token")), None),
            (("ecr", "get-login-password"), None), (("sts", "get-session-token"), None)],
    "gcloud": [(("secrets", "versions", "access"), None), (("auth", "print-access-token"), None),
               (("auth", "print-identity-token"), None),
               (("auth", "application-default", "print-access-token"), None)],
    "security": [(("find-generic-password",), _short_has("wg")), (("find-internet-password",), _short_has("wg")),
                 (("dump-keychain",), _short_has("d"))],
    "pass": [(("show",), None), (("otp",), None), (("grep",), None)],
    "doppler": [(("secrets", "get"), None), (("secrets", "download"), None), (("secrets",), _doppler_secrets_bare)],
    "sops": [(("decrypt",), None)],
    "ansible-vault": [(("view",), None), (("decrypt",), None)],
}
# a pass(1) word that is a subcommand; any other first word is the name of an entry, and `pass NAME` shows it
_PASS_SUBS = frozenset("init ls list find search show insert add edit generate rm remove delete mv rename cp copy git"
                       " help version grep otp".split())
# az: the last leading words of a call that prints a secret (Azure CLI 2.6x reference)
_AZ_SECRET_TAILS = (("keyvault", "secret", "show"), ("keyvault", "secret", "download"), ("account", "get-access-token"),
                    ("keys", "list"), ("show-connection-string",), ("credential", "show"),
                    ("list-publishing-profiles",), ("list-publishing-credentials",))


def _leading(args: list[str], words: tuple) -> bool:
    """The arguments start with these words past the options; a plain word after an option without `=` may be its
    value and is skipped once (subcommand_hit's rule)."""
    k = 0
    may_be_value = False
    for t in args:
        if k == len(words):
            return True
        if t == "--":
            return False
        if t.startswith("-") and len(t) > 1:
            may_be_value = "=" not in t
            continue
        want = words[k]
        if (t == want) if isinstance(want, str) else want(t):
            k, may_be_value = k + 1, False
            continue
        if not may_be_value:
            return False
        may_be_value = False
    return k == len(words)


def secret_store_what(seg: list[str]) -> Optional[str]:
    """The call when one simple command prints a stored secret (`vault kv get`, `gh auth token`), or None."""
    head = tool_name(seg[0])
    args = drop_redirections(seg[1:])
    if head == "git":
        sub, rest = _git_subcommand(seg)
        if (sub == "credential" and "fill" in rest) or (sub and sub.startswith("credential-") and "get" in rest):
            return f"`git {sub}` prints a stored credential"
        return None
    if head == "az":
        lead = tuple(_az_leading_words(args))
        if not _help_probe(args) and any(lead[-len(tail) :] == tail for tail in _AZ_SECRET_TAILS):
            return f"`az {' '.join(lead)}` prints a secret"
        return None
    if head == "sops" and ("-d" in args or "--decrypt" in args):
        return "`sops --decrypt` prints the plaintext"
    if head == "pass":
        first = next((t for t in args if not t.startswith("-")), None)
        if first is not None and first not in _PASS_SUBS:
            return "`pass NAME` prints a stored password"
    # F04: under `gh auth`, -h is --hostname, no help word (`gh auth token --help`, gh 2.92.0)
    if _help_probe([t for t in args if t != "-h"] if head == "gh" and _leading(args, ("auth",)) else args):
        return None
    for words, cond in _SECRET_STORES.get(head, ()):
        if _leading(args, words) and (cond is None or cond(args)):
            shown = " ".join(w for w in words if isinstance(w, str))
            return f"`{head} {shown}` prints a stored secret"
    return None


# 0.10.0 (item #65, D8): the owner's stored GitHub login is read by no session; these deny (some asked at 0.9.0)
GITHUB_LOGIN_MSG = ("{rule}: {what} reads stored credentials (a keychain item, a credential helper or the owner's "
                    "stored GitHub login); a session never does (plan rev 3, D6).")
_GITHUB_LOGIN_SUFFIXES = ("/.config/gh/hosts.yml", "/.git-credentials")
_GITHUB_TOKEN_VARS = frozenset({"GH_TOKEN", "GITHUB_TOKEN"})
_EMPTY_TOKEN_RE = re.compile(
    r"(?:^|[;&|(`\n])\s*(?:export\s+|env\s+(?:-\S+\s+)*)?(?:[A-Za-z_]\w*=\S*\s+)*(GH_TOKEN|GITHUB_TOKEN)="
    r"(?:\"\"|''|)(?=[\s;&|)]|$)")


def github_login_file(path: Optional[str]) -> bool:
    """The file of the owner's stored GitHub login (gh's hosts.yml, git's store helper), matched by its end."""
    return bool(path) and ("/" + path.replace("\\", "/").lower().lstrip("/")).endswith(_GITHUB_LOGIN_SUFFIXES)


def _env_runs(args: list[str]) -> list[str]:
    """The command `env` runs: its arguments past options and assignments."""
    k = 0
    while k < len(args) and (args[k].startswith("-") or _ASSIGN_RE.match(args[k])):
        k += 2 if args[k] in ("-u", "--unset", "-C", "--chdir", "-S", "--split-string") else 1
    return args[k:]


def github_login_what(seg: list[str]) -> Optional[str]:
    """The call when one simple command reads or drops the owner's stored GitHub login, or None."""
    head = tool_name(seg[0])
    args = drop_redirections(seg[1:])
    if head == "gh" and "--help" not in args:
        if _leading(args, ("auth", "token")):
            return "`gh auth token`"
        if _leading(args, ("auth", "status")) and _has("--show-token", "-t")(args):
            return "`gh auth status --show-token`"
    if head == "git":
        sub, rest = _git_subcommand(seg)
        if sub == "credential" and ("fill" in rest or "approve" in rest):
            return "`git credential " + ("fill`" if "fill" in rest else "approve`")
        if sub and sub.startswith("credential-") and "get" in rest:
            return f"`git {sub} get`"
    if head == "security":
        if _leading(args, ("dump-keychain",)):
            return "`security dump-keychain`"
        for verb in ("find-generic-password", "find-internet-password"):
            if _leading(args, (verb,)) and _short_has("wg")(args):
                return f"`security {verb}` with the secret shown"
    if head == "unset" and _GITHUB_TOKEN_VARS.intersection(args):
        return "`unset GH_TOKEN` (the session's own login gone, gh falls back to the stored one)"
    if head == "env":
        for k, t in enumerate(args):
            name = args[k + 1] if t in ("-u", "--unset") and k + 1 < len(args) else (
                t.split("=", 1)[1] if t.startswith("--unset=") else t[2:] if t.startswith("-u") else "")
            if name in _GITHUB_TOKEN_VARS:
                return f"`env -u {name}` (gh and git fall back to the stored login)"
        if any(t in ("-i", "--ignore-environment", "-") for t in args):
            run = _env_runs(args)
            names = [os.path.basename(run[0])] if run else []
            if run and os.path.basename(run[0]) in _NC_SHELLS and "-c" in run[1:-1]:
                names = [os.path.basename(s[0]) for s in segments(run[run.index("-c", 1) + 1])]
            if any(n in ("gh", "git") for n in names):
                return "`env -i` in front of gh or git (they fall back to the stored login)"
    return None


SECRET_STORE_MSG = ("secret-shell: {what}. A secret printed into the session leaves the vault; confirm the command "
                    "(AGENTS.md: secrets stay in the vault).")


# 0.9.0, group C (K6, K7, K9): commands that name a secret path and read nothing of it: they print their words,
# list or test the file, or report git's view of the name
_REPORT_HEADS = frozenset({"echo", "printf", "ls", "stat", "test", "[", "[["})
_REPORT_GIT_SUBS = frozenset({"check-ignore", "ls-files", "status"})
# second fix round: a separator is read by its characters; without spaces and line breaks these are plain, any
# other (`|`, `|&`, an operator the check does not know) hands the output on
_PLAIN_SEPS = frozenset({"", ";", "&&", "||", "&"})


def _report_words(toks) -> tuple:
    """The words of a simple command without leading assignments and shell words and without redirections: the
    form both passes of secret-shell compare."""
    words = drop_redirections(list(toks))
    k = 0
    while k < len(words) and (_ASSIGN_RE.match(words[k]) or words[k] in _NC_SHELL_WORDS):
        k += 1
    return tuple(words[k:])


# fifth fix round: `$_` in any spelling of a parameter expansion (`${_:-x}`, `${_%y}`)
_LAST_ARG_RE = re.compile(r"\$_(?![A-Za-z0-9_])|\$\{[^}]*(?<![A-Za-z0-9_])_(?![A-Za-z0-9_])")
_COMPOUND_OPENERS = frozenset({"{", "if", "while", "until", "for", "case", "select"})
_COMPOUND_CLOSERS = frozenset({"}", "fi", "done", "esac"})


_GROUP_CLOSER = {"{": "}", "if": "fi", "while": "done", "until": "done", "for": "done", "select": "done"}
# fifth fix round: the quiet reading is strict; a line it cannot read with certainty has no quiet report.
# In `$[…]` a quote is no quote for the shell, and a character of the private plane would pass for a quoted one.
# (`$'…'`, whose escapes the lexer does not know, and `$((…))` are turned down where the quotes are read.)
# sixth fix round: a carriage return is a blank for the lexer and a plain character for the shell (`}\r` closes
# nothing there)
_QUIET_UNREAD_RE = re.compile("\\$\\[|\r|[\U000f0000-\U000ffffd]")
# sixth fix round: a report's name written with a path is the report only in a system folder (`./ls`, `script/test`
# are other programs)
_REPORT_DIRS = frozenset({"/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"})
# sixth fix round: what the first argument of a quiet `printf` may hold outside quotes; anything else a shell could
# expand to the option `-v` (a parameter, braces, a pattern, a tilde). A backslash is left in a masked word only
# inside double quotes.
_PRINTF_PLAIN_RE = re.compile("[A-Za-z0-9%_./:,+@=\\\\\U000f0000-\U000ffffd-]*")
_QUOTED_OFFSET = 0xF0000
_QUOTE_MARK = "\U000ffffd"  # behind every opening quote: a word with an empty quoted part (`{''`) is no bare word
_BRACKET_WORDS = frozenset({"{", "}", "[", "]", "[[", "]]"})


def _plain_sep(sep: str) -> bool:
    """The lexer's separator hands no output on: read by its characters, never compared whole (`|⏎` is a pipe)."""
    return sep.replace(" ", "").replace("\n", "") in _PLAIN_SEPS


def _quoted_char(c: str) -> str:
    return chr(ord(c) + _QUOTED_OFFSET) if c and ord(c) < 0xFFFD else c


# sixth fix round: `case` is a word by its neighbours, not by blanks (`$(true;case x in x) …)`): the `)` of its
# pattern does not end the substitution
_CASE_WORD_RE = re.compile(r"(?<![A-Za-z0-9_])case(?![A-Za-z0-9_])")


def _quiet_sub_end(text: str, i: int) -> Optional[int]:
    """Index of the character that closes the substitution opened at text[i] inside a double-quoted string, or
    None when the check cannot tell where the shell ends it. A backtick ends at the next backtick that is not
    escaped. `$(` ends at the first `)` when the body up to it holds no bracket, backtick, `${`, `$'` or `case`
    (a word by its neighbours, not by blanks: `$(true;case x in x) …)`, sixth fix round), no `#` outside
    quotes, and quotes that pair up: then that `)` is quoted for no shell. (A here-document, which could hide it
    too, is turned down for the whole line.)"""
    if text[i] == "`":
        j = i + 1
        while j < len(text):
            if text[j] == "`":
                return j
            j += 2 if text[j] == "\\" else 1
        return None
    end = text.find(")", i + 2)
    body = text[i + 2 : max(end, 0)]
    if end < 0 or any(x in body for x in ("(", "`", "${", "$'")) or _CASE_WORD_RE.search(body):
        return None
    quote = ""
    k = 0
    while k < len(body):
        c = body[k]
        if c == "\\" and quote != "'":
            if k + 1 >= len(body):
                return None  # the `)` itself is escaped
            k += 2
            continue
        if quote:
            quote = "" if c == quote else quote
        elif c in "'\"":
            quote = c
        elif c == "#":
            return None
        k += 1
    return None if quote else end


def _quiet_mask(text: str) -> Optional[str]:
    """The prepared line with every quoted or escaped character moved to the private plane, by the lexer's own
    quoting rules: a brace, a bracket or a reserved word the line spells with a quote or a backslash (`'{'`, `\\}`,
    `"fi"`) is then none for the check, as it is none for the shell. The lexer takes a quote inside a substitution
    of a double-quoted string for the string's own (`"$(grep -c "x" f)"`); the check lets that stand only where
    it shows the lexer no separator and the string ends for the lexer where it ends for the shell. None for any
    other such substitution, and when a double-quoted string ends inside a `${`: the shell reads on to the `}`,
    the lexer stops at the quote (`"${X:-"a"}"`)."""
    out: list[str] = []
    quote = ""
    depth = 0
    sub_end = -1  # the last character of the substitution at hand
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if i == sub_end and quote != '"':
            return None  # the lexer is not back in the string where the shell ends the substitution
        if quote == '"' and i > sub_end and (c == "`" or (c == "$" and text[i + 1 : i + 2] == "(")):
            end = _quiet_sub_end(text, i)
            if end is None:
                return None
            sub_end = end
        if c == "\\" and quote != "'":
            nxt = text[i + 1 : i + 2]
            # inside "…" the lexer takes the backslash off `\"` and `\\` only; these two stay as they are
            out.append(c + (nxt if quote and nxt in ('"', "\\") else _quoted_char(nxt)))
            i += 2
            continue
        if not quote and i <= sub_end and c in _HI_PUNCT:
            return None  # a separator of the lexer inside the substitution, where the shell has none
        if quote:
            if c == quote:
                if depth:
                    return None
                quote = ""
                out.append(c)
            else:
                if quote == '"' and c == "$" and text[i + 1 : i + 2] == "{":
                    depth += 1
                elif quote == '"' and c == "}" and depth:
                    depth -= 1
                out.append(_quoted_char(c))
        else:
            if c in "'\"":
                if c == "'" and out and out[-1] == "$":
                    return None  # `$'…'`: its escapes (`\\'`) are none for the lexer. `'^a$'` ends a string and stays
                quote, depth = c, 0
                c += _QUOTE_MARK
            out.append(c)
        i += 1
    return "".join(out)


def _quiet_unmask(word: str) -> str:
    return "".join(chr(ord(c) - _QUOTED_OFFSET) if 0xF0000 <= ord(c) < 0xFFFFD else c
                   for c in word if c != _QUOTE_MARK)


def _printf_format(first: str) -> bool:
    """The first argument of a `printf` (masked, as the lexer gave it) is its format for certain: it is no
    option, and it holds nothing a shell expands, so no `-v` can come out of it (`printf $X x`, `printf {-v,x}`,
    `printf "$(echo -v)" x` store their words in a variable). After `--` no word is an option."""
    plain = _quiet_unmask(first)
    if plain == "--":
        return True
    return (not plain.startswith("-") and "$" not in plain and "`" not in plain
            and _PRINTF_PLAIN_RE.fullmatch(first) is not None)


def _compound_outputs(cmds: list) -> Optional[tuple[list, dict]]:
    """For each simple command of the lexer's list, the groups and compounds around it (each by a number of its
    own, counted in the order they open), and for each of these whether its output is handed on by the separator
    behind its closer; a construct that never closes counts as handed on. None when a closer is not the word of
    the construct it would close (the line is not read completely). The caller has turned down every line with a
    bracket, so neither subshells nor `case` reach this. Fourth fix round: a key per construct, not per opening
    command, because zsh closes a group at a `}` that is no first word (`{ { ls .env; true } | xargs cat; }`):
    the check does not see that closer, and the construct it leaves open must not take the answer of a
    neighbour opened by the same command. Fifth fix round, the strict reading: also None for a closer with more
    than redirections behind it (`} always {`, `fi fi`, `} }`), a closer behind a shell word (`else fi`, which
    zsh takes) and a `}` among the words of a command (zsh closes a group there). With every closer the shell
    sees seen here, an opener the check does not know (`time {`, `repeat 1 {`) leaves one closer too many, which
    is None too; so no list of such words is kept."""
    stack: list[tuple[int, str]] = []
    enclosing: list = []
    handed_on: dict = {}
    opened = 0
    for k, (_sep, toks) in enumerate(cmds):
        j = 0
        if toks[:1] and toks[0] in _COMPOUND_CLOSERS:
            # fifth round: behind a closer only redirections; `} always {`, `fi fi` and `} }` open or close unseen
            if not stack or stack[-1][1] != toks[0] or drop_redirections(toks[1:]):
                return None
            # one construct, one closing: its own key, so a neighbour's answer never stands for it
            handed_on[stack.pop()[0]] = not _plain_sep(cmds[k + 1][0] if k + 1 < len(cmds) else "")
            j = len(toks)
        # `{ { ls .env; }; }`, `then if true`: the leading words of one command can open more than one construct;
        # each gets a number of its own, so one zsh closes unseen stays open here and counts as handed on
        while j < len(toks):
            t = toks[j]
            if t in _GROUP_CLOSER:
                stack.append((opened, _GROUP_CLOSER[t]))
                opened += 1
                j += 1
                if t in ("for", "select"):
                    break
            elif t in _NC_SHELL_WORDS:
                j += 1
            elif t in _COMPOUND_CLOSERS:
                return None  # fifth round: `else fi`, `do done`, `{ }`: a closer behind a shell word, which zsh takes
            else:
                break
        # fifth round: zsh closes a group at a `}` among the words of a command. With every closer seen, an opener
        # the check does not see (`time {`, `repeat 1 {`, `always {`) leaves one closer too many, and that is None
        if "}" in toks[j:]:
            return None
        enclosing.append([o for o, _ in stack])
    return enclosing, handed_on


def _quiet_reports(command: str) -> tuple:
    """The report commands (_REPORT_HEADS, `git check-ignore|ls-files|status`) whose output goes to no other
    command: `ls .env | xargs cat` and `cat $(ls .env)` read the file. Second fix round: a report is quiet only
    on a line the check reads completely; a line with a here-document, `$_`, a backtick, a bracket in a separator
    (subshell, substitution, function, `case` pattern, array) or a `function` or `coproc` has none. Fifth fix
    round: a report is quiet only on a line the check reads the way the shell does, and where it cannot be sure
    the line has none (fail closed). The structure is read from the masked line (_quiet_mask: a quoted or escaped
    brace, reserved word or separator is none); a line has no quiet report with `$[`, a character of the private
    plane, `$_` in any spelling, quoting the lexer reads otherwise than the shell (_quiet_mask gives up), more
    `[[` than `]]` or a word with unbalanced braces or brackets in one command (the lexer split inside `[[ ]]`,
    `${ }` or a subscript), or a structure _compound_outputs turns down. `printf -v` and `[[ … =~ … ]]` hand
    their words on in a variable and are never quiet. Sixth fix round: a quiet report is a command the check is
    certain about. A `printf` is one only when its first argument is a format for certain (_printf_format: no
    option, nothing a shell expands, so no `-v` can come out of it); `$_` is looked for in every word as the
    shell reads it too (`eval 'cat $'_`); a line with a carriage return (a blank for the lexer, a character for
    the shell) has none; a report's name with a path in front counts only in a system folder (_REPORT_DIRS:
    `./ls` is another program). Seventh fix round: a git report is quiet only when it hands its output to no pager
    for certain (_git_report_plain: between `git` and the subcommand only `-C <dir>`, `--no-pager` and `-P`, and
    no assignment in front of `git`). Eighth fix round: and only when nothing else on the line can set the
    environment or the configuration git takes a pager from: no word that runs a command while it is expanded
    (_WORD_RUNS_RE), and beside it only other quiet reports and the commands of _sets_nothing."""
    if "<<" in command or _LAST_ARG_RE.search(command):  # F13: `$_` hands the last word of a report on
        return ()
    if _QUIET_UNREAD_RE.search(command):
        return ()
    # F23: the lexer ends a command at the `&` of `2>&1`, `>&1`, `<&0`, `2>&-`, so the pipe behind it belonged to a
    # command `1`; _hi_prepare takes that `&` out, as the reader has it
    masked = _quiet_mask(_hi_prepare(command)[0])
    cmds = None if masked is None else _hi_lex(masked)
    if cmds is None:  # F12: a line the lexer cannot split shows no pipe; no report of it is quiet
        return ()
    for sep, toks in cmds:
        if any(c in sep for c in "()`"):
            return ()
        if _report_words(toks)[:1] in (("function",), ("coproc",)):
            return ()
        # fifth round: the lexer split inside `[[ … ]]`, `${…}` or a subscript, where the shell does not
        # (`[[ a && { ]]`, `${X:-a; }`, `a[x ; { ]=1`): what looks like a first word there is none
        if toks.count("[[") != toks.count("]]"):
            return ()
        if any(t not in _BRACKET_WORDS and (t.count("{") != t.count("}") or t.count("[") != t.count("]"))
               for t in toks):
            return ()
        # sixth round: `$_` in a word as the shell reads it, whatever quotes split it in the text (`eval 'cat $'_`)
        if any(_LAST_ARG_RE.search(_quiet_unmask(t)) for t in toks):
            return ()
    outputs = _compound_outputs(cmds)
    if outputs is None:
        return ()
    enclosing, handed_on = outputs
    out = []
    git_at: dict = {}  # eighth round: the git reports by their place on the line
    beside: set = set()  # eighth round: the places of the other reports that are their words alone
    for k, (sep, toks) in enumerate(cmds):
        if not _plain_sep(sep) or not _plain_sep(cmds[k + 1][0] if k + 1 < len(cmds) else ""):
            continue
        if any(handed_on.get(o, True) for o in enclosing[k]):  # F11: `{ ls .env; } | xargs cat`
            continue
        masked_words = _report_words(toks)
        words = tuple(_quiet_unmask(w) for w in masked_words)
        if not words:
            continue
        head = tool_name(words[0])
        # sixth round: a name with a path in front is the report only in a system folder
        if "/" in words[0] and os.path.dirname(words[0]) not in _REPORT_DIRS:
            continue
        # fifth round: `printf -v x` and `[[ … =~ … ]]` hand their words on in a variable; sixth round: the option
        # can only be the first argument, and that argument must be a format for certain (_printf_format)
        if head == "printf" and len(words) > 1 and not _printf_format(masked_words[1]):
            continue
        if head == "[[" and "=~" in words:
            continue
        if head in _REPORT_HEADS:
            out.append(words)
            if _words_alone(toks):
                beside.add(k)
        elif head == "git":
            sub, rest = _git_subcommand(list(words))
            if (sub in _REPORT_GIT_SUBS and not (sub == "status" and _git_status_verbose(rest))
                    and _git_report_plain(toks, words, rest)):
                git_at[k] = words
    # eighth round: a git report is quiet only when nothing else on the line can set what git reads: no word that
    # runs a command while it is expanded, and no other command but those of _sets_nothing
    if (git_at and not _WORD_RUNS_RE.search(command)
            and all(k in git_at or k in beside or _sets_nothing(toks) for k, (_sep, toks) in enumerate(cmds))):
        out.extend(git_at.values())
    return tuple(out)


# eighth fix round: the commands that may stand beside a quiet git report, apart from other quiet reports: they
# set no variable and write no file (a closer has only redirections behind it: _compound_outputs)
_BESIDE_GIT_REPORT = frozenset({"cd", "true", "false"}) | _COMPOUND_CLOSERS
# eighth fix round: a word that can run a command while the shell expands it, quoted or not: `$( )`, a backtick,
# and `${`, which opens `${ cmd; }` in bash 5.3 and the flags of zsh; read from the text of the line, so a
# literal one in single quotes counts too. The forms that open with a bare bracket are not listed and need not
# be (`<( )`, `>( )`, zsh's `=( )`, a glob qualifier such as `*(e:'…':)`): the lexer ends a command at the bracket,
# and a line with a bracket in a separator has no quiet report (second fix round, in _quiet_reports; rows F84)
_WORD_RUNS_RE = re.compile(r"\$[({]|`")


def _words_alone(toks) -> bool:
    """Eighth fix round: behind its leading shell words the command is its words alone: no redirection and no
    assignment."""
    k = 0
    while k < len(toks) and toks[k] in _NC_SHELL_WORDS:
        k += 1
    return tuple(toks[k:]) == _report_words(toks)


def _sets_nothing(toks) -> bool:
    """Eighth fix round: a command beside a git report that sets nothing git reads. git takes a pager and other
    programs from its environment and its configuration, and any other command of the line can set either, in a
    loop one behind the report too (`export GIT_CONFIG_COUNT=1 …; git ls-files .env`,
    `git config pager.ls-files 'xargs cat'`, `echo … >> .git/config`). So beside a quiet git report stand only
    other quiet reports that are their words alone, shell words, a closer, and `cd`, `true` and `false`, each
    without a redirection and without an assignment. (What an earlier call left in the configuration or the
    environment is not seen. That holds for the folder a `cd` of the line or `-C <dir>` names as well: the report
    runs under the configuration of the repository there, and the guard does not read it.)"""
    if not _words_alone(toks):
        return False
    words = _report_words(toks)
    return not words or words[0] in _BESIDE_GIT_REPORT


# seventh fix round: the options of git itself a quiet report may carry in front of its subcommand, beside
# `-C <dir>`. Any other is not known to hand nothing on.
_REPORT_GIT_OPTIONS = frozenset({"--no-pager", "-P"})


def _git_report_plain(toks, words: tuple, rest: list) -> bool:
    """Seventh fix round: a git report hands its output to no pager for certain. On a terminal git pipes a
    report into the program that an option in front of the subcommand or a variable set for the command names
    (`-c core.pager='xargs cat' -p`, `-c pager.ls-files=…`, `--config-env`, `GIT_PAGER=… git -p`, `GIT_CONFIG_…`),
    and `-c core.fsmonitor=…` runs a program outright. So between `git` and the subcommand stand only `-C <dir>`,
    `--no-pager` and `-P`, and no assignment stands in front of `git`. `toks` are the command's words as the
    lexer gave them, `words` the same without redirections and leading words, `rest` the words behind the
    subcommand. (A pager the configuration or the environment names without a word of this command is not seen.)"""
    lead = drop_redirections(list(toks))
    if any(_ASSIGN_RE.match(t) for t in lead[: len(lead) - len(words)]):
        return False
    front = list(words[1 : len(words) - len(rest) - 1])
    while front:
        if front[0] == "-C":
            del front[:2]
        elif front[0] in _REPORT_GIT_OPTIONS:
            del front[:1]
        else:
            return False
    return True


def _git_status_verbose(rest: list[str]) -> bool:
    """F26: `git status -v` prints the staged change of the paths it names, `-vv` the change in the work tree:
    content, not names (measured, git 2.55). A `v` in a short cluster (`-bv`), or a long option that is a prefix
    of --verbose (git takes a unique prefix: `--v`), before `--`."""
    for t in rest:
        if t == "--":
            return False
        if t.startswith("--"):
            name = t.partition("=")[0]
            if len(name) >= 3 and "--verbose".startswith(name):
                return True
        elif t.startswith("-") and "v" in t[1:]:
            return True
    return False


def _take_quiet(quiet: "collections.Counter", seg) -> bool:
    """The simple command is one of the quiet reports: count it off, so a twin nested elsewhere is still read."""
    words = _report_words(seg)
    if quiet.get(words, 0) > 0:
        quiet[words] -= 1
        return True
    return False


def rule_secret_shell(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    writes: list[str] = []
    reads: list[str] = []
    command = strip_heredocs(ev.command)
    # addendum: the targets on the line as the shell joins it (`echo x > \⏎.env` writes .env); only here
    for target in _REDIRECT_RE.findall(command.replace("\\\n", "")):
        target = target.strip("\"'`,;)")
        if secret_class(_expand(target, ev.cwd)) == "secret":
            writes.append(target)
    if _EMPTY_TOKEN_RE.search(command):
        return "deny", GITHUB_LOGIN_MSG.format(rule="secret-shell", what="an empty GH_TOKEN (gh and git fall back to "
                                                                       "the stored login)")
    quiet = _quiet_reports(ev.command)
    first_quiet = collections.Counter(quiet)
    for seg in segments(command):
        what = github_login_what(seg)
        if what:
            return "deny", GITHUB_LOGIN_MSG.format(rule="secret-shell", what=what)
        if _take_quiet(first_quiet, seg):
            continue
        # 0.9.0 (K3): the first pass leaves a search tool's pattern out as the reader pass does
        _secret_reader_seg(seg, ev.cwd, writes, reads)
    if writes:
        return _secret_verdict(writes, reads, ev.cwd)
    # the reader pass adds to the same lists, so one message names every file of both passes; the reader gets
    # the here-documents and reads a body only where a shell runs it (0.8.0)
    stored: list[Decision] = []

    reader_quiet = collections.Counter(quiet)

    def judge(seg: list[str]) -> Optional[Decision]:
        what = github_login_what(seg)
        if what:
            return "deny", GITHUB_LOGIN_MSG.format(rule="secret-shell", what=what)
        if _take_quiet(reader_quiet, seg):
            return None
        _secret_reader_seg(seg, ev.cwd, writes, reads)
        what = secret_store_what(seg)  # 0.9.0: a stored secret printed (decision af)
        if what:
            stored.append(("ask", SECRET_STORE_MSG.format(what=what)))
        return None

    read: list[bool] = []
    failed = reader_pass(ev.command, judge, "secret-shell", read=read)
    # the read went through, so its input redirections are known (`cat <.env`), whatever the pass answers (an
    # unread pipe, a crash of the judge); a line the reader could not read leaves `read` empty
    if read:
        reads.extend(p for p in nested_inputs(ev.command) if secret_class(_expand(p, ev.cwd)) == "secret")
    if failed and failed[0] == "deny":
        return failed
    return combine([d for d in (_secret_verdict(writes, reads, ev.cwd), failed, *stored) if d])


# ----------------------------------------------------------------------------
# git-guard: no force push, no push to a protected branch, no --no-verify
# ----------------------------------------------------------------------------

_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                          "--config-env"}  # 0.8.0: `--config-env <name>=<envvar>` (git(1))
_PUSH_OPT_WITH_VALUE = {"-o", "--push-option", "--receive-pack", "--exec", "--repo", "--recurse-submodules"}
_FORCE_FLAGS = {"-f", "--force", "--force-with-lease", "--force-if-includes"}
GIT_MSG = (
    "git-guard: {what}. Work on a branch and open a PR; "
    "force pushes and hook bypasses are never auto-approved."
)


def _git_subcommand(seg: list[str]) -> tuple[Optional[str], list[str]]:
    if not seg or os.path.basename(seg[0]) != "git":
        return None, []
    i = 1
    while i < len(seg) and seg[i].startswith("-"):
        if seg[i] in _GIT_GLOBAL_WITH_VALUE:
            i += 2
        else:
            i += 1
    if i >= len(seg):
        return None, []
    return seg[i], seg[i + 1 :]


# 0.8.0: git accepts a unique prefix of a long option (`--no-verif`, `--force-with-leas`; measured) and short
# options in one word (`-uf`, `-nm x`). These subcommands run a hook that --no-verify skips (githooks(5))
_NO_VERIFY_SUBS = frozenset("commit push merge pull am rebase".split())
_PUSH_FORCE_NAMES = ("force", "force-with-lease", "force-if-includes")
# short options that take a value (git-commit(1), git-push(1)): the letters after one are its value, or the next
# word is; commit's -u and -S take an optional value glued on (`-uno` is --untracked-files=no)
_GIT_SHORT_VALUED = {"commit": ("mFCct", "uS"), "push": ("o", "")}


def _git_options(sub: str, rest: list[str]) -> tuple[list[str], set]:
    """The long option names (cut at `=`) and the short option letters among a git subcommand's words in front
    of `--`; the value of a short option that takes one is no option (`-mn` is the message `n`)."""
    valued, optional = _GIT_SHORT_VALUED.get(sub, ("", ""))
    longs: list[str] = []
    shorts: set = set()
    skip = False
    for t in rest:
        if skip:
            skip = False
            continue
        if t == "--":
            break
        if t.startswith("--"):
            name = t[2:].split("=", 1)[0]
            if name:
                longs.append(name)
        elif t.startswith("-") and len(t) > 1:
            for k, c in enumerate(t[1:], 1):
                shorts.add(c)
                if c in valued:
                    skip = k == len(t) - 1  # nothing glued on: the next word is the value
                    break
                if c in optional:
                    break
    return longs, shorts


def _git_prefix(longs: list[str], names: tuple) -> bool:
    """A long option as written is one of `names` or a prefix of one: git takes a unique prefix for the option,
    and refuses a prefix two options share, so the over-match costs nothing."""
    return any(n.startswith(x) for x in longs for n in names)


# 0.8.0: the hook gate through configuration and the environment. The key is case-insensitive (measured); the
# kit's own hook directory is the one silent value
_HOOKS_PATH_KEY = "core.hookspath"
_KIT_HOOKS = ".githooks"
GIT_HOOKS_PATH_MSG = ("git-guard: `git config core.hooksPath` changes where the commit gate's hooks run. "
                      "The kit installs `.githooks`; confirm any other change.")
# the hook managers' own off switches (husky, lefthook, pre-commit's SKIP) and the git calls whose hooks they skip
# the values that switch a hook runner off: husky 9 `HUSKY=0`; lefthook 1.x `LEFTHOOK=0` or `LEFTHOOK=false` (its
# documentation; 0.9.0)
_HOOK_ENV_OFF = {"HUSKY": frozenset({"0"}), "LEFTHOOK": frozenset({"0", "false"})}
_HOOK_ENV_SUBS = frozenset("commit push merge pull rebase am cherry-pick revert".split())


def _git_sets_hooks_path(own: list[str]) -> bool:
    """git's own options (the words between `git` and the subcommand) set core.hooksPath for the call:
    `-c core.hooksPath=…` with any value but `.githooks`, or `--config-env=core.hooksPath=VAR` (git(1))."""
    for k, t in enumerate(own):
        if t == "-c" and k + 1 < len(own):
            key, _eq, value = own[k + 1].partition("=")
            if key.lower() == _HOOKS_PATH_KEY and value != _KIT_HOOKS:
                return True
        elif t.startswith("--config-env=") and t[len("--config-env=") :].partition("=")[0].lower() == _HOOKS_PATH_KEY:
            return True
        elif t == "--config-env" and k + 1 < len(own) and own[k + 1].partition("=")[0].lower() == _HOOKS_PATH_KEY:
            return True  # the value as the next word (measured: git 2.43.0 accepts it)
    return False


def _git_config_writes_hooks_path(rest: list[str]) -> bool:
    """`git config` sets or unsets core.hooksPath: `[set] core.hooksPath <value>`, `--unset`, `--unset-all`,
    `unset`, with any scope option in front. The value `.githooks` and the reads (`--get`, `get`, the name alone,
    `--list`) are none (git-config(1))."""
    for k, t in enumerate(rest[:-1]):  # dropping or renaming the section `core` drops core.hooksPath (0.8.0)
        if t in ("--remove-section", "--rename-section", "remove-section", "rename-section") \
                and rest[k + 1].lower() == "core":
            return True
    keys = [k for k, t in enumerate(rest) if t.lower() == _HOOKS_PATH_KEY]
    if not keys:
        return False
    before = rest[: keys[0]]
    if any(t in ("--unset", "--unset-all", "unset") for t in before):
        return True
    if any(t.startswith(("--get", "--list")) or t in ("-l", "get", "list") for t in before):
        return False
    values = [t for t in rest[keys[0] + 1 :] if not t.startswith("-")]
    return bool(values) and values[0] != _KIT_HOOKS


def _git_env_bypass(env: list[str], seg: list[str]) -> Optional[str]:
    """What the environment of one git call (assignments in front of it, `env NAME=value`, earlier exports) does
    to the hooks: HUSKY=0, LEFTHOOK=0 or SKIP=… for a git call that runs hooks; GIT_CONFIG_KEY_<n> or
    GIT_CONFIG_PARAMETERS naming core.hooksPath for any git call."""
    sub, _rest = _git_subcommand(seg)
    if sub is None:
        return None
    for word in env:
        name, _eq, value = word.partition("=")
        if sub in _HOOK_ENV_SUBS and (value in _HOOK_ENV_OFF.get(name, ()) or name == "SKIP"):
            return f"`{word}` in the environment of `git {sub}` skips the hooks"
        if ((name.startswith("GIT_CONFIG_KEY_") and value.lower() == _HOOKS_PATH_KEY)
                or (name == "GIT_CONFIG_PARAMETERS" and _HOOKS_PATH_KEY in value.lower())):
            return f"`{name}` sets core.hooksPath for `git {sub}` and skips the hooks"
    return None


def _git_env_gate(command: str) -> Optional[Decision]:
    """The hook gate through the environment, read from the reader's token lists: the words in front of a git
    command word and the `export NAME=value` of an earlier simple command of the line (a plain `NAME=value;`
    does not reach git). segments() drops these words, so only the reader sees them."""
    try:
        exported: list[str] = []
        assigned: dict = {}  # NAME -> `NAME=value` of a plain assignment, which an `export NAME` exports later
        export_names: set = set()  # F19: a name exported before it is assigned; a later assignment is exported
        allexport = [False]  # `set -a`: every later assignment is exported

        def environment(toks) -> bool:
            """Take an assignment, export or `set -a` line into the state; False for any other command."""
            # F19: `builtin eval …`, `command export …` run the builtin itself (bash(1), "builtin", "command");
            # `command -v` is a lookup and stays. Second fix round: also behind `command -p`, `--`, a shell word
            # (`{`, `then`, `do`, `!`) and `time [-p]`: each exports to the commands after it (bash 5.3, zsh 5.9, sh)
            toks = list(toks)
            while toks:
                if toks[0] in _NC_SHELL_WORDS:
                    toks = toks[1:]
                elif toks[0] == "time":
                    toks = toks[2:] if toks[1:2] == ["-p"] else toks[1:]
                elif toks[0] in ("builtin", "command"):
                    k = 1
                    while k < len(toks) and toks[k] in (("-p", "--") if toks[0] == "command" else ("--",)):
                        k += 1
                    if k >= len(toks) or toks[k].startswith("-"):
                        break
                    toks = toks[k:]
                else:
                    break
            if not toks:
                return False
            if all(_ASSIGN_RE.match(t) for t in toks):
                for t in toks:
                    assigned[t.partition("=")[0]] = t
                if allexport[0]:
                    exported.extend(toks)
                else:
                    exported.extend(t for t in toks if t.partition("=")[0] in export_names)
                return True
            if toks[0] in ("export", "declare", "typeset"):
                flags = "".join(t[1:] for t in toks[1:] if t.startswith("-"))
                if toks[0] == "export" or "x" in flags:  # `declare -x`, `typeset -x` export as well
                    exported.extend(t for t in toks[1:] if _ASSIGN_RE.match(t))
                    exported.extend(assigned[t] for t in toks[1:] if t in assigned)
                    export_names.update(t.partition("=")[0] for t in toks[1:] if not t.startswith("-"))
                return True
            if toks[0] == "set":
                for t in toks[1:]:
                    if t.startswith(("-", "+")) and "a" in t[1:] and not t.startswith("--"):
                        allexport[0] = t[0] == "-"
                    elif t == "allexport" and toks[toks.index(t) - 1] in ("-o", "+o"):
                        allexport[0] = toks[toks.index(t) - 1] == "-o"
                return True
            if toks[0] == "eval" and len(toks) > 1:
                # 0.9.0: the script of an eval runs in this shell, so its exports reach the commands after it in
                # the line; the reader reads the script after them, so it is taken in here, where the eval stands
                start = 2 if toks[1] == "--" else 1
                for _sep, words in simple_commands(" ".join(toks[start:])):  # its own commands, not its nests
                    inner = [w for w in drop_redirections(words) if w not in _NC_SHELL_WORDS]
                    if inner:
                        environment(inner)
            return False

        for toks, inherited in zip(nested_commands(command), nested_envs(command)):
            if environment(toks):
                continue
            for i in sorted(command_word_indexes(toks)):
                if os.path.basename(toks[i]) == "git":
                    # the environment the script inherits from the shell that runs it, the words in front, exports
                    env = list(inherited) + [t for t in toks[:i] if _ASSIGN_RE.match(t)] + exported
                    what = _git_env_bypass(env, list(toks[i:]))
                    if what:
                        return "deny", GIT_MSG.format(what=what)
    except CommandNotRead:  # reader_pass reads the same memo next and asks with the reason
        return None
    except Exception as exc:  # main() turns a crash into exit 1, which both harnesses let run silently: ask instead
        return "ask", READER_MSG.format(rule="git-guard", what=f"the command could not be read ({type(exc).__name__})")
    return None


def current_branch(cwd: str) -> Optional[str]:
    """Checked-out branch name, also on an unborn branch; None when detached or not a repo."""
    for args in (["symbolic-ref", "--short", "-q", "HEAD"], ["rev-parse", "--abbrev-ref", "HEAD"]):
        try:
            r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            return None
        name = r.stdout.strip()
        if r.returncode == 0 and name and name != "HEAD":
            return name
    return None


GIT_ELSEWHERE_MSG = (
    "git-guard: `git push` {what} runs in a container or on another host; the branch checked out there is not "
    "known. Name the destination branch (`git push origin <branch>`) or confirm."
)


def _git_guard_seg(seg: list[str], cwd: str, protected: set, elsewhere: bool = False) -> Optional[Decision]:
    """The git-guard verdict on one simple command: a hook bypass, a forced push, a push to a protected branch.
    `elsewhere`: the push runs in a container or on another host, so the host's branch says nothing; a push
    without a refspec, or to HEAD, asks."""
    sub, rest = _git_subcommand(seg)
    if sub is None:
        return None
    longs, shorts = _git_options(sub, rest)
    if ("--no-verify" in rest or (sub == "commit" and ("-n" in rest or "n" in shorts))
            or (sub in _NO_VERIFY_SUBS and _git_prefix(longs, ("no-verify",)))):
        return "deny", GIT_MSG.format(what=f"`git {sub} --no-verify` skips the commit gate")
    if _git_sets_hooks_path(seg[1 : len(seg) - len(rest) - 1]):
        return "deny", GIT_MSG.format(what=f"`git {sub}` sets core.hooksPath for the call and skips the hooks")
    if sub == "config" and _git_config_writes_hooks_path(rest):
        return "ask", GIT_HOOKS_PATH_MSG
    rewrite = _git_ref_rewrite(sub, rest)
    if sub != "push" or rewrite:
        return rewrite
    if (any(t in _FORCE_FLAGS or t.startswith("--force-with-lease=") for t in rest) or "f" in shorts
            or _git_prefix(longs, _PUSH_FORCE_NAMES)):
        return "deny", GIT_MSG.format(what="force push")
    if "--all" in rest or "--mirror" in rest or _git_prefix(longs, ("mirror", "all")):
        return "deny", GIT_MSG.format(what="`git push --all/--mirror` can rewrite a protected branch")
    positional: list[str] = []
    skip = False
    for t in rest:
        if skip:
            skip = False
            continue
        if t in _PUSH_OPT_WITH_VALUE:
            skip = True
            continue
        if t.startswith("-"):
            continue
        positional.append(t)
    refspecs = positional[1:]
    if not refspecs:
        if elsewhere:
            return "ask", GIT_ELSEWHERE_MSG.format(what="without a refspec")
        branch = current_branch(cwd)
        if branch in protected:
            return "deny", GIT_MSG.format(what=f"push to protected branch '{branch}'")
        return None
    to_head = False
    for r in refspecs:
        if r.startswith("+"):
            return "deny", GIT_MSG.format(what=f"force refspec {r}")
        dest = r.split(":", 1)[1] if ":" in r else r
        if dest.startswith("refs/heads/"):
            dest = dest[len("refs/heads/") :]
        if dest == "HEAD" and elsewhere:
            to_head = True
            continue
        if dest == "HEAD":
            dest = current_branch(cwd) or dest
        if dest in protected:
            return "deny", GIT_MSG.format(what=f"push to protected branch '{dest}'")
    return ("ask", GIT_ELSEWHERE_MSG.format(what="to HEAD")) if to_head else None


# 0.10.0 (item #65, D9): the remote-tracking refs are what the guard and the tracker read as the remote's state.
# Named limit: `git fetch . <sha>:<other ref>` forms and direct writes under .git/ match nothing.
REF_REWRITE_MSG = ("git-guard: {what} rewrites the remote-tracking refs the guard reads (refs/remotes/); a session "
                   "never does.")
REF_SOURCE_MSG = ("git-guard: {what} changes where the remote-tracking refs the guard reads come from. Confirm the "
                  "command.")
_REMOTE_REFS = "refs/remotes/"
_REMOTE_KEY_RE = re.compile(r"^(remote\.(.+\.)?(url|pushurl|fetch)|url\..+\.(push)?insteadof)$", re.IGNORECASE)


def _git_config_writes_remote(rest: list[str]) -> bool:
    """`git config` sets, adds or unsets remote.<name>.url|pushurl|fetch, or drops or renames a remote's section;
    the reads (`--get`, the name alone, `--list`) are none."""
    for k, t in enumerate(rest[:-1]):
        if t in ("--remove-section", "--rename-section", "remove-section", "rename-section") \
                and rest[k + 1].lower().startswith("remote."):
            return True
    keys = [k for k, t in enumerate(rest) if _REMOTE_KEY_RE.match(t)]
    if not keys:
        return False
    before = rest[: keys[0]]
    if any(t in ("--unset", "--unset-all", "unset", "--add", "--replace-all") for t in before):
        return True
    if any(t.startswith(("--get", "--list")) or t in ("-l", "get", "list") for t in before):
        return False
    return any(not t.startswith("-") for t in rest[keys[0] + 1 :])


def _git_local_remote(word: str) -> bool:
    """A push target that names a repository on this machine: a path (`.`, `..`, `.git`, `sub/repo`, `~/x`,
    `$PWD`, `file:…`), not a URL, an scp-like `host:path` or a configured remote's bare name. Fails closed: a word
    with a slash and no host part counts as a path."""
    if word.startswith(("file:", "$", "`", "~", ".", "/")):
        return True
    if "://" in word or re.match(r"^[^/]+:", word):
        return False
    return "/" in word


_LOOPBACK_HOSTS = frozenset(("localhost", "127.0.0.1", "::1"))


def _git_remote_add_local(rest: list[str]) -> bool:
    """`git remote add [-t <branch>] [-m <master>] [-f] … <name> <url>` with a url on this machine: anything but a
    URL with `://` or an scp-like `host:path` (a bare word is a relative path to git here, not a remote name)."""
    words, skip = [], False
    for t in rest[rest.index("add") + 1:]:
        if skip:
            skip = False
        elif t in ("-t", "--track", "-m", "--master"):
            skip = True
        elif not t.startswith("-"):
            words.append(t)
    if len(words) < 2:
        return False
    url = words[1]
    if url.startswith("file:"):
        return True
    m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?(\[[^\]]*\]|[^:/]*)", url, re.IGNORECASE) \
        or re.match(r"^(?:[^@/:]*@)?(\[[^\]]*\]|[^:/]+):", url)
    if not m:
        return True  # no host part: a path
    return m.group(1).lower().strip("[]") in _LOOPBACK_HOSTS  # ssh://localhost/…, 127.0.0.1:/…: this machine


def _git_ref_rewrite(sub: str, rest: list[str]) -> Optional[Decision]:
    """The git-guard verdict on a call that writes the remote-tracking refs (deny) or their source (ask)."""
    operands = [t for k, t in enumerate(rest) if not t.startswith("-") and not (k and rest[k - 1] == "-m")]
    remote = any(t.startswith(_REMOTE_REFS) for t in operands)
    if sub == "update-ref" and remote:
        return "deny", REF_REWRITE_MSG.format(what="`git update-ref`")
    if sub == "push" and operands:
        dests = [t.rsplit(":", 1)[1] if ":" in t else t.lstrip("+") for t in operands[1:]]
        if any(d.lower().startswith((_REMOTE_REFS, "remotes/")) for d in dests):
            return "deny", REF_REWRITE_MSG.format(what="`git push` into a remote-tracking ref")
        # a push into this repository (or another local one) resolves a short name like `origin/main` against
        # its refs, remote-tracking ones included: only refs/heads/ and refs/tags/ written out stay open
        if _git_local_remote(operands[0]):
            if "--delete" in rest or "-d" in rest or any(not d.startswith(("refs/heads/", "refs/tags/"))
                                                          for d in dests if d):
                return "deny", REF_REWRITE_MSG.format(
                    what="`git push` into a local repository with a short or deleted destination")
    if sub == "branch":
        longs, shorts = _git_options(sub, rest)
        if ("r" in shorts or _git_prefix(longs, ("remotes",))) and (
                shorts & set("dDmMcC") or _git_prefix(longs, ("delete", "move", "copy"))):
            return "deny", REF_REWRITE_MSG.format(
                what="`git branch -r` deleting, renaming or copying a remote-tracking ref")
    if sub == "replace" and rest and rest[0] not in ("-l", "--list") and not rest[0].startswith("--format"):
        return "deny", REF_REWRITE_MSG.format(what="`git replace` (it swaps the objects every ref reads through)")
    if sub == "symbolic-ref" and remote and (len(operands) > 1 or "-d" in rest or "--delete" in rest):
        return "deny", REF_REWRITE_MSG.format(what="`git symbolic-ref`")
    if sub == "remote" and operands[:1] == ["add"] and _git_remote_add_local(rest):
        return "ask", REF_SOURCE_MSG.format(what="`git remote add` of a repository on this machine")
    if sub == "remote" and operands[:1] in (["set-url"], ["rename"], ["remove"], ["rm"], ["set-branches"],
                                            ["set-head"]):
        return "ask", REF_SOURCE_MSG.format(what=f"`git remote {operands[0]}`")
    if sub == "config" and _git_config_writes_remote(rest):
        return "ask", REF_SOURCE_MSG.format(what="`git config` of a remote's url or fetch refspec")
    if sub == "fetch" and any(":" in t and t.rsplit(":", 1)[1].startswith(_REMOTE_REFS) for t in operands):
        return "ask", REF_SOURCE_MSG.format(what="`git fetch` into a named remote-tracking ref")
    return None


def rule_git_guard(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    protected = protected_branches(cfg)
    command = strip_heredocs(ev.command)
    asks = []  # 0.8.0: the first pass can ask (`git config core.hooksPath`); a later deny of the line still wins
    if _REMOTE_REFS in ev.command and any(_git_subcommand(seg)[0] == "update-ref" and "--stdin" in seg
                                          for seg in segments(command)):  # the refs it moves come from its input
        return "deny", REF_REWRITE_MSG.format(what="`git update-ref --stdin` with refs/remotes/ on the line")
    for seg in segments(command):
        d = _git_guard_seg(seg, ev.cwd, protected)
        if d and d[0] == "deny":
            return d
        if d:
            asks.append(d)
    here = _local_simple_commands(ev.command)  # the reader takes the here-document bodies out itself (0.8.0)

    def judge(seg: list[str]) -> Optional[Decision]:
        # a simple command the local reading does not find runs elsewhere: the host's branch says nothing there
        return _git_guard_seg(seg, ev.cwd, protected, elsewhere=here is not None and tuple(seg) not in here)

    gate = _git_env_gate(ev.command)
    if gate and gate[0] == "deny":
        return gate
    # the net (0.9.0) judges a git behind an unknown word as run here: what that word does is not known
    net = reader_pass(ev.command, judge, "git-guard", net=lambda seg: _git_guard_seg(seg, ev.cwd, protected))
    return combine(asks + [d for d in (gate, net) if d])


def _local_simple_commands(command: str) -> Optional[set]:
    """The words from every command word of every simple command this machine runs (the local reading), or None
    when that reading stops; then every push is judged by the host's branch, as before."""
    try:
        return {toks[i:] for toks in nested_commands(command, local=True) for i in command_word_indexes(toks)}
    except Exception:  # CommandNotRead or a crash: the full reading in reader_pass asks or judges on its own
        return None


# ----------------------------------------------------------------------------
# deploy-ask: anything that changes a live environment needs an explicit yes
# ----------------------------------------------------------------------------

def _verbs(words: str) -> frozenset:
    """A word set (what `_w` does further down; the tables here load before it)."""
    return frozenset(words.split())


_TERRAFORM = (_verbs("apply destroy import taint untaint"), {"state": _verbs("rm mv push")},
              "terraform/tofu changes state")
_PROXMOX = "Proxmox changes a guest"
_PULUMI_CDK = "pulumi/cdk deploys"
# tool basename -> (verbs, pairs as first word -> second words, label); restates the 0.6.0 expressions tool by
# tool, and counts wherever the tool's name stands as a word (behind sudo, timeout, npx, uv run, ssh host, …)
_DEPLOY_TABLE: dict = {
    "terraform": _TERRAFORM,
    "tofu": _TERRAFORM,
    "kubectl": (_verbs("apply create delete rollout drain cordon uncordon scale patch replace edit exec"), {},
                "kubectl changes the cluster"),
    "helm": (_verbs("install upgrade uninstall delete rollback"), {}, "helm changes a release"),
    "docker": (_verbs("push"), {"compose": _verbs("push")}, "pushes an image"),
    "docker-compose": (_verbs("push"), {}, "pushes an image"),
    "gh": (_verbs(""), {"workflow": _verbs("run"), "release": _verbs("create delete edit upload")},
           "triggers a workflow or release"),
    "az": (_verbs(""), {}, "az changes resources"),  # judged by _az_changes
    # `s3 sync` counts only with --delete (deploy_what)
    "aws": (_verbs(""), {"cloudformation": _verbs("deploy create-stack update-stack delete-stack execute-change-set"),
                         "s3": _verbs("rm rb sync")}, "CloudFormation"),
    "hcloud": (_verbs(""), {"server": _verbs("create delete rebuild poweroff reset shutdown")},
               "hcloud server lifecycle"),
    "pvesh": (_verbs("create set delete"), {}, _PROXMOX),
    "qm": (_verbs("destroy stop shutdown reset"), {}, _PROXMOX),
    "pulumi": (_verbs("up destroy"), {}, _PULUMI_CDK),
    "cdk": (_verbs("deploy destroy"), {}, _PULUMI_CDK),
    "ansible-playbook": (_verbs(""), {}, "ansible-playbook changes hosts"),  # judged by _ansible_runs
    "flux": (_verbs("uninstall suspend"), {}, "flux changes reconciliation"),
    # 0.7.0: the tools below are new; their rows are all in _DEPLOY_ADDED
    "podman": (_verbs("push"), {"compose": _verbs("push")}, "pushes an image"),
    "nerdctl": (_verbs("push"), {"compose": _verbs("push")}, "pushes an image"),
    "pct": (_verbs(""), {}, _PROXMOX),
    "argocd": (_verbs(""), {}, "argocd changes an application"),
    "skopeo": (_verbs(""), {}, "copies or deletes registry images"),
    "crane": (_verbs(""), {}, "copies or deletes registry images"),
}
_PROXMOX_GUEST = ("start stop shutdown reboot reset suspend resume destroy migrate clone rollback create set"
                  " delsnapshot")
_DOCKER_ADDED = (_verbs("build"), {"image": _verbs("push"), "manifest": _verbs("push"),
                                   "buildx": _verbs("build bake")})
_TERRAFORM_ADDED = (_verbs("force-unlock"), {"workspace": _verbs("delete"), "state": _verbs("replace-provider")})
# 0.7.0 rows (verbs, pairs), read after the 0.6.1 rows above found nothing. Unlike those, they keep a help probe
# silent wherever its word stands (`kubectl label --help`); the 0.6.1 rows ask for it as they did.
_DEPLOY_ADDED: dict = {
    "docker": _DOCKER_ADDED,
    "podman": _DOCKER_ADDED,
    "nerdctl": _DOCKER_ADDED,
    "terraform": _TERRAFORM_ADDED,
    "tofu": _TERRAFORM_ADDED,
    "kubectl": (_verbs("label annotate set run taint expose autoscale debug"), {}),  # debug starts a container
    "gh": (_verbs(""), {"run": _verbs("rerun cancel delete"), "workflow": _verbs("enable disable")}),
    "argocd": (_verbs(""), {"app": _verbs("sync delete rollback set create patch")}),
    "flux": (_verbs("reconcile resume delete create bootstrap"), {}),
    "qm": (_verbs(_PROXMOX_GUEST), {}),
    "pct": (_verbs(_PROXMOX_GUEST + " restore"), {}),
    "skopeo": (_verbs("copy delete sync"), {}),
    "crane": (_verbs("push copy delete tag"), {}),
}
_PUSH_ONLY = frozenset({"build", "buildx build", "buildx bake"})  # these count only with --push
# aws: an operation under any service that starts so, and these pairs (_aws_hit)
_AWS_DESTROY = ("delete-", "terminate-", "batch-delete-")
_AWS_UPDATES = {"ecs": _verbs("update-service execute-command"),
                "lambda": _verbs("update-function-code update-function-configuration update-alias"),
                # 0.9.0: run a command on a live host or container (AWS CLI v2 reference: `aws ssm send-command`,
                # `aws ssm start-session`, `aws ecs execute-command`)
                "ssm": _verbs("send-command start-session")}
# 0.9.0: az verbs that run a command on a live host or container, or deploy past the table above (Azure CLI 2.6x
# reference: `az vm|vmss run-command invoke`, `az aks command invoke`, `az container|containerapp exec`,
# `az webapp|functionapp deployment source config-zip`, `… deployment slot swap`); the verb is the last leading word
_AZ_RUNS = frozenset({"invoke", "exec", "config-zip", "swap"})
_DRY_VALUES = frozenset({"client", "server", "true"})  # --dry-run=<these> previews; any other value applies
# the 0.6.0 text pass, kept as it was (fix brief 1: nothing that asked at 0.6.0 may stop asking)
_DEPLOY_PATTERNS = [
    (
        r"(terraform|tofu)\s+(apply|destroy|import|taint|untaint|state\s+(rm|mv|push))",
        "terraform/tofu changes state",
    ),
    (
        r"kubectl\s+(apply|create|delete|rollout|drain|cordon|uncordon|scale|patch|replace|edit|exec)",
        "kubectl changes the cluster",
    ),
    (r"helm\s+(install|upgrade|uninstall|delete|rollback)", "helm changes a release"),
    (r"docker\s+push|docker\s+compose\s+push", "pushes an image"),
    (r"gh\s+workflow\s+run|gh\s+release\s+(create|delete|edit|upload)", "triggers a workflow or release"),
    (r"az\s+pipelines\s+(run|build\s+queue)", "triggers a pipeline run"),
    # `az repos pr create` opens a PR (pr-prep's job), it changes no environment
    (r"az\s+deployment|az\s+(?!repos\s+pr\s+create(\s|$))\S+(\s+\S+)*\s+(delete|create)", "az changes resources"),
    (
        r"aws\s+cloudformation\s+(deploy|create-stack|update-stack|delete-stack|execute-change-set)",
        "CloudFormation",
    ),
    (r"aws\s+s3\s+(rm|rb)|aws\s+s3\s+sync\s.*--delete", "aws s3 deletes"),
    (r"hcloud\s+server\s+(create|delete|rebuild|poweroff|reset|shutdown)", "hcloud server lifecycle"),
    (r"pvesh\s+(create|set|delete)|qm\s+(destroy|stop|shutdown|reset)", "Proxmox changes a guest"),
    (r"pulumi\s+(up|destroy)|cdk\s+(deploy|destroy)", "pulumi/cdk deploys"),
    (r"ansible-playbook", "ansible-playbook changes hosts"),
    (r"flux\s+(uninstall|suspend)", "flux changes reconciliation"),
]
_DEPLOY_RES = [
    (re.compile(r"(^|[;&|(`]|\$\()\s*(sudo\s+)?(" + p + r")(\s|$)", re.MULTILINE), label)
    for p, label in _DEPLOY_PATTERNS
]
_DRY_RE = re.compile(r"--dry-run|--check(\s|$)|\s--diff(\s|$)|\s(plan|validate|template|lint|diff)(\s|$)")
DEPLOY_MSG = (
    "Deploy/apply boundary: {what}. Needs an explicit yes (AGENTS.md: terraform plan / kubectl diff first)."
)


def _deploy_text(command: str) -> Optional[str]:
    """The 0.6.0 text pass: the label of the first deploy pattern at the start of a text segment, or None."""
    for part in _SEP_RE.split(command):
        if _DRY_RE.search(part):
            continue
        for rx, label in _DEPLOY_RES:
            if rx.search(" " + part.strip()) or rx.search(part):
                return label
    return None


def _dry_run(name: str, args: list[str]) -> bool:
    """This tool call only previews: the last --dry-run is bare or client/server/true, ansible's --check, or az's
    validate as a subcommand word."""
    last = None
    for t in args:
        if t == "--dry-run" or t.startswith("--dry-run="):
            last = t  # the last one wins, as in kubectl and helm
        elif name == "ansible-playbook" and t == "--check":
            return True
    if last is not None and (last == "--dry-run" or last.split("=", 1)[1].lower() in _DRY_VALUES):
        return True
    if name != "az":
        return False
    for t in args:  # only the leading words: `az group delete --name validate` names a resource
        if t.startswith("-"):
            return False
        if t == "validate":
            return True
    return False


def _az_changes(args: list[str], at_command_word: bool = True) -> Optional[str]:
    """0.6.0's az expressions in token form: pipeline runs, deployments, and delete/create past the first word;
    0.9.0: at a command word, every verb that is no known read (_az_writes)."""
    args = drop_redirections(args)
    words = [t for t in args if not t.startswith("-")]
    if words[:2] == ["pipelines", "run"] or words[:3] == ["pipelines", "build", "queue"]:
        return "triggers a pipeline run"
    if words[:1] == ["deployment"]:
        return "az changes resources"
    if words[:3] == ["repos", "pr", "create"]:
        return None  # opens a PR (pr-prep's job), it changes no environment
    if {"delete", "create"} & set(args[1:]):
        return "az changes resources"
    if words[:3] == ["repos", "pr", "update"]:
        return None  # changes a pull request, no environment (tracker-guard still reads it)
    lead = _az_leading_words(args)
    if lead[:2] == ["extension", "update"]:
        return None  # an install on this machine: host-install judges it
    if {"deploy", "update", "up"} & set(lead[1:]) and not _help_probe(args):  # 0.7.0 words, where the verb stands
        return "az changes resources"
    if len(lead) > 1 and lead[-1] in _AZ_RUNS and not _help_probe(args):
        return "az runs a command on a live resource or deploys"
    return _az_writes(args, lead) if at_command_word else None  # `echo az vm restart` is text


# 0.9.0 (decision ag): every az call whose verb (the last leading word) is no known read asks. The reads and the
# calls that change only this machine, from the Azure CLI 2.6x reference; a list of write verbs was the other
# answer and is not taken, since a verb such a list misses would stay silent
_AZ_READ_VERBS = frozenset("list show exists wait query tail download browse version result".split())
_AZ_READ_PREFIXES = ("list-", "show-", "get-", "check-")
_AZ_LOCAL_GROUPS = frozenset("login logout config configure extension bicep cache self-test interactive feedback"
                             " upgrade init find version survey".split())
_AZ_LOCAL_CALLS = (("account", "set"), ("account", "clear"), ("acr", "login"), ("devops", "configure"),
                   ("devops", "login"), ("devops", "logout"), ("cloud", "set"), ("cloud", "register"),
                   ("cloud", "unregister"), ("cloud", "update"), ("repos", "pr", "checkout"))
_AZ_REST_READS = frozenset({"get", "head", "options"})


def _az_writes(args: list[str], lead: list[str]) -> Optional[str]:
    """An az call that may change a live resource: its verb is no known read and it is no help probe, no call
    that changes only this machine; `az rest` with a method other than GET (its default)."""
    if not lead or _help_probe(args) or lead[0] in _AZ_LOCAL_GROUPS:
        return None
    if lead[0] == "rest":
        method = (_flag_value(args, {"--method", "-m"}) or "get").lower()
        return None if method in _AZ_REST_READS else f"`az rest --method {method}` changes resources"
    if len(lead) == 1:
        return None  # a group alone prints its help
    if any(tuple(lead[: len(call)]) == call for call in _AZ_LOCAL_CALLS):
        return None
    verb = lead[-1]
    if verb in _AZ_READ_VERBS or verb.startswith(_AZ_READ_PREFIXES):
        return None
    return f"`az {' '.join(lead)}` changes resources"


def _az_leading_words(args: list[str]) -> list[str]:
    """The plain words of an az call in front of the first option that follows a plain word (`webapp up` of
    `az --verbose webapp up --name x`): the group and the verb, not an option's value."""
    out: list[str] = []
    for t in args:
        if t.startswith("-"):
            if out:
                break
            continue  # options at the very start are skipped
        out.append(t)
    return out


def _help_probe(args: list[str]) -> bool:
    """A help word in front of the first `--`; behind it, it belongs to the command inside (`-- ls --help`)."""
    head = args[: args.index("--")] if "--" in args else args
    return bool(_NC_HELP & set(head))


def _ansible_runs(args: list[str], at_command_word: bool) -> bool:
    """A playbook run: as the command, any non-option word; elsewhere (uv run, npx, …) a .yml/.yaml word."""
    rest = drop_redirections(args)
    if at_command_word:
        return any(not t.startswith("-") for t in rest)
    return any(t.endswith((".yml", ".yaml")) for t in rest)


def _deploy_call(name: str, args: list[str], at_command_word: bool) -> Optional[str]:
    """The label when one call of a deploy tool changes a live environment, before the dry-run check."""
    verbs, pairs, label = _DEPLOY_TABLE[name]
    if name == "az":
        return _az_changes(args, at_command_word)
    if name == "ansible-playbook":
        return label if _ansible_runs(args, at_command_word) else None
    hit = subcommand_hit(args, verbs, pairs)
    if not hit:
        return _deploy_added(name, args, label)
    if hit == "s3 sync" and "--delete" not in args:
        return None
    return "aws s3 deletes" if name == "aws" and hit.startswith("s3 ") else label


def _deploy_added(name: str, args: list[str], label: str) -> Optional[str]:
    """The label when the 0.7.0 rows find a change; a help probe in front of the first `--` is none."""
    if name == "aws":
        hit = _aws_hit(args)
        label = ("aws deletes or terminates resources" if hit and hit.split()[1].startswith(_AWS_DESTROY)
                 else "aws updates a service or function")
    elif name in _DEPLOY_ADDED:
        hit = subcommand_hit(args, *_DEPLOY_ADDED[name])
    else:
        return None
    if not hit or _help_probe(args):
        return None
    if hit in _PUSH_ONLY and not any(t == "--push" or (t.startswith("--push=") and t[7:].lower() != "false")
                                     for t in args):
        return None  # a local build; with --push it publishes the image
    return label


def _aws_hit(args: list[str]) -> Optional[str]:
    """The words `service operation` when an aws call deletes, terminates or updates (_AWS_DESTROY,
    _AWS_UPDATES), or None.
    subcommand_hit's rule for options: a plain word after an option without `=` may be its value, so the word
    taken for the service may be one, and then the next plain word is the service."""
    service = ""
    service_may_be_value = may_be_value = False
    for t in drop_redirections(args):
        if t == "--" or t in _NC_HELP:
            return None
        if t.startswith("-") and len(t) > 1:
            may_be_value = "=" not in t
            continue
        if not service:
            service, service_may_be_value, may_be_value = t, may_be_value, False
            continue
        if t.startswith(_AWS_DESTROY) or t in _AWS_UPDATES.get(service, ()):
            return f"{service} {t}"
        if service_may_be_value:  # the service word was an option's value: this word is the service
            service, service_may_be_value, may_be_value = t, may_be_value, False
            continue
        if not may_be_value:
            return None
        may_be_value = False
    return None


def deploy_what(command: str) -> Optional[str]:
    """The label of the first deploy a command line would run, read from every simple command it runs, or None."""
    for toks in nested_commands(command):
        at_word = command_word_indexes(toks)
        named = 0
        for i, t in enumerate(toks):
            name = os.path.basename(t)
            if name not in _DEPLOY_TABLE:
                continue
            named += 1
            if named > _MAX_TOOL_WORDS:  # each call reads the rest of the line: bound the cost, ask instead
                raise CommandNotRead(_TOO_MANY_TOOLS)
            args = list(toks[i + 1 :])
            what = _deploy_call(name, args, i in at_word)
            if what and not _dry_run(name, args):
                return what
    return None


def rule_deploy_ask(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    pipe = None
    try:
        if _single_preview(ev.command):  # 0.9.0 (K5): `kubectl delete --help` as the whole line changes nothing
            return None
        text = strip_heredocs(ev.command)
        # the 0.6.0 verdict OR the token verdict; the reader takes the here-document bodies out itself (0.8.0)
        what = _deploy_text(text) or deploy_what(ev.command)
        pipe = _PIPE_NOT_READ if _unread_pipe(ev.command) else None  # read past it, asked for with the rest
    except CommandNotRead as exc:  # too deep or too many tools: ask rather than pass it unread
        what = str(exc)
    except Exception as exc:  # main() turns a crash into exit 1, which both harnesses let run silently: ask instead
        what = f"the command could not be read ({type(exc).__name__})"
    return combine([("ask", DEPLOY_MSG.format(what=w)) for w in (what, pipe) if w])


# ----------------------------------------------------------------------------
# egress-guard: inside a client boundary, other-vendor LLM tools need a yes
# ----------------------------------------------------------------------------

_OTHER_LLM_CLIS = {"agy", "gemini", "codex", "llm", "openai", "ollama", "aider", "cursor-agent",
                   "hf", "huggingface-cli"}  # 0.7.1: every call of the Hugging Face CLI, a download too
_LLM_HOSTS_RE = re.compile(
    r"api\.openai\.com|generativelanguage\.googleapis\.com|openrouter\.ai|api\.mistral\.ai|api\.together\.xyz|api\.anthropic\.com"
    # 0.7.1, Hugging Face: the inference router, dedicated endpoints, Spaces. The bare huggingface.co serves
    # downloads and stays out
    r"|router\.huggingface\.co|\.endpoints\.huggingface\.cloud|\.hf\.space"
    # 0.7.1: ten more inference APIs, each host read in the vendor's own docs on 2026-11-17
    r"|api\.together\.ai|api\.groq\.com|api\.deepseek\.com|api\.x\.ai|api\.cohere\.com|api\.fireworks\.ai"
    r"|api\.cerebras\.ai|api\.perplexity\.ai|api\.replicate\.com|api\.deepinfra\.com",
    re.IGNORECASE,  # 0.8.0: a host name is never case-sensitive (`API.OPENAI.COM`)
)
EGRESS_MSG = (
    "Client boundary (KZ_BOUNDARY=client): {what} would send material to another vendor's endpoint. "
    "Only the agreed endpoint; use the egress screen for anything that must leave the machine."
)


def rule_egress_guard(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    if str(cfg.get("boundary") or "own") != "client":
        return None
    text = strip_heredocs(ev.command)
    places = None  # K11: worked out once per line, at the first hit (F21: once per hit cost O(n^3))
    for seg in segments(text):
        d = _egress_seg(seg)
        if not d:
            continue
        if places is None:
            places = _pattern_places(text, ev.command)
        if not _only_in_search_patterns(places, seg):
            return d
    # 0.8.0: the full reading (not the local one): a container or another host still sends the data out
    return reader_pass(ev.command, _egress_seg, "egress-guard")


def _search_patterns(command: str) -> list[str]:
    """The pattern words of the search tools the reader finds in the line (grep and kin, `git grep`): the operand
    _search_pattern names, and the values of -e and --regexp. None are found in a line the reader cannot read."""
    out = []
    try:
        for toks in nested_commands(command):
            words = sorted(command_word_indexes(toks))
            for k in words:
                # F07: macOS finds `GREP` as grep (a case-insensitive file system, as fold_names reads it)
                name = tool_name(toks[k].lower())
                if name not in _SEARCH_TOOLS and name != "git":
                    continue
                if any(tool_name(toks[j].lower()) == "ssh" for j in words if j < k):
                    continue  # ssh hands its words to the remote shell unquoted: the bars there are pipes
                seg = list(toks)
                seg[k] = name
                idx, _files = _search_pattern(seg, k)
                if idx is not None:
                    out.append(toks[idx])
                for m in range(k + 1, len(toks)):
                    t = toks[m]
                    if t in ("-e", "--regexp") and m + 1 < len(toks):
                        out.append(toks[m + 1])
                    elif t.startswith("--regexp="):
                        out.append(t[len("--regexp=") :])
    except CommandNotRead:  # no patterns: every hit of the first pass keeps asking
        return []
    return out


def _pattern_places(text: str, command: str) -> tuple:
    """K11's reading of a line, once (F21): the spans of the quoted search patterns that hold a separator, merged
    and sorted, and for each segment the first pass gives, the places (start, end) of its first word in the parts
    of the line that give it."""
    spans = []
    for p in set(_search_patterns(command)):
        if not _SEP_RE.search(p):
            continue
        for q in ("'", '"'):
            start = text.find(q + p + q)
            while start >= 0:
                spans.append((start + 1, start + 1 + len(p)))
                start = text.find(q + p + q, start + 1)
    merged: list = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    where: dict = {}
    if merged:
        pos = 0
        for m in [*_SEP_RE.finditer(text), None]:
            end = m.start() if m else len(text)
            part = text[pos:end]
            segs = _segments_cached(part)
            if len(segs) == 1:
                # F08: the place of the segment's first word (the part behind the last bar runs on past the closing
                # quote, `'a|openai api' notes.txt`); a first word the part does not hold as written (quotes taken
                # out) is read as the whole part
                at = part.find(segs[0][0]) if segs[0] else -1
                place = (pos + at, pos + at + len(segs[0][0])) if at >= 0 else (pos, end)
                where.setdefault(segs[0], []).append(place)
            pos = m.end() if m else end
    return [a for a, _ in merged], [b for _, b in merged], where


def _only_in_search_patterns(places: tuple, seg: list[str]) -> bool:
    """Group C (K11, the owner's answer of 2026-11-18): the first pass splits the line at every `|`, also inside a
    quoted word, so the words of a quoted search pattern (`grep -E 'a|openai|b'`) look like a command. A hit is
    dropped when, at every place of the line that gives this segment, its first word lies inside such a pattern,
    written between a pair of quotes; a hit anywhere else keeps asking, and the reader pass still reads every real
    command."""
    starts, ends, where = places
    key = tuple(seg)
    found = where.get(key)
    if not isinstance(found, list):  # judged before on this line (the same segment repeats), or never placed
        return bool(found)
    inside = True
    for a, b in found:
        i = bisect.bisect_right(starts, a) - 1
        if i < 0 or b > ends[i]:
            inside = False
            break
    where[key] = inside  # one verdict per segment and line (F21)
    return inside


def _egress_seg(seg: list[str]) -> Optional[Decision]:
    """The egress-guard verdict on the words from one command word: another vendor's LLM tool, or an HTTP
    client with an LLM API host among its words."""
    head = os.path.basename(seg[0])
    if head in _OTHER_LLM_CLIS:
        return "ask", EGRESS_MSG.format(what=f"`{head}`")
    if head in ("curl", "wget", "http", "https", "xh") and _LLM_HOSTS_RE.search(" ".join(seg)):
        return "ask", EGRESS_MSG.format(what=f"`{head}` to an LLM API host")
    return None

# ----------------------------------------------------------------------------
# scratch-md: a NEW markdown file outside the documented homes is a smell (plan step 1.5)
# ----------------------------------------------------------------------------


def git_root(start_dir: str) -> Optional[str]:
    d = os.path.abspath(start_dir)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


SCRATCH_MSG = (
    "Scratch-markdown guard: {rel} would be a new .md outside the documented homes ({homes}, …). "
    "Findings belong in the reply, the PR body or the tracker; documentation goes under docs/. "
    "Say yes only if this file is meant to stay."
)


def rule_scratch_md(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "write":
        return None
    mode = str(cfg.get("scratch_md_mode") or "ask")
    if mode == "off":
        return None
    p = ev.abspath()
    if not p or not p.lower().endswith((".md", ".markdown")) or os.path.exists(p):
        return None
    root = git_root(os.path.dirname(p))
    if root is None:
        return None
    rel = os.path.relpath(p, root).replace(os.sep, "/")
    allow = cfg.get("scratch_md_allow") or DEFAULTS["scratch_md_allow"]
    base = os.path.basename(rel)
    for pat in allow:
        if pat.endswith("/") and rel.startswith(pat):
            return None
        if pat.startswith("**/") and base == pat[3:]:
            return None
        if rel == pat:
            return None
    verdict = "deny" if mode == "deny" else "ask"
    return verdict, SCRATCH_MSG.format(rel=rel, homes=", ".join(allow[:4]))


# ----------------------------------------------------------------------------
# protected-branch: no edits and no commits on a protected branch (plan step 2.2)
# ----------------------------------------------------------------------------

PROTECTED_MSG = (
    "protected-branch: {what} on '{branch}' ({root}). Work on a branch (git switch -c <step>) and open a PR; "
    "the protected set comes from .claude/guard.json."
)


def _git_c_dir(seg: list[str], cwd: str) -> str:
    """Directory a `git -C <dir> …` call runs in; cwd when no -C is given."""
    for i, t in enumerate(seg[:-1]):
        if t == "-C":
            return _expand(seg[i + 1], cwd)
        if t.startswith("-C") and len(t) > 2:
            return _expand(t[2:], cwd)
    return cwd


def rule_protected_branch(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse":
        return None
    protected = protected_branches(cfg)
    if not protected:
        return None
    if ev.kind in ("write", "edit"):
        p = ev.abspath()
        if not p or ".git" in p.split(os.sep):
            return None
        root = git_root(os.path.dirname(p))
        if root is None:
            return None
        branch = current_branch(root)
        if branch in protected:
            rel = os.path.relpath(p, root)
            return "deny", PROTECTED_MSG.format(what=f"edit of {rel}", branch=branch, root=root)
        return None
    if ev.kind == "shell" and ev.command:
        command = strip_heredocs(ev.command)
        asks = []  # 0.9.0: `git update-ref --stdin` asks; a later deny of the line still wins
        for seg in segments(command):
            d = _commit_on_protected(seg, ev.cwd, protected)
            if d and d[0] == "deny":
                return d
            if d:
                asks.append(d)

        # the local reading: a commit behind ssh or inside a container happens in another checkout
        def judge(seg: list[str]) -> Optional[Decision]:
            return _commit_on_protected(seg, ev.cwd, protected)

        return combine(asks + [d for d in (reader_pass(ev.command, judge, "protected-branch", local=True, net=judge),)
                               if d])
    return None


def _commit_on_protected(seg: list[str], cwd: str, protected: set) -> Optional[Decision]:
    """Deny when one simple command is a `git commit` in a checkout whose branch is protected, or a `git
    update-ref` that moves or deletes a protected branch (0.9.0)."""
    sub, rest = _git_subcommand(seg)
    if sub == "update-ref":
        return _update_ref_on_protected(seg, rest, cwd, protected)
    if sub != "commit":
        return None
    where = _git_c_dir(seg, cwd)
    branch = current_branch(where)
    if branch in protected:
        return "deny", PROTECTED_MSG.format(what="`git commit`", branch=branch, root=where)
    return None


UPDATE_REF_STDIN_MSG = ("protected-branch: `git update-ref --stdin` takes the refs it moves from its input, which "
                        "the guard cannot read. Confirm the command.")


def _update_ref_on_protected(seg: list[str], rest: list[str], cwd: str, protected: set) -> Optional[Decision]:
    """`git update-ref` (decision ab): deny for `refs/heads/<protected>` whatever is checked out, and for `HEAD`
    while a protected branch is; `-d` of such a ref too. `--stdin` asks. The ref is the first operand; `-m`
    takes a value (git-update-ref(1), git 2.4x)."""
    if "--stdin" in rest:
        return "ask", UPDATE_REF_STDIN_MSG
    operands = [t for k, t in enumerate(rest) if not t.startswith("-") and not (k and rest[k - 1] == "-m")]
    if not operands:
        return None
    ref = operands[0]
    where = _git_c_dir(seg, cwd)
    # F18: on a file system that ignores case (APFS, NTFS) the ref is one file under every spelling (measured,
    # git 2.55: `git update-ref REFS/HEADS/MAIN` moves main), so the name is compared without case
    name = ref[len("refs/heads/"):] if ref.lower().startswith("refs/heads/") else None
    if name is None and ref == "HEAD":
        name = current_branch(where)
    name = next((p for p in protected if name is not None and p.lower() == name.lower()), name)
    if name in protected:
        return "deny", PROTECTED_MSG.format(what=f"`git update-ref {ref}` moves the branch", branch=name, root=where)
    return None


# ----------------------------------------------------------------------------
# fan-out: log every spawn; ask at the 6th and every 10 after (plan step 2.3)
# ----------------------------------------------------------------------------

FANOUT_FIRST, FANOUT_EVERY = 6, 10
LLAMA_PORT = 8012
FANOUT_MSG = (
    "Fan-out guard: spawn #{n} in this session (a prompt at #{first}, then every {every}). "
    "Cost guardrails: one shared brief, <=5 agents, no two agents with the same job. Continue?{llama}"
)
LLAMA_NOTE = " llama-server is up on :{port} (39 GB of RAM in use): parallel agents will swap."


def spawn_log_path(cfg: dict) -> str:
    return os.path.join(telemetry_dir(cfg), "spawns.jsonl")


def log_spawn(ev: Event, cfg: dict) -> int:
    """Append one line to the spawn log; return how many PreToolUse spawns this session has, this one included."""
    entry = {
        "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": ev.event,
        "harness": ev.harness,
        "session": ev.session,
        "agent": _first_str(ev.args, "subagent_type", "agent_type", "agent", "name") or ev.raw.get("agent_type"),
        "model": _first_str(ev.args, "model"),
        "agent_id": ev.raw.get("agent_id"),
        "cwd": ev.cwd,
    }
    path = spawn_log_path(cfg)
    count = 0
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("session") == ev.session and row.get("event") == "PreToolUse":
                        count += 1
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"guard: spawn log failed: {exc}", file=sys.stderr)
    return count + 1 if ev.event == "PreToolUse" else count


def llama_server_up(port: int = LLAMA_PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def rule_fan_out(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event == "SubagentStart":
        log_spawn(ev, cfg)
        return None
    if ev.event != "PreToolUse" or ev.kind != "spawn":
        return None
    n = log_spawn(ev, cfg)
    if n < FANOUT_FIRST or (n - FANOUT_FIRST) % FANOUT_EVERY:
        return None
    llama = LLAMA_NOTE.format(port=LLAMA_PORT) if llama_server_up() else ""
    return "ask", FANOUT_MSG.format(n=n, first=FANOUT_FIRST, every=FANOUT_EVERY, llama=llama)


# ----------------------------------------------------------------------------
# guard-config: changing the guard or its wiring needs a human yes (plan step 2.1)
# ----------------------------------------------------------------------------

_SETTINGS_RE = re.compile(r"^settings(\..+)?\.json$")
# the files below tools/ that enforce a rule (0.10.0: the commit gate, the test guard, the tag scan, the tracker)
_GUARDED_TOOLS = {"guard": "the guard itself", "testguard": "the test guard", "scan": "the tag scan",
                  "tracker": "the tracker", "commit_msg.py": "the commit message gate"}
GUARD_CONFIG_MSG = (
    "Guard-the-guard: {path} is {what}; it polices this very session, so a human confirms every change "
    "(and AGENTS.md rule 4 wants the why in DECISIONS.md)."
)


def guard_config_class(path: Optional[str]) -> Optional[str]:
    """What kind of hook configuration a path is, or None for an ordinary file. 0.9.0: read as written and in
    lower case, as secret_class reads a path since 0.8.0 (the owner's file system ignores case); the home prefix
    is compared the same way."""
    if not path:
        return None
    home_claude = os.path.join(os.path.expanduser("~"), ".claude")
    return (_guard_config_as_written(path, home_claude)
            or _guard_config_as_written(path.lower(), home_claude.lower()))


def _guard_config_as_written(path: str, home_claude: str) -> Optional[str]:
    """guard_config_class for one reading of the path."""
    if path.startswith(home_claude + os.sep):
        rest = path[len(home_claude) + 1 :].split(os.sep)
        if rest[0] == "hooks" or (len(rest) == 1 and _SETTINGS_RE.match(rest[0])):
            return "user-scope hook configuration"
    parts = path.split(os.sep)
    for i, part in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        last = i + 1 == len(parts) - 1
        if part == ".claude" and last and (_SETTINGS_RE.match(nxt) or nxt in ("guard.json", "guard.local.json")):
            return "the repo's hook configuration"
        if part == ".github" and nxt == "hooks":
            return "the repo's Copilot hook configuration"
        if part == ".github" and nxt == "workflows" and not last:
            return "a CI workflow"
        if part == "tools" and nxt in _GUARDED_TOOLS and (nxt != "commit_msg.py" or last):
            return _GUARDED_TOOLS[nxt]
    return None


def rule_guard_config(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse":
        return None
    if ev.kind == "shell" and ev.command:
        return _guard_config_shell(ev)
    if ev.kind not in ("write", "edit"):
        return None
    what = guard_config_class(ev.abspath())
    if what is None:
        return None
    return "ask", GUARD_CONFIG_MSG.format(path=ev.path, what=what)


# 0.10.0 (item #65, D7): shell writes to the same paths ask, as Write and Edit do. Named limits: a branch switch,
# merge, pull, rebase or stash that changes these files; a patch whose target is not on the line; obfuscated code.
GUARD_CONFIG_SHELL_MSG = (
    "Guard-the-guard: `{head}` writes {path}, which is {what}; it polices this very session, so a human confirms "
    "every change (and AGENTS.md rule 4 wants the why in DECISIONS.md)."
)
_GC_REDIRECT_RE = re.compile(r"(?<![<>])>{1,2}\|?\s*([^\s;&|]+)")
_GC_DIFF_HEADER_RE = re.compile(r"^(?:\+\+\+|---) (?:[ab]/)?(\S+)", re.MULTILINE)
_GC_INLINE = {"python": "-c", "node": "-e", "perl": "-e", "ruby": "-e"}
_GC_WRITE_WORDS = ("'w'", '"w"', "'a'", '"a"', "write", "rename", "replace", "unlink", "remove", "copy", "move",
                   "symlink", "chmod")
_GC_PATH_RE = re.compile(r"[\w.~/$-]+")


def _gc_class(path: str, cwd: str, below: bool = False) -> Optional[str]:
    """guard_config_class of a word as the shell names a file; `below`: a directory a file is written into."""
    full = _expand(path.strip("\"'`,;)"), cwd)
    return guard_config_class(full) or (guard_config_class(os.path.join(full, "x")) if below else None)


def _gc_operands(args: list[str]) -> list[str]:
    return [t for t in args if not t.startswith("-") and t != "--"]


def _gc_targets(seg: list[str]) -> list[tuple]:
    """(word, below) for each file one simple command writes, as far as its words say."""
    head = tool_name(seg[0])
    args = seg[1:]
    ops = _gc_operands(args)
    if head in _WRITERS_LAST:
        for k, t in enumerate(args):
            if t in ("-t", "--target-directory") and k + 1 < len(args):
                return [(args[k + 1], True)]
            if t.startswith("--target-directory="):
                return [(t.split("=", 1)[1], True)]
        return [(ops[-1], True)] if len(ops) > 1 else []
    if head in _WRITERS_ALL:
        return [(t, False) for t in ops]
    if head == "dd":
        return [(t[3:], False) for t in args if t.startswith("of=")]
    if head == "sed" and any(t.startswith("-i") or t.startswith("--in-place") for t in args):
        return [(t, False) for t in ops]
    if head == "perl" and any(re.match(r"^-[a-zA-Z]*i", t) for t in args):
        return [(t, False) for t in ops]
    if head in ("curl", "wget"):
        names = ("-o", "--output") if head == "curl" else ("-O", "--output-document")
        out = []
        for k, t in enumerate(args):
            if t in names and k + 1 < len(args):
                out.append((args[k + 1], False))
            elif t.startswith(tuple(n + "=" for n in names[1:])):
                out.append((t.split("=", 1)[1], False))
            elif t.startswith(names[0]) and len(t) > 2 and not t.startswith("--"):
                out.append((t[2:], False))
        return out
    if head == "patch":
        return [(t, False) for t in ops]
    if head == "git":
        sub, rest = _git_subcommand(seg)
        if sub == "apply":
            return [(t, False) for t in _gc_operands(rest)]
        if sub == "checkout" and "--" in rest:
            return [(t, True) for t in rest[rest.index("--") + 1 :]]
        if sub == "restore" and not _restore_index_only(rest):
            out = []
            for k, t in enumerate(rest):
                if t.startswith("-") or t == "--" or (k and rest[k - 1] in ("-s", "--source")):
                    continue
                out.append((t, True))
            return out
    key = "python" if _PYTHON_RE.match(head) else head
    if key in _GC_INLINE:
        opt = _GC_INLINE[key]
        for k, t in enumerate(args[:-1]):
            code = args[k + 1]
            if t == opt and any(w in code for w in _GC_WRITE_WORDS):
                return [(p, False) for p in _GC_PATH_RE.findall(code) if "/" in p]
    return []


def _guard_config_shell(ev: Event) -> Optional[Decision]:
    hits: list[tuple] = []  # (path, class, head)
    command = strip_heredocs(ev.command)
    for target in _GC_REDIRECT_RE.findall(command.replace("\\\n", "")):
        what = _gc_class(target, ev.cwd)
        if what:
            hits.append((target.strip("\"'`,;)"), what, ">"))

    def judge(seg: list[str]) -> Optional[Decision]:
        head = tool_name(seg[0])
        for word, below in _gc_targets(seg):
            what = _gc_class(word, ev.cwd, below)
            if what:
                hits.append((word, what, head))
        if head == "patch" or (head == "git" and _git_subcommand(seg)[0] == "apply"):
            for word in _GC_DIFF_HEADER_RE.findall(ev.command):  # the patch in a here-document
                what = _gc_class(word, ev.cwd)
                if what:
                    hits.append((word, what, head))
        return None

    failed = reader_pass(ev.command, judge, "guard-config")
    if hits:
        path, what, head = hits[0]
        return "ask", GUARD_CONFIG_SHELL_MSG.format(head=head, path=path, what=what)
    return failed


# ----------------------------------------------------------------------------
# tracker-guard: issues and labels change only through the tracker verbs (plan step 2.6)
# ----------------------------------------------------------------------------

_GH_ISSUE_REPLACEMENT = {
    "create": "`tracker new --title ... --ac ... --scope ... --scope-limit ... --source ...`",
    "edit": "`tracker claim|block|review` for status labels; bodies are frozen after ready",
    "comment": "`tracker note N \"text\"`",
    "close": "`tracker owner done N` (a human runs it)",
    "reopen": "`tracker owner ready N` (a human runs it)",
    "delete": "nothing: issues are never deleted",
    "transfer": "nothing: ask the owner",
    "pin": "nothing: ask the owner",
    "unpin": "nothing: ask the owner",
    "lock": "nothing: ask the owner",
    "unlock": "nothing: ask the owner",
    "develop": "`tracker claim N --branch <branch>`",
}
_GH_API_MUTATING_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}
_GH_API_VALUE_FLAGS = _GH_API_MUTATING_FLAGS | {"-X", "--method", "-H", "--header", "-q", "--jq", "-t", "--template",
                                                "--hostname", "-p", "--preview", "--cache"}
_CURL_MUTATING_FLAGS = {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json", "-T",
                        "--upload-file", "--post-data", "--post-file"}
_ISSUE_API_RE = re.compile(r"(^|/)repos/[^/\s]+/[^/\s]+/(issues|labels)(/|$|\?)")
TRACKER_MSG = "tracker-guard: {what}. Use {use}; the tracker is the only writer of issues and labels."
# Azure DevOps: work items are the issues, tags the labels; any host, so Azure DevOps Server paths count too
_AZ_WORK_ITEM_REPLACEMENT = {
    "create": _GH_ISSUE_REPLACEMENT["create"],
    "update": "`tracker claim|block|review` for status tags, `tracker note N \"text\"` for comments; "
              "bodies are frozen after ready",
    "delete": _GH_ISSUE_REPLACEMENT["delete"],
    "relation": "nothing: ask the owner",
}
_AZ_RELATION_READS = {"show", "list-type"}
_ADO_WIT_RE = re.compile(r"/_apis/wit(/|\?|$)", re.IGNORECASE)
_BYPASS_RULES_RE = re.compile(r"bypassRules\s*=\s*true|--bypass-rules\b", re.IGNORECASE)
_HTTP_VERBS = {"POST", "PATCH", "PUT", "DELETE"}
_HTTPIE_SEP_RE = re.compile(r":=|==|=|:|@")  # httpie/xh request items: the first separator decides the kind


def _flag_value(seg: list[str], names: set) -> Optional[str]:
    for i, t in enumerate(seg):
        if t in names and i + 1 < len(seg):
            return seg[i + 1]
        for n in names:
            if t.startswith(n + "="):
                return t[len(n) + 1 :]
    return None


def _az_flag_on(seg: list[str], name: str) -> bool:
    """An az three-state flag is on when given bare or with any value but `false`."""
    for i, t in enumerate(seg):
        if t == name:
            return (seg[i + 1] if i + 1 < len(seg) else "").lower() != "false"
        if t.startswith(name + "="):
            return t[len(name) + 1 :].lower() != "false"
    return False


# 0.9.0: a merge of a pull request is the owner's call; `--admin` skips the branch protection
_MERGE_API_RE = re.compile(r"(^|/)repos/[^/\s]+/[^/\s]+/pulls/\d+/merge/?($|\?)")
MERGE_ASK_MSG = "tracker-guard: {what} merges a pull request, which is the owner's call. Confirm the command."
APPROVE_ASK_MSG = ("tracker-guard: {what} approves a pull request, and an approval counts as a person's, which is the "
                   "owner's call. Confirm the command.")


def _http_method(seg: list[str]) -> str:
    """The method a curl, wget or httpie call names (`-X PUT`, `-XPUT`, `--method=PUT`, httpie's `PUT`), or ""."""
    method = (_flag_value(seg, {"-X", "--request", "--method"}) or "").upper()
    if not method:  # curl -XPATCH
        method = next((t[2:].upper() for t in seg[1:] if t.startswith("-X") and len(t) > 2), "")
    curl = os.path.basename(seg[0]) in ("curl", "wget")
    # F17: curl(1), curl 8: `-T, --upload-file` "this uses PUT" on HTTP, unless -X names another method
    if not method and os.path.basename(seg[0]) == "curl" and any(
            t == "-T" or t == "--upload-file" or t.startswith("--upload-file=") or (t.startswith("-T") and len(t) > 2)
            for t in seg[1:]):
        method = "PUT"
    if not method and not curl:  # F17: httpie takes the method word in any case (`http put …` sends PUT)
        method = next((t.upper() for t in seg[1:] if t.upper() in _HTTP_VERBS), "")
    return method


_GITHUB_API_RE = re.compile(r"api\.github\.com\.?(?::\d+)?(/[^\s?#]*)", re.IGNORECASE)


def _github_api_path(word: str) -> Optional[str]:
    """The path a word names on GitHub's REST host, slashes doubled up taken as one, or None (F17: a second
    slash, `api.github.com//repos/…`, and the dot of the root zone, `api.github.com./repos/…`, reach the same
    API; `api.github.com.evil.example` is another host; second fix round: so does a port, `api.github.com:443`)."""
    m = _GITHUB_API_RE.search(word)
    return re.sub(r"/+", "/", m.group(1)) if m else None


def _http_writes(seg: list[str], head: str, url: str) -> bool:
    """curl/wget/httpie/xh: an explicit write method, a data flag, or httpie's implicit POST (data items)."""
    method = (_flag_value(seg, {"-X", "--request", "--method"}) or "").upper()
    if not method:  # curl -XPATCH
        method = next((t[2:].upper() for t in seg[1:] if t.startswith("-X") and len(t) > 2), "")
    if method in _HTTP_VERBS:
        return True
    if any(t.split("=", 1)[0] in _CURL_MUTATING_FLAGS or t.startswith("--data") or t[:2] == "-d" for t in seg[1:]):
        return True  # `--data-raw=x`, `-d@body.json` and `--post-data=x` count like their spaced forms
    if head in ("curl", "wget"):
        return False
    if any(t.upper() in _HTTP_VERBS for t in seg[1:]):
        return True
    for t in seg[1:]:
        if t == url or t.startswith("-") or "://" in t:
            continue
        m = _HTTPIE_SEP_RE.search(t)
        if m and m.group(0) in (":=", "=", "@"):  # `field=v`, `field:=json`, `field@file`; `H:v` and `q==v` are reads
            return True
    return False


_AZ_GLOBAL_FLAGS = {"--debug", "--verbose", "--only-show-errors"}
_AZ_GLOBAL_VALUED = {"-o", "--output", "--query", "--subscription", "--org", "--organization", "-p", "--project",
                     "--detect"}


def _az_words(seg: list[str]) -> list[str]:
    """The az command words. az accepts its global options before the command (`az -o json devops invoke`),
    so those are skipped, with their value; the walk stops at the first other option."""
    words: list[str] = []
    skip = False
    for t in seg[1:]:
        if skip:
            skip = False
        elif t in _AZ_GLOBAL_VALUED:
            skip = True
        elif t.startswith("-"):
            if t not in _AZ_GLOBAL_FLAGS and t.split("=", 1)[0] not in _AZ_GLOBAL_VALUED:
                break
        else:
            words.append(t)
    return words


def _az_tracker_guard(seg: list[str]) -> Optional[Decision]:
    """`az boards work-item` writes, `az devops invoke`, `az rest` writes to _apis/wit, PR completion shortcuts."""
    words = _az_words(seg)
    if words[:2] == ["boards", "work-item"] and words[2:3] and words[2] in _AZ_WORK_ITEM_REPLACEMENT:
        if words[2] == "relation" and words[3:4] and words[3] in _AZ_RELATION_READS:
            return None
        return "deny", TRACKER_MSG.format(what=f"`az boards work-item {words[2]}` bypasses the tracker",
                                          use=_AZ_WORK_ITEM_REPLACEMENT[words[2]])
    if words[:2] == ["devops", "invoke"]:
        return "deny", TRACKER_MSG.format(what="`az devops invoke` is a generic REST writer",
                                          use="the tracker verbs (reads: `tracker list|show`)")
    if words[:1] == ["rest"]:
        uri = _flag_value(seg, {"--uri", "--url", "-u"}) or ""
        method = (_flag_value(seg, {"--method", "-m"}) or "GET").upper()
        body = any(t in ("--body", "-b") or t.startswith("--body=") for t in seg)
        if _ADO_WIT_RE.search(uri) and (method in _HTTP_VERBS or body):
            return "deny", TRACKER_MSG.format(what=f"`az rest {method}` writes work items at {uri}",
                                              use="the tracker verbs")
    if words[:2] == ["repos", "pr"] and words[2:3] in (["create"], ["update"]):
        verb = f"az repos pr {words[2]}"
        if (_flag_value(seg, {"--status"}) or "").lower() == "completed":
            return "deny", TRACKER_MSG.format(what=f"`{verb} --status completed` merges behind the tracker",
                                              use="the web UI (a human completes the PR), then `tracker owner done N`")
        if _az_flag_on(seg, "--transition-work-items"):
            return "deny", TRACKER_MSG.format(what=f"`{verb} --transition-work-items` moves work items on merge",
                                              use="`tracker owner done N` (a human runs it); pass "
                                                  "`--transition-work-items false`")
        if _az_flag_on(seg, "--bypass-policy"):
            return "deny", TRACKER_MSG.format(what=f"`{verb} --bypass-policy` skips the branch policies",
                                              use="nothing: policies are never bypassed; ask the owner")
    return None


def rule_tracker_guard(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    command = strip_heredocs(ev.command)
    if _BYPASS_RULES_RE.search(command):
        return "deny", TRACKER_MSG.format(what="`bypassRules` skips the work item rules",
                                          use="the tracker verbs; process rules are never bypassed")
    asks = []  # 0.9.0: the first pass can ask (a GraphQL mutation); a later deny of the line still wins
    for seg in segments(command):
        d = _tracker_seg(seg)
        if d and d[0] == "deny":
            return d
        if d:
            asks.append(d)
    # the reader takes the bodies out (0.8.0); the net reads a gh or az behind an unknown word (0.9.0)
    return combine(asks + [d for d in (reader_pass(ev.command, _tracker_seg, "tracker-guard", net=_tracker_seg),)
                           if d])


def _gh_words(seg: list[str]) -> list[int]:
    """The indexes of the first two plain words of a gh call (the command group and the verb). gh accepts
    `-R`/`--repo` before the group and between group and verb (`gh -R o/r issue close 3`, `gh issue --repo o/r
    close 3`); its value is skipped in every spelling: `-R v`, `-Rv`, `--repo v`, `--repo=v` (0.8.0)."""
    out: list[int] = []
    k = 1
    while k < len(seg) and len(out) < 2:
        t = seg[k]
        if t in ("-R", "--repo"):
            k += 1  # the value is the next word
        elif not t.startswith("-"):
            out.append(k)
        k += 1
    return out


def _gh_api_mutating(t: str) -> bool:
    """A gh api write flag in any spelling gh accepts: `-f k=v`, `-fk=v`, `-F…`, `--field=k=v`, `--raw-field=…`,
    `--input v`, `--input=v` (gh api --help)."""
    return (t in _GH_API_MUTATING_FLAGS or t.startswith(("--field=", "--raw-field=", "--input="))
            or (t[:2] in ("-f", "-F") and len(t) > 2))


# 0.9.0 (decision aa): GitHub's GraphQL endpoint. A mutation whose field names an issue or a label is the REST
# write's twin and is denied; any other mutation, and a query the line does not hold, asks; a query is a read
# second fix round: the host with the dot of the root zone or a port, and a doubled slash, as _GITHUB_API_RE has it
_GRAPHQL_URL_RE = re.compile(r"api\.github\.com\.?(?::\d+)?/+graphql(?![\w.-])", re.IGNORECASE)
_GRAPHQL_TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|[{}()]|[A-Za-z_][A-Za-z0-9_]*')
_GRAPHQL_TRACKER_RE = re.compile(r"Issue|Label")
GRAPHQL_ASK_MSG = "tracker-guard: {what}. Confirm the command; the tracker is the only writer of issues and labels."


def _graphql_fields(query: str) -> Optional[list]:
    """The field names at the top of each `mutation` operation of a GraphQL document, or None when it holds no
    mutation. A word at brace depth 1 outside parentheses is a field (or its alias)."""
    m = re.search(r"\bmutation\b", query)
    if not m:
        return None
    fields: list[str] = []
    depth = parens = 0
    for tok in _GRAPHQL_TOKEN_RE.findall(query, m.start()):
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
        elif tok == "(":
            parens += 1
        elif tok == ")":
            parens -= 1
        elif depth == 1 and parens == 0 and not tok.startswith('"'):
            fields.append(tok)
    return fields


def _graphql_verdict(query: Optional[str], via: str) -> Optional[Decision]:
    """The verdict on a GraphQL document sent by `via`; None as the document means the line does not hold it."""
    if query is None:
        return "ask", GRAPHQL_ASK_MSG.format(what=f"`{via}` sends a GraphQL document the guard cannot read")
    fields = _graphql_fields(query)
    if fields is None:
        return None
    hit = next((f for f in fields if _GRAPHQL_TRACKER_RE.search(f)), None)
    if hit:
        return "deny", TRACKER_MSG.format(what=f"`{via}` mutation `{hit}` writes issues or labels",
                                          use="the tracker verbs")
    named = f" `{fields[0]}`" if fields else ""
    return "ask", GRAPHQL_ASK_MSG.format(what=f"`{via}` sends the GraphQL mutation{named}")


def _graphql_value(value: str) -> Optional[str]:
    """The document a field value holds, or None when the line does not show it: a file (`@q.graphql`), a value
    that starts with `$` (a variable, a command substitution, or `$'…'`, whose escapes the words no longer show:
    F05) or with a backtick."""
    if value.lstrip().startswith(("@", "$", "`")):
        return None
    return value


def _graphql_join(values: list) -> tuple:
    """(found, document) from the query values of one call: every one is read (F05), and one the line does not
    show makes the whole document unknown."""
    if not values:
        return False, None
    if any(v is None for v in values):
        return True, None
    return True, "\n".join(values)


def _gh_graphql_path(path: str) -> bool:
    """`gh api` reaches the GraphQL API as `graphql`, `/graphql` or with the host (measured, gh 2.92.0); slashes
    doubled up are taken as one, as for the merge path."""
    flat = re.sub(r"/+", "/", path)
    return flat.lower().rstrip("/") in ("graphql", "/graphql") or bool(_GRAPHQL_URL_RE.search(path))


def _gh_graphql_query(seg: list[str], start: int) -> tuple:
    """(found, document) of `gh api graphql`: the values of its `query` fields in every spelling of gh's field
    flags (`-f query=…`, `-fquery=…`, `--raw-field=query=…`); `--input` sends a file and the fields go
    (measured, gh 2.92.0), read as no document."""
    values: list = []
    k = start
    while k < len(seg):
        t = seg[k]
        if t == "--input" or t.startswith("--input="):
            return True, None
        value = None
        if t in ("-f", "-F", "--field", "--raw-field") and k + 1 < len(seg):
            value, k = seg[k + 1], k + 1
        elif t.startswith(("--field=", "--raw-field=")):
            value = t.split("=", 1)[1]
        elif t[:2] in ("-f", "-F") and len(t) > 2:
            value = t[2:]
        if value is not None and value.startswith("query="):
            values.append(_graphql_value(value[len("query="):]))
        k += 1
    return _graphql_join(values)


def _http_graphql_query(seg: list[str], head: str) -> tuple:
    """(found, document) of a curl, wget or httpie call: the `query` of the JSON body, or of httpie's `query=`
    item; a body from a file or one that is no JSON with a query is read as no document. Addendum: httpie's
    `--raw` is a body, and an httpie call that shows no document sends its standard input (never a terminal in
    an agent's shell), so it is found with no document; wget's `--body-data` and `--body-file` are its
    `--post-data` and `--post-file`."""
    bodies = []
    values: list = []
    httpie = head not in ("curl", "wget")
    for k, t in enumerate(seg[1:], 1):
        name, eq, value = t.partition("=")
        if name in ("-T", "--upload-file", "--post-file", "--body-file"):
            return True, None  # the body is a file
        if (name in _CURL_MUTATING_FLAGS or name == "--body-data" or t.startswith("--data")
                or (httpie and name == "--raw")):
            bodies.append(value if eq else (seg[k + 1] if k + 1 < len(seg) else ""))
        elif t[:2] == "-d" and len(t) > 2:
            bodies.append(t[2:])
        elif httpie and name == "query" and eq:
            values.append(_graphql_value(value))
        elif httpie and name == "query:" and eq:
            # F05: httpie's `query:=…` is raw JSON (httpie 3, "Raw JSON fields"); a string is the document
            try:
                raw = json.loads(value)
            except (ValueError, RecursionError):  # no JSON the guard can read: the document is not known
                raw = None
            values.append(raw if isinstance(raw, str) else None)
    if values:
        return _graphql_join(values)
    for body in bodies:
        if body.startswith("@"):
            return True, None
        try:
            doc = json.loads(body)
        except (ValueError, RecursionError):  # no JSON the guard can read: it cannot tell what the server reads
            return True, None
        query = doc.get("query") if isinstance(doc, dict) else None
        return True, query if isinstance(query, str) else None
    return httpie, None  # httpie sends its standard input or a file (`@q.json`); curl and wget send nothing


def _tracker_seg(seg: list[str]) -> Optional[Decision]:
    """The tracker-guard verdict on one simple command: a write to issues, labels or work items past the tracker."""
    head = os.path.basename(seg[0])
    if head == "az":
        d = _az_tracker_guard(seg)
        if d:
            return d
    at = _gh_words(seg) if head == "gh" else []
    group, verb = ([seg[k] for k in at] + ["", ""])[:2]
    if group == "issue" and verb in _GH_ISSUE_REPLACEMENT:
        return "deny", TRACKER_MSG.format(what=f"`gh issue {verb}` bypasses the tracker",
                                          use=_GH_ISSUE_REPLACEMENT[verb])
    if group == "pr" and verb == "merge" and not _help_probe(seg):
        if any(t == "--admin" or (t.startswith("--admin=") and t[8:].lower() != "false") for t in seg):
            return "deny", TRACKER_MSG.format(what="`gh pr merge --admin` bypasses the branch protection",
                                              use="a merge the protection allows, by the owner")
        return "ask", MERGE_ASK_MSG.format(what="`gh pr merge`")
    if group == "pr" and verb == "review" and ("--approve" in seg or "-a" in seg) and not _help_probe(seg):
        return "ask", APPROVE_ASK_MSG.format(what="`gh pr review --approve`")
    if group == "label" and verb in ("create", "edit", "delete", "clone"):
        return "deny", TRACKER_MSG.format(what=f"`gh label {verb}` bypasses the tracker",
                                          use="`tracker owner labels-sync` (a human runs it)")
    if group == "api":
        path, skip = "", False
        for t in seg[at[0] + 1 :]:
            if skip:
                skip = False
            elif t in _GH_API_VALUE_FLAGS:
                skip = True
            elif not t.startswith("-"):
                path = t
                break
        method = _flag_value(seg, {"-X", "--method"})
        if method is None:  # `-XPATCH`: the value glued on
            method = next((t[2:] for t in seg[at[0] + 1 :] if t.startswith("-X") and len(t) > 2), "GET")
        method = method.upper()
        if _gh_graphql_path(path):
            found, doc = _gh_graphql_query(seg, at[0] + 1)
            d = _graphql_verdict(doc, "gh api graphql") if found else None
            if d:
                return d
        # second fix round: `repos/o/r/pulls//3/merge` is the same path, as curl's merge path reads it (the issue
        # write below keeps its own reading)
        if method == "PUT" and _MERGE_API_RE.search(re.sub(r"/+", "/", path)):
            return "ask", MERGE_ASK_MSG.format(what=f"`gh api PUT {path}`")
        mutating = method != "GET" or any(_gh_api_mutating(t) for t in seg)
        if _ISSUE_API_RE.search(path) and mutating:
            return "deny", TRACKER_MSG.format(what=f"`gh api {method} {path}` writes issues or labels",
                                              use="the tracker verbs")
    if head in ("curl", "wget", "http", "https", "xh"):
        # the host in any case, scheme included (0.9.0): `https://API.GITHUB.COM/repos/…` is the same host
        url = next((t for t in seg[1:] if ("api.github.com/repos/" in t.lower() and _ISSUE_API_RE.search(t))
                    or _ADO_WIT_RE.search(t)), "")
        if url and _http_writes(seg, head, url):
            return "deny", TRACKER_MSG.format(what=f"`{head}` writes to {url}", use="the tracker verbs")
        merge = next((t for t in seg[1:] if _MERGE_API_RE.search(_github_api_path(t) or "")), "")
        if merge and _http_method(seg) == "PUT":
            return "ask", MERGE_ASK_MSG.format(what=f"`{head} PUT {merge}`")
        if any(_GRAPHQL_URL_RE.search(t) for t in seg[1:]):
            found, doc = _http_graphql_query(seg, head)
            d = _graphql_verdict(doc, f"{head} …/graphql") if found else None
            if d:
                return d
    words = seg[1:] if head in ("python", "python3") else seg
    if words and os.path.basename(words[0]) in ("tracker", "tracker.py") and "owner" in words[1:2]:
        use = "`tracker new|claim|block|review|note`; ask the owner to promote or close"
        return "deny", TRACKER_MSG.format(what="`tracker owner` is the human's verb", use=use)
    return None


# ----------------------------------------------------------------------------
# host-install: no package installs and no fetch-and-run on the developer machine (AGENTS.md, 2026-11-16).
# Matches command text: a second line of defence against habit, not a sandbox.
# ----------------------------------------------------------------------------

HOST_INSTALL_MSG = (
    "Host install: {what}. AGENTS.md: an agent installs nothing on the developer machine; "
    "run checks offline from the cache (uv run --offline, npx --no-install) and anything "
    "that needs a download in a container. Needs the owner's explicit yes."
)
_DISPOSABLE_FILES = ("/.dockerenv", "/run/.containerenv")
_DISPOSABLE_VARS = ("GITHUB_ACTIONS", "TF_BUILD", "CODESPACES", "REMOTE_CONTAINERS", "CLAUDE_CODE_REMOTE")


def disposable_environment(
    environ: Optional[Mapping[str, str]] = None, exists: Optional[Callable[[str], bool]] = None
) -> bool:
    """True inside a container, CI or a cloud dev box: the guard's own process runs there. Bare CI does not count."""
    env = os.environ if environ is None else environ
    path_exists = os.path.exists if exists is None else exists
    if any(path_exists(p) for p in _DISPOSABLE_FILES):
        return True
    return any(str(env.get(v, "")).lower() not in ("", "0", "false") for v in _DISPOSABLE_VARS)


def _w(words: str) -> frozenset:
    return frozenset(words.split())


_HI_STOP = _w("run run-script exec x test t start stop restart help")
_HI_NONE = frozenset()
# tool -> (install words, fetch-and-run words, exemption flags of the fetch-and-run words)
_HI_TABLE: dict = {
    "npm": (_w("install i add ci clean-install install-test it install-ci-test cit update up upgrade create"
               " ic install-clean dedupe ddp rebuild rb link ln"),
            _w("exec x"), _w("--no-install --no --offline")),
    "pnpm": (_w("install i add update up upgrade dlx create"), _HI_NONE, _HI_NONE),
    "yarn": (_w("install add up upgrade upgrade-interactive dlx create"), _HI_NONE, _HI_NONE),
    "bun": (_w("install i add update create upgrade"), _w("x"), _w("--no-install")),
    "pip": (_w("install download wheel"), _HI_NONE, _HI_NONE),
    "pipx": (_w("install install-all inject upgrade upgrade-all reinstall reinstall-all run"), _HI_NONE, _HI_NONE),
    # --no-sync skips the project sync but not --with requirements: only --offline exempts `uv run`
    "uv": (_w("add sync install upgrade update"), _w("run"), _w("--offline")),
    "poetry": (_w("install add update sync"), _HI_NONE, _HI_NONE),
    "pdm": (_w("install add update sync"), _HI_NONE, _HI_NONE),
    "pipenv": (_w("install sync update"), _HI_NONE, _HI_NONE),
    "conda": (_w("install create update upgrade"), _HI_NONE, _HI_NONE),
    "mamba": (_w("install create update upgrade"), _HI_NONE, _HI_NONE),
    "micromamba": (_w("install create update upgrade"), _HI_NONE, _HI_NONE),
    "brew": (_w("install reinstall upgrade tap bundle"), _HI_NONE, _HI_NONE),
    "apt": (_w("install upgrade full-upgrade dist-upgrade build-dep"), _HI_NONE, _HI_NONE),
    "apt-get": (_w("install upgrade full-upgrade dist-upgrade build-dep"), _HI_NONE, _HI_NONE),
    "dnf": (_w("install upgrade update groupinstall"), _HI_NONE, _HI_NONE),
    "yum": (_w("install upgrade update groupinstall"), _HI_NONE, _HI_NONE),
    "apk": (_w("add upgrade"), _HI_NONE, _HI_NONE),
    "snap": (_w("install refresh"), _HI_NONE, _HI_NONE),
    "cargo": (_w("install binstall add"), _HI_NONE, _HI_NONE),
    "go": (_w("install get"), _HI_NONE, _HI_NONE),
    "gem": (_w("install update"), _HI_NONE, _HI_NONE),
    "bundle": (_w("install update add"), _HI_NONE, _HI_NONE),
    "bundler": (_w("install update add"), _HI_NONE, _HI_NONE),
    "mise": (_w("install use upgrade"), _HI_NONE, _HI_NONE),
    "asdf": (_w("install"), _HI_NONE, _HI_NONE),
    "nvm": (_w("install"), _HI_NONE, _HI_NONE),
    "fnm": (_w("install"), _HI_NONE, _HI_NONE),
    "volta": (_w("install"), _HI_NONE, _HI_NONE),
    "pyenv": (_w("install"), _HI_NONE, _HI_NONE),
    "rustup": (_w("install update"), _HI_NONE, _HI_NONE),
    "corepack": (_w("prepare install use up"), _HI_NONE, _HI_NONE),
    "pre-commit": (_w("install install-hooks autoupdate"), _HI_NONE, _HI_NONE),
}
# two consecutive non-option tokens anywhere after the tool name; az and gh are judged by these pairs only
_HI_PAIRS: dict = {
    "npm": {("audit", "fix")},
    "rustup": {("component", "add"), ("target", "add")},
    "go": {("mod", "download")},
    "az": {("extension", "add"), ("extension", "update"), ("bicep", "install"), ("bicep", "upgrade")},
    "gh": {("extension", "install"), ("extension", "upgrade")},
}
_HI_PAIRS_ONLY = _w("az gh")
_HI_BARE = _w("yarn bundle bundler")  # a bare call installs
# heads that fetch and run by themselves -> their exemption flags (pnpx: never exempt)
_HI_SELF_FETCH: dict = {"npx": _w("--no-install --no --offline"), "pnpx": _HI_NONE, "bunx": _w("--no-install"),
                        "uvx": _w("--offline")}
_HI_PROBES = _w("--version -v -V --help -h")
_HI_HELP = _w("--help -h")
_HI_SHELLS = _w("sh bash zsh dash ksh")
_HI_DOWNLOADERS = _w("curl wget")
_HI_SHELL_WORDS = _w("! { then do else elif if while until time")
_HI_WRAPPERS = _w("sudo env command exec nohup doas builtin timeout gtimeout nice ionice caffeinate arch stdbuf xargs"
                  " find watch")
# a wrapper that reaches one of these first hands over to a container or another machine: not judged
# (DECISIONS.md, 2026-11-16, "installs stay off the developer machine")
_HI_REMOTE = _w("docker docker-compose podman nerdctl kubectl oc ssh devcontainer")
_HI_PUNCT = ";&|()`\n"
_HI_WORD_START = " \t\n;&|()`"  # a `#` after one of these (or at the start) begins a comment
_HI_MAX_DEPTH = 5
_HI_NOT_READ = f"the command nests deeper than {_HI_MAX_DEPTH} levels and was not read"
_PIP_RE = re.compile(r"^pip(\d+(\.\d+)?)?$")
_PYTHON_RE = re.compile(r"^python(\d+(\.\d+)?)?$")
_DOWNLOAD_SUB_RE = re.compile(r"^\s*(\$\(|`)\s*(curl|wget)(\s|$)")
# an unbalanced quote: coarse checks for a downloaded script (the shell would probably reject the line anyway)
_HI_COARSE = (
    # the gap is bounded: unbounded, a 50 kB line of `curl` words took 0.5 s here, and a slow hook fails open
    (re.compile(r"\b(curl|wget)\b[^|;&\n]{0,2000}\|(?!\|)[\s&]*(?:\S*/)?(?:sudo\s+)?(?:\S*/)?(sh|bash|zsh|dash|ksh)\b"),
     "`{0} | {1}` runs a downloaded script"),
    (re.compile(r"<\(\s*(curl|wget)\b"), "`<({0} …)` runs a downloaded script"),
    (re.compile(r"(?:\s-\w*c|\beval)\s+[\"']?(?:\$\(|`)\s*(curl|wget)\b"), "`$({0} …)` runs a downloaded script"),
)


def _hi_key(name: str) -> Optional[str]:
    """The table entry a command basename belongs to (pip3.12 -> pip), or None."""
    if _PIP_RE.match(name):
        return "pip"
    return name if name in _HI_TABLE or name in _HI_SELF_FETCH or name in _HI_PAIRS_ONLY else None


def _hi_startable(name: str) -> bool:
    return name in _HI_SHELLS or bool(_PYTHON_RE.match(name)) or _hi_key(name) is not None


def _hi_sub_end(text: str, i: int) -> int:
    """Index of the character that closes the substitution opened at text[i] (`$(` or a backtick), or len(text)."""
    tick = text[i] == "`"
    depth, j = 1, i + (1 if tick else 2)
    cases = 0  # 0.9.0: open `case … in` statements; a `)` among them ends a pattern
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if tick and c == "`":
            return j
        if not tick and c in "ce" and _case_word(text, j, cases > 0):
            cases += 1 if c == "c" else -1
            j += 4
            continue
        if not tick and c in "()":
            if c == ")" and cases and depth == 1:
                j += 1
                continue
            depth += 1 if c == "(" else -1
            if depth == 0:
                return j
        j += 1
    return len(text)


def _hi_glued(out: list[str]) -> bool:
    """The unquoted `<` or `>` at hand is glued to a word in front of it that is no file descriptor number
    (`cat<f`, `bash<<EOF`; not `2>f`, the second `<` of `<<`, or a word start)."""
    if not out or out[-1] in ("<", ">", "<\x01"):
        return False
    for p in reversed(out):
        if len(p) == 1 and p in _HI_WORD_START:
            break
        if not p.isdigit():
            return True
    return False


def _hi_prepare(text: str, mark: bool = False) -> tuple[str, list[str]]:
    """One quote-aware pass before the lexer. Drops backslash-newline and comments, takes the `&` out of a
    redirection (2>&1, >&2, &>) so it does not split the command, and collects the body of every $( … ) and
    backtick substitution written inside double quotes: the host shell runs it. 0.8.0: an unquoted `<` or `>`
    glued to the word in front of it is split off (`cat<.env`, `bash<<EOF`); with `mark` (the reader) an unquoted
    input redirection `<` gets the mark \x01, so a quoted word that starts with `<` is no redirection."""
    out: list[str] = []
    subs: list[str] = []
    quote = ""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and quote != "'":
            if text[i + 1 : i + 2] != "\n":  # backslash-newline is removed, as the shell does
                out.append(text[i : i + 2])
            i += 2
            continue
        if quote == "'":
            quote = "" if c == "'" else quote
        elif quote == '"':
            if c == '"':
                quote = ""
            elif c == "`" or (c == "$" and text[i + 1 : i + 2] == "(" and text[i + 2 : i + 3] != "("):
                end = _hi_sub_end(text, i)
                subs.append(text[i + (1 if c == "`" else 2) : end])
                out.append(text[i : end + 1])
                i = end + 1
                continue
        elif c in "'\"":
            quote = c
        elif c == "#" and (not out or (len(out[-1]) == 1 and out[-1] in _HI_WORD_START)):  # not after `\ `
            j = text.find("\n", i)  # a comment runs to, not including, the end of its line
            i = n if j < 0 else j
            continue
        elif c in "<>" and text[i + 1 : i + 2] == "&":  # 2>&1, >&2, <&3, 2>&-
            if _hi_glued(out):
                out.append(" ")
            out.append(c)
            i += 2
            continue
        elif c == "&" and text[i + 1 : i + 2] == ">":  # &>, &>>
            i += 1
            continue
        elif c in "<>":
            glued = _hi_glued(out)
            if glued:
                out.append(" ")
            if mark and c == "<" and text[i + 1 : i + 2] not in ("<", "(") and (glued or out[-1:] != ["<"]):
                out.append("<\x01")  # an input redirection: `<f`, `< f`, `<>f`
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out), subs


def _hi_lex(text: str) -> Optional[list[tuple[str, list[str]]]]:
    """Quote-aware split into (preceding separator run, tokens) per simple command; None on an unbalanced quote."""
    lex = shlex.shlex(text, posix=True, punctuation_chars=_HI_PUNCT)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    out: list[tuple[str, list[str]]] = []
    cur: list[str] = []
    sep = ""
    try:
        for tok in lex:
            if tok and all(c in _HI_PUNCT for c in tok):
                if cur:
                    out.append((sep, cur))
                    cur, sep = [], tok
                else:
                    sep += tok  # `| <newline>`, `) |`: one run, so a pipe stays a pipe
            else:
                cur.append(tok)
    except ValueError:  # unbalanced quote or trailing escape
        return None
    if cur:
        out.append((sep, cur))
    return out


def simple_commands(text: str) -> list[tuple[str, list[str]]]:
    """Quote-aware split into (preceding separator, tokens) per simple command; a quoted string stays one token.
    An unbalanced quote falls back to segments() (separators unknown); this never raises."""
    cmds = _hi_lex(text)
    return [("", seg) for seg in segments(text)] if cmds is None else cmds


def _hi_real(toks: list[str]) -> list[str]:
    """Drop assignments and shell words; a wrapper hands over to the first later shell, Python, table tool or
    downloader, and to nothing when a container or remote head comes first."""
    i = 0
    while i < len(toks) and (_ASSIGN_RE.match(toks[i]) or toks[i] in _HI_SHELL_WORDS):
        i += 1
    toks = toks[i:]
    if not toks or os.path.basename(toks[0]) not in _HI_WRAPPERS:
        return toks
    if os.path.basename(toks[0]) == "command" and toks[1:2] in (["-v"], ["-V"]):
        return []  # a lookup
    start = 1
    if tool_name(toks[0]) == "find":
        # 0.9.0 (K1): find runs a command only after -exec, -execdir, -ok or -okdir; `-name yarn` is a pattern
        start = next((k + 1 for k in range(1, len(toks)) if toks[k] in _NC_FIND_EXEC), len(toks))
    for j in range(start, len(toks)):
        name = os.path.basename(toks[j])
        if name in _HI_REMOTE:
            # the container or remote route, also behind a wrapper
            # (DECISIONS.md, 2026-11-16, "installs stay off the developer machine")
            return []
        if _hi_startable(name) or name in _HI_DOWNLOADERS:
            return toks[j:]
    return []


def _hi_dash_c(args: list[str]) -> Optional[str]:
    """The script of `sh -c <script>` (also -lc, -ec, after -o <opt>); None when the shell runs a file or stdin."""
    skip = False
    for i, t in enumerate(args):
        if skip:
            skip = False
        elif t in ("-o", "+o"):
            skip = True
        elif t.startswith("-") and not t.startswith("--") and "c" in t[1:]:
            return args[i + 1] if i + 1 < len(args) else None
        elif t == "--" or not t.startswith(("-", "+")):
            return None
    return None


def _hi_search(rest: list[str], depth: int) -> Optional[str]:
    """After a stop word: judge the first later token that starts a shell, Python or table command."""
    for j, t in enumerate(rest):
        if _hi_startable(os.path.basename(t)):
            return _hi_judge(rest[j:], depth + 1)
    return None


def _hi_script(script: str, head: str, depth: int) -> Optional[str]:
    m = _DOWNLOAD_SUB_RE.match(script)
    if m:
        shown = "eval" if head == "eval" else f"{head} -c"
        return f"`{shown} \"$({m.group(2)} …)\"` runs a downloaded script"
    return host_install_what(script, depth + 1)


# shell options whose value is the next word (bash(1): -o, -O, --rcfile, --init-file; 0.8.0 adds all but -o)
_HI_SHELL_VALUED = frozenset("-o +o -O +O --rcfile --init-file".split())


def _hi_shell_reads_stdin(args: list[str]) -> bool:
    """A shell reads its program from stdin: no -c script, and no operand unless -s is given."""
    if _hi_dash_c(args) is not None:
        return False
    s_flag, skip, options = False, False, True
    for t in args:
        if skip:
            skip = False
        elif options and t in _HI_SHELL_VALUED:
            skip = True
        elif options and t == "--":
            options = False
        elif options and t.startswith(("-", "+")):
            s_flag = s_flag or (not t.startswith("--") and "s" in t[1:])
        else:
            # an operand is a script file, unless -s reads the program from stdin or it names stdin (0.8.0)
            return s_flag or t in ("/dev/stdin", "/dev/fd/0")
    return True


def _hi_code_option(name: str, t: str) -> bool:
    """An interpreter option that carries the program itself (or names a module to run)."""
    if _PYTHON_RE.match(name):
        return t.startswith(("-c", "-m"))
    if name == "node":
        return t in ("-e", "-p", "--eval", "--print") or t.startswith(("--eval=", "--print="))
    return not t.startswith("--") and t.endswith("e")  # perl, ruby: a short-option cluster that ends in e


def _hi_reads_stdin(name: str, args: list[str]) -> bool:
    """True when `name args` would run a program read from standard input (`sh`, `bash -s`, `python3 -`)."""
    if name in _HI_SHELLS:
        return _hi_shell_reads_stdin(args)
    if not (_PYTHON_RE.match(name) or name in ("node", "ruby", "perl")):
        return False
    skip = False
    for t in args:
        if skip:
            skip = False
        elif t == "-":
            return True
        elif not t.startswith("-") or _hi_code_option(name, t):
            return False  # a script file or a program of its own
        else:
            skip = bool(_PYTHON_RE.match(name)) and t in ("-W", "-X")  # these take a value
    return True


def _hi_python(args: list[str], depth: int) -> Optional[str]:
    """`python -m <tool>` is judged as `<tool>` (also -mpip, after -W/-X and their value)."""
    skip = False
    for i, t in enumerate(args):
        if skip:
            skip = False
        elif t.startswith("-m"):
            return _hi_judge(([t[2:]] if t[2:] else []) + args[i + 1 :], depth + 1)
        elif t in ("-W", "-X"):
            skip = True
        elif not t.startswith("-") or t.startswith("-c") or t == "-":
            return None  # a script, inline code or stdin: not judged
    return None


def _hi_pair(head: str, key: str, args: list[str]) -> Optional[str]:
    pairs = _HI_PAIRS.get(key, ())
    for a, b in zip(args, args[1:]):
        if a == "--":
            break
        if (a, b) in pairs:
            return f"`{head} {a} {b}` installs packages"
    return None


def _hi_options_only(toks: list[str]) -> bool:
    return all(t.startswith("-") for t in toks)


def _hi_walk(head: str, key: str, args: list[str], depth: int) -> Optional[str]:
    """Walk a table tool's tokens left to right (DECISIONS.md, 2026-11-16, "installs stay off the developer
    machine")."""
    install, fetch, exempt = _HI_TABLE[key]
    for i, t in enumerate(args):
        if t == "--":
            return None
        if t.startswith("-"):
            continue
        later = args[i + 1 :]
        if (t in install or t in fetch) and later and _hi_options_only(later) and _HI_HELP & set(later):
            return None  # `pip install --help`: a help probe
        if t in install:
            return f"`{head} {t}` installs packages"
        if key == "npm" and t == "init" and later[:1] and not later[0].startswith("-"):
            return f"`{head} init` fetches and runs a package"
        if key == "go" and t == "run":
            operands = [x for x in later if not x.startswith("-")]
            if operands and "@" in operands[0]:
                return f"`{head} run` fetches and runs a package"
        if t in fetch:
            if not exempt & set(args):
                if key == "uv":
                    return f"`{head} {t}` without --offline may install"
                return f"`{head} {t}` fetches and runs a package"
            return _hi_search(later, depth)
        if t in _HI_STOP:
            return _hi_search(later, depth)
    if key in _HI_BARE:
        rest = [t for k, t in enumerate(args) if not (t == "--cwd" or (k and args[k - 1] == "--cwd"))]
        if _hi_options_only(rest) and not _HI_PROBES & set(rest):
            return f"`{head}` installs packages"
    return None


def _hi_judge(toks: list[str], depth: int) -> Optional[str]:
    """What one simple command would install or fetch-and-run on the host, or None."""
    if depth > _HI_MAX_DEPTH:
        return _HI_NOT_READ if toks else None
    toks = _hi_real(toks)
    if not toks:
        return None
    head = os.path.basename(toks[0])
    args = caps_verbs(head, toks[1:])  # `brew REINSTALL jq` (0.9.0)
    if head in _HI_SHELLS:
        script = _hi_dash_c(args)
        return None if script is None else _hi_script(script, head, depth)
    if head == "eval":
        return _hi_script(" ".join(args), head, depth) if args else None
    if _PYTHON_RE.match(head):
        return _hi_python(args, depth)
    key = _hi_key(head)
    if key is None:
        return None  # not a tool of the table: never inspected past its head (the container route)
    if key in _HI_SELF_FETCH:
        if _hi_options_only(args) and _HI_PROBES & set(args):
            return None  # `npx --version`: a version or help probe
        if _HI_SELF_FETCH[key] & set(args):
            return _hi_search(args, depth)
        return f"`{head}` fetches and runs a package"
    pair = _hi_pair(head, key, args)
    if pair or key in _HI_PAIRS_ONLY:
        return pair  # az, gh: the pairs only, nothing else of the command is read
    return _hi_walk(head, key, args, depth)


def _hi_commands(cmds: list[tuple[str, list[str]]], depth: int) -> Optional[str]:
    """Judge each simple command, then the downloaded-script forms that span commands (DECISIONS.md, 2026-11-16,
    "installs stay off the developer machine")."""
    downloader = ""  # a curl or wget earlier in the current pipeline
    for k, (sep, toks) in enumerate(cmds):
        what = _hi_judge(toks, depth)
        if what:
            return what
        real = _hi_real(toks)
        name = os.path.basename(real[0]) if real else ""
        if sep.count("|") != 1:
            downloader = ""  # any other separator (`||` included) starts a new pipeline
        elif downloader and _hi_reads_stdin(name, real[1:]):  # curl … | tee f | sh
            return f"`{downloader} | {name}` runs a downloaded script"
        if name in _HI_DOWNLOADERS:
            downloader = name
        nxt = cmds[k + 1] if k + 1 < len(cmds) else ("", [])
        fed = _hi_real(nxt[1])
        fed_name = os.path.basename(fed[0]) if fed else ""
        if fed_name not in _HI_DOWNLOADERS:
            continue
        before = real[1:-1][:-1] if real[-2:-1] == ["<"] else real[1:-1]  # bash < <(curl …): stdin is the file
        if real[-1:] == ["<"] and nxt[0].startswith("(") and (
                name in ("source", ".") or _hi_reads_stdin(name, before)):  # bash <(curl …)
            return f"`{name} <({fed_name} …)` runs a downloaded script"
        if name == "eval" and ((real[1:] == ["$"] and nxt[0].startswith("("))
                               or (len(real) == 1 and nxt[0].startswith("`"))):  # eval $(curl …), eval `curl …`
            return f"`eval $({fed_name} …)` runs a downloaded script"
    return None


def host_install_what(command: str, depth: int = 0) -> Optional[str]:
    """Name what a command line would install or fetch-and-run on the host, or None. A nest deeper than the
    limit is named, not read."""
    if depth > _HI_MAX_DEPTH:
        return _HI_NOT_READ if command.strip() else None
    text, subs = _hi_prepare(command)
    for sub in subs:  # $( … ) inside double quotes: the host shell runs it
        what = host_install_what(sub, depth + 1)
        if what:
            return what
    cmds = _hi_lex(text)
    if cmds is None:  # an unbalanced quote: split without separators, and fail closed for a downloaded script
        for rx, msg in _HI_COARSE:
            m = rx.search(text)
            if m:
                return msg.format(*m.groups())
        cmds = [("", seg) for seg in segments(text)]
    return _hi_commands(cmds, depth)


def host_install_silent(cfg: dict) -> bool:
    """The knob silences host-install: `off`, or `auto` where the guard runs in a disposable environment. Any other
    value is False (fail closed). run_hook still runs the rule and logs the silenced ask as `skipped`."""
    mode = cfg.get("host_install", DEFAULTS["host_install"])
    return mode == "off" or (mode == "auto" and disposable_environment())


def rule_host_install(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    command = strip_heredocs(ev.command)
    try:
        what = host_install_what(command)
    except Exception as exc:  # main() turns a crash into exit 1, which both harnesses let run silently: ask instead
        what = f"the command could not be read ({type(exc).__name__})"
    if what:
        return "ask", HOST_INSTALL_MSG.format(what=what)

    def judge(seg: list[str]) -> Optional[Decision]:
        found = _hi_judge(seg, 0)
        return ("ask", HOST_INSTALL_MSG.format(what=found)) if found else None

    # the local reading: what this machine runs; a container or remote tool ends the simple command. The reader
    # takes the here-document bodies out itself and reads one only where a local shell runs it (0.8.0)
    return reader_pass(ev.command, judge, "host-install", local=True)


# ----------------------------------------------------------------------------
# cloud-launch: no session starts work in the cloud (item #65, plan rev 3 row 1.7)
# ----------------------------------------------------------------------------

CLOUD_LAUNCH_MSG = ("cloud-launch: {what} starts work in the cloud, outside the boundary this session runs in; a "
                    "session never starts it (plan rev 3, row 1.7). The owner starts cloud work.")
CLOUD_UNREAD_MSG = "cloud-launch: {what}; the guard could not read whether it starts cloud work. Confirm the call."
DESIGN_SYNC_MSG = ("cloud-launch: `{tool}` sends material to a service of the account, and the guard cannot read "
                   "what; confirm the call.")
_CLOUD_CLIS = frozenset({"claude"})
_CLOUD_FLAGS = ("--cloud", "--remote")
_REMOTE_ISOLATION_RE = re.compile(r"\[?[\"'`]?isolation[\"'`]?\]?\s*:\s*[\"'`]remote[\"'`]", re.IGNORECASE)


def _cloud_seg(seg: list[str]) -> Optional[Decision]:
    """The words from one command word: `claude` with --cloud/--remote, or an argument that runs /autofix-pr."""
    if os.path.basename(seg[0]) not in _CLOUD_CLIS:
        return None
    for a in seg[1:]:
        if a in _CLOUD_FLAGS or a.startswith(tuple(f + "=" for f in _CLOUD_FLAGS)):
            return "deny", CLOUD_LAUNCH_MSG.format(what=f"`claude {a}`")
        if a.lstrip(" \t\n'\"`").startswith("/autofix-pr"):
            return "deny", CLOUD_LAUNCH_MSG.format(what="`claude /autofix-pr`")
    return None


WORKFLOW_SCRIPT_MAX = 1_000_000


def _workflow_script(ev: Event) -> tuple:
    """(script text or None, what could not be read or None) of a Workflow call; a `name` is not resolved."""
    if "script" in ev.args:
        script = ev.args["script"]
        return (script, None) if isinstance(script, str) else (None, "a Workflow script that is not text")
    if "scriptPath" in ev.args:
        path = ev.args["scriptPath"]
        if not isinstance(path, str) or not path:
            return None, "a Workflow scriptPath that is not a path"
        full = os.path.join(ev.cwd, os.path.expanduser(path))
        try:  # a directory, a device, a FIFO or a huge file would raise or stall the hook: each asks
            # a FIFO swapped in cannot block here, and a tty cannot become the controlling terminal
            fd = os.open(full, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0))
            with os.fdopen(fd, "rb") as fh:
                info = os.fstat(fh.fileno())  # judged on what was opened, not on the name
                if not stat.S_ISREG(info.st_mode):
                    return None, f"the Workflow script {path} is not a regular file"
                if info.st_size > WORKFLOW_SCRIPT_MAX:
                    return None, f"the Workflow script {path} is larger than {WORKFLOW_SCRIPT_MAX} bytes"
                data = fh.read(WORKFLOW_SCRIPT_MAX + 1)
                if len(data) > WORKFLOW_SCRIPT_MAX:  # it grew after fstat: refuse, never judge a prefix
                    return None, f"the Workflow script {path} is larger than {WORKFLOW_SCRIPT_MAX} bytes"
                return data.decode("utf-8", errors="replace"), None
        except OSError as exc:
            return None, f"the Workflow script {path} could not be read ({type(exc).__name__})"
    if isinstance(ev.args.get("name"), str):
        return None, None  # a named workflow: step 1.2 reads it (named limit)
    return None, "a Workflow call with no script, scriptPath or name"


def rule_cloud_launch(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse":
        return None
    if ev.kind == "shell":
        if not ev.command:
            return None
        for seg in segments(strip_heredocs(ev.command)):  # first: also a line the reader cannot read
            d = _cloud_seg(seg)
            if d:
                return d
        return reader_pass(ev.command, _cloud_seg, "cloud-launch")
    if ev.kind == "cloud":
        return "deny", CLOUD_LAUNCH_MSG.format(what=f"`{ev.tool}`")
    if ev.kind == "design":
        return "ask", DESIGN_SYNC_MSG.format(tool=ev.tool)
    if ev.kind == "spawn" and "isolation" in ev.args:
        iso = ev.args["isolation"]
        if not isinstance(iso, str):
            return "ask", CLOUD_UNREAD_MSG.format(what=f"`{ev.tool}` with an isolation that is not text")
        return ("deny", CLOUD_LAUNCH_MSG.format(what=f"`{ev.tool}` with isolation remote")) if (
            iso.lower() == "remote") else None
    if ev.kind == "skill":
        name = ev.args.get("skill")
        if not isinstance(name, str) or not name:
            return "ask", CLOUD_UNREAD_MSG.format(what="a Skill call without a skill name")
        if name.rsplit(":", 1)[-1].lstrip("/").lower() == "schedule":
            return "deny", CLOUD_LAUNCH_MSG.format(what="the `schedule` skill (cloud routines)")
        return None
    if ev.kind == "workflow":
        script, unread = _workflow_script(ev)
        if unread:
            return "ask", CLOUD_UNREAD_MSG.format(what=unread)
        if script and _REMOTE_ISOLATION_RE.search(script):
            return "deny", CLOUD_LAUNCH_MSG.format(what="a Workflow whose agent asks for isolation remote")
    return None


# ----------------------------------------------------------------------------
# github-tools: the harness's own GitHub tools get the verdict of the same act in a shell or a file tool (#65, D5)
# ----------------------------------------------------------------------------

GITHUB_TOOL_PREFIXES = ("mcp__github__", "github-mcp-server-")  # Claude Code; Copilot (unverified, fixtures only)
GITHUB_TWIN_MSG = "github-tools: {tool} is the same act as {twin}: {reason}"
GITHUB_UNKNOWN_MSG = "github-tools: {tool} has no known twin and is not named as a read or harmless; confirm this call."
GITHUB_BROKEN_MSG = "github-tools: {tool} came with {what}, which the guard cannot read; confirm this call."
_GITHUB_HARMLESS = frozenset(
    "create_branch create_pull_request update_pull_request update_pull_request_branch request_copilot_review"
    " create_pending_pull_request_review add_comment_to_pending_review"
    " add_pull_request_review_comment_to_pending_review".split())
_GITHUB_REVIEWS = frozenset(
    "pull_request_review_write create_and_submit_pull_request_review submit_pending_pull_request_review".split())
# op -> (gh words, the method that picks the verb from `method`): every one is a write tracker-guard denies
_GITHUB_TRACKER = {
    "issue_write": ("issue", {"create": "create"}, "edit"), "create_issue": ("issue", {}, "create"),
    "update_issue": ("issue", {}, "edit"), "add_issue_comment": ("issue", {}, "comment"),
    "sub_issue_write": ("issue", {}, "edit"), "assign_copilot_to_issue": ("issue", {}, "edit"),
    "label_write": ("label", {"create": "create", "delete": "delete"}, "edit"),
    "create_label": ("label", {}, "create"), "update_label": ("label", {}, "edit"),
    "delete_label": ("label", {}, "delete"),
}
_GITHUB_PATH_RULES = ("secret-write", "guard-config", "scratch-md")


class _Unreadable(Exception):
    """Input of a GitHub tool the twin cannot be built from; the rule asks with the text."""


def github_op(tool: str) -> Optional[str]:
    """The op of a GitHub tool name (`mcp__github__merge_pull_request` -> `merge_pull_request`), or None."""
    for prefix in GITHUB_TOOL_PREFIXES:
        if tool.startswith(prefix) and len(tool) > len(prefix):
            return tool[len(prefix) :]
    return None


def _gh_number(args: dict) -> str:
    """The pull request or issue number as a word (empty when none is given); not an int or digits: unreadable."""
    for key in ("pullNumber", "pull_number", "issue_number", "issueNumber"):
        if key in args:
            v = args[key]
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                return f" {v}"
            if isinstance(v, str) and v.isdigit():
                return f" {v}"
            raise _Unreadable(f"a {key} that is not a number")
    return ""


def _gh_text(args: dict, key: str, required: bool) -> Optional[str]:
    v = args.get(key)
    if v is None and not required and key not in args:
        return None
    if not isinstance(v, str) or not v:
        raise _Unreadable(f"a {key} that is not text" if key in args else f"no {key}")
    return v


def _github_twins(op: str, args: dict, cfg: dict) -> Optional[list]:
    """[(twin as shown, tool, input, rules)] for a GitHub op; [] for a read or a harmless op, None for no twin."""
    if op == "get_file_contents":
        path = _gh_text(args, "path", True)
        return [(f"a `Read` of {path}", "Read", {"file_path": path}, ("secret-read",))]
    if op.startswith(("get_", "list_", "search_")) or op.endswith("_read") or op in _GITHUB_HARMLESS:
        return []
    if op in _GITHUB_REVIEWS:
        event = args.get("event")
        if event is not None and not isinstance(event, str):
            raise _Unreadable("an event that is not text")
        if str(event or "").upper() != "APPROVE":
            return []
        return [_shell_twin(f"gh pr review{_gh_number(args)} --approve", "tracker-guard")]
    if op in ("merge_pull_request", "enable_pr_auto_merge"):
        auto = " --auto" if op == "enable_pr_auto_merge" else ""
        return [_shell_twin(f"gh pr merge{_gh_number(args)}{auto}", "tracker-guard")]
    if op in _GITHUB_TRACKER:
        group, by_method, verb = _GITHUB_TRACKER[op]
        method = args.get("method")
        verb = by_method.get(method, verb) if isinstance(method, str) else verb
        return [_shell_twin(f"gh {group} {verb}{_gh_number(args)}", "tracker-guard")]
    if op in ("create_or_update_file", "push_files", "delete_file"):
        branch = _gh_text(args, "branch", False)
        if op == "push_files":
            files = args.get("files")
            if not isinstance(files, list) or not files or not all(
                    isinstance(f, dict) and isinstance(f.get("path"), str) and f["path"] for f in files):
                raise _Unreadable("files that are not a list of objects with a path")
            paths = [f["path"] for f in files]
        else:
            paths = [_gh_text(args, "path", True)]
        twins = [(f"a `Write` of {p}", "Write", {"file_path": p, "content": ""}, _GITHUB_PATH_RULES) for p in paths]
        if op == "delete_file":
            twins.append(_shell_twin(f"git rm {shlex.quote(paths[0])}", "delete-guard"))
        protected = sorted(protected_branches(cfg))
        name = branch[len("refs/heads/"):] if branch and branch.lower().startswith("refs/heads/") else branch
        # no branch: the API writes the default branch; a spelling of a protected name in another case counts
        hit = next((b for b in protected if name is None or b.lower() == name.lower()), None)
        if hit is not None:
            twins.append(_shell_twin(f"git push origin HEAD:{'main' if name is None and 'main' in protected else hit}",
                                     "git-guard"))
        return twins
    return None


def _shell_twin(command: str, rule: str) -> tuple:
    return f"`{command}`", "Bash", {"command": command}, (rule,)


def rule_github_tools(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "github":
        return None
    op = github_op(ev.tool) or ""
    try:
        twins = _github_twins(op, ev.args, cfg)
    except _Unreadable as exc:
        return "ask", GITHUB_BROKEN_MSG.format(tool=ev.tool, what=exc)
    if twins is None:
        return "ask", GITHUB_UNKNOWN_MSG.format(tool=ev.tool)
    decisions = []
    for shown, tool, tool_input, rules in twins:
        twin = Event({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": ev.cwd,
                      "session_id": ev.session})
        for name in rules:
            d = RULES[name](twin, cfg)
            if d:
                decisions.append((d[0], GITHUB_TWIN_MSG.format(tool=ev.tool, twin=shown, reason=d[1])))
    return combine(decisions)


# ----------------------------------------------------------------------------
# Command reader for deploy-ask and delete-guard (0.6.1): every simple command the shell would run, nested
# scripts included, as tokens, so a variable, wrapper, option or nesting in front of a verb no longer hides it.
# Built on the host-install lexer; segments() stays as it is for the git, tracker, secret and egress rules.
# ----------------------------------------------------------------------------


class CommandNotRead(Exception):
    """The reader stopped (a nest deeper than _HI_MAX_DEPTH, too many tools or command words in one simple
    command): the rules ask, and the message says why."""


_MAX_TOOL_WORDS = 32  # tool and shell names judged per simple command; each reads the rest of it: bounds the cost
_TOO_MANY_TOOLS = f"one simple command names more than {_MAX_TOOL_WORDS} tools and was not read"
_MAX_COMMAND_WORDS = 64
_TOO_MANY_WORDS = (f"one simple command has more than {_MAX_COMMAND_WORDS} places where a command can stand "
                   "and was not read")
_REDIRECT_TOKEN_RE = re.compile(r"^\d*[<>]")
_BARE_REDIRECT_TOKEN_RE = re.compile(r"^\d*(<|>|>>|<<|<<-|<<<|<>|<\x01|<\x01>)$")  # \x01: _hi_prepare's mark
# the reader's own tables (the host-install ones stay as they are): names whose -c or here-string hands a script
# to a shell, by basename; `$SHELL` is a word the reader sees unexpanded
_NC_SHELLS = frozenset("sh bash zsh dash ksh fish ash su script flock $SHELL ${SHELL}".split())
_NC_DASH_C_RE = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")  # -c, -lc, -ec, -ce, -qc
_NC_VALUED = frozenset("-o +o -O +O".split())  # shell options whose next word is their value
_NC_SHELL_WORDS = frozenset("! { then do else elif if while until".split())
# wrapper basename -> plain words before the command it runs (timeout's duration, flock's lock file, chroot's new
# root, ssh's host); `time` is a wrapper here, so `time -p rm` and `/usr/bin/time rm` are read
_NC_WRAPPERS: dict = {
    **dict.fromkeys("sudo doas env command exec builtin nohup time nice ionice stdbuf caffeinate arch setsid strace"
                    " watch xargs parallel coproc busybox toybox".split(), 0),
    **dict.fromkeys("timeout gtimeout flock chroot ssh script".split(), 1),  # BSD `script file command …`
    # 0.9.0, each from its manual: util-linux 2.39 unshare(1), nsenter(1), runuser(1), taskset(1) (`taskset MASK
    # command`, or `-c LIST`), chrt(1) (`chrt PRIORITY command`); ltrace(1); valgrind 3.2x; zsh 5.9 precommand
    # modifiers `noglob`, `nocorrect`, `-`; FreeBSD/macOS lockf(1) (`lockf FILE command`); OpenSSH ssh-agent(1)
    # (`ssh-agent command`); fakeroot(1); libfaketime faketime(1) (`faketime TIMESTAMP command`); expect's
    # unbuffer(1); polkit pkexec(1); gosu (`gosu USER command`); systemd-run(1); firejail(1); watchexec 2
    # (`watchexec … -- command`); entr(1); sshpass(1); Xcode xcrun(1) (`xcrun TOOL …`)
    **dict.fromkeys("unshare nsenter runuser ltrace valgrind noglob nocorrect - ssh-agent fakeroot unbuffer pkexec"
                    " systemd-run firejail watchexec entr sshpass xcrun".split(), 0),
    **dict.fromkeys("lockf faketime gosu chrt taskset".split(), 1),
}
# 0.9.0: debuggers that run the command after one of their options: gdb(1) `--args`, lldb(1) `--`
_NC_AFTER_OPTION: dict = {"gdb": frozenset({"--args"}), "lldb": frozenset({"--"})}
# 0.7.0: a tool plus a subcommand that runs a command -> {subcommand words: plain words before that command}.
# Runners run it on this machine; container tools run it in a container (the image, container, service or pod
# comes first). The subcommand is found past the tool's own options; a `--` after it puts the command next.
_NC_RUN = {("run",): 0}
_NC_CONTAINER_SUBS = {(*pre, sub): 1 for pre in ((), ("container",), ("compose",)) for sub in ("run", "exec")}
_NC_SUB_WRAPPERS: dict = {
    **dict.fromkeys("uv poetry pdm pipenv hatch conda mamba micromamba".split(), _NC_RUN),
    "mise": {("exec",): 0, ("x",): 0},
    **dict.fromkeys("asdf bundle npm pnpm yarn".split(), {("exec",): 0}),
    "direnv": {("exec",): 1},
    **dict.fromkeys("docker podman nerdctl".split(), _NC_CONTAINER_SUBS),
    **dict.fromkeys("docker-compose podman-compose".split(), {("run",): 1, ("exec",): 1}),
    "kubectl": {("run",): 1, ("exec",): 1, ("debug",): 1},  # fix pass: `kubectl debug <pod> … -- <command…>`
    "oc": {("run",): 1, ("exec",): 1, ("rsh",): 1, ("debug",): 1},  # `oc rsh <pod> <command…>`
    "devcontainer": {("exec",): 0},
    # 0.9.0: secret injectors that run a command (1Password CLI 2 `op run -- …`, aws-vault 7 `aws-vault exec
    # PROFILE -- …`, Doppler CLI 3 `doppler run -- …`) and launchd's launchctl(1) `submit -l LABEL -- …`,
    # `asuser UID …`
    "op": {("run",): 0},
    "aws-vault": {("exec",): 1},
    "doppler": {("run",): 0},
    "launchctl": {("submit",): 0, ("asuser",): 1},
    "dotenv": {("run",): 0},  # python-dotenv 1 `dotenv run -- …`
}
# fix pass: a tool plus a subcommand whose command follows an option: `nix develop … -c <command…>`,
# `nix shell <installables…> --command <command…>`; the word after the first such option is a command word
_NC_OPTION_RUNNERS: dict = {"nix": {"develop": frozenset({"-c", "--command"}), "shell": frozenset({"-c", "--command"})}}
# fix pass: name -> (subcommand or "", options whose value is a script): `nix-shell --run '…'` wherever the
# option stands, `npx -c '…'`, `npm exec --call '…'`
_NC_SCRIPT_OPTIONS: dict = {
    "nix-shell": ("", frozenset({"--run", "--command"})),
    "npx": ("", frozenset({"-c", "--call"})),
    "npm": ("exec", frozenset({"-c", "--call"})),
    # F16: Doppler CLI 3, `doppler run --help`: "--command  command to execute (e.g. 'echo hello')", run in a shell
    "doppler": ("run", frozenset({"--command"})),
}
_NC_FD = frozenset({"fd", "fdfind"})
_NC_FD_EXEC = frozenset("-x -X --exec --exec-batch".split())  # fd runs the command after these per match
# the local reading ends at these command words: the command after them runs in a container or on another host
_NC_ELSEWHERE = _HI_REMOTE | {"podman-compose"}
# names whose quoted words are command lines for a shell: `ssh host '…'`, `watch '…'`, `parallel '…' ::: a`,
# `trap '…' EXIT`, `tmux send-keys '…' Enter`
_NC_SCRIPT_WORDS = frozenset("ssh watch parallel trap tmux hyperfine watchexec entr".split())  # 0.9.0: the last
# three take a command line as one quoted word (hyperfine 1.18 `hyperfine '…'`, watchexec 2 `watchexec '…'`,
# entr(1) `entr -s '…'`)
_NC_FIND_EXEC = frozenset("-exec -execdir -ok -okdir".split())
_NC_HELP = frozenset("-h -help --help".split())
_NC_FALLBACK_SPLIT_RE = re.compile(r"\|\||&&|[;|\n()`]")
# 0.8.0: a script fed to a shell. These shells read their program from standard input when they get no -c
# script and no script file (_hi_shell_reads_stdin); a here-document body or the words of an echo or printf piped
# into one are its script. The reader marks each here-document operator with the number of its body.
_NC_STDIN_SHELLS = frozenset("sh bash zsh dash ksh fish ash $SHELL ${SHELL}".split())
_NC_HEREDOC_MARK_RE = re.compile(r"^\d*<<-?\x00(\d+)\x00$")
_NC_ECHO_OPTION_RE = re.compile(r"^-[neE]+$")
# ssh options that take a value (ssh(1), OpenSSH 9): the first plain word after the options is the host
_SSH_VALUED = frozenset("BbcDEeFIiJLlmOoPpQRSWw")


def nested_commands(command: str, local: bool = False) -> tuple[tuple[str, ...], ...]:
    """The tokens of every simple command of the line and of what it nests (`$( … )` in double quotes, `sh -c`,
    `bash <<<`, `env -S`, `eval`, an ssh or watch script). Memoised: seven rules read the same text in one hook
    run. Raises CommandNotRead past _HI_MAX_DEPTH, and when a simple command is too long to read in bounded
    time; that outcome is memoised too.

    `local` is the local reading (host-install, protected-branch: what this machine runs): a simple command ends
    at the first command word that names a container or remote tool (_HI_REMOTE), and nothing after it is read,
    neither as a command nor as a script. `$( … )` in double quotes still counts: the local shell runs it."""
    got = _nc_cached(command, local)
    if isinstance(got, CommandNotRead):
        raise CommandNotRead(str(got))
    return got[0]


def nested_inputs(command: str, local: bool = False) -> tuple[str, ...]:
    """The files the simple commands of nested_commands read through an input redirection (`<f`, `0<f`,
    `< f`), from the same memoised read; the token tuples carry no redirection. Raises as nested_commands."""
    got = _nc_cached(command, local)
    if isinstance(got, CommandNotRead):
        raise CommandNotRead(str(got))
    return got[1]


@functools.lru_cache(maxsize=16)
def _nc_cached(command: str, local: bool = False):
    """nested_commands' memo: the token tuples, the input files, the environments and whether a shell reads its
    script from a pipe the guard cannot read, or the CommandNotRead that stopped the read."""
    out: list[tuple[str, ...]] = []
    inputs: list[str] = []
    envs: list[tuple[str, ...]] = []
    unread: list[bool] = []
    try:
        _nc_read(command, 0, out, set(), local, inputs, [], envs, unread=unread)
    except CommandNotRead as exc:  # kept as a value so the second rule does not read the line again
        return exc
    return tuple(out), tuple(inputs), tuple(envs), bool(unread)


def nested_unread_pipe(command: str, local: bool = False) -> bool:
    """Addendum to the second fix round: a shell of the line or of what it nests reads its script from a pipe
    whose content the guard cannot read (decision ad). The reader reads on past it; the rules ask for it. From
    the same memoised read; raises as nested_commands."""
    got = _nc_cached(command, local)
    if isinstance(got, CommandNotRead):
        raise CommandNotRead(str(got))
    return got[3]


def _pipe_ask(rule: str) -> Decision:
    """The ask for an unread pipe, in the words the reader pass used when the pipe ended the read."""
    return "ask", READER_MSG.format(rule=rule, what=_PIPE_NOT_READ)


def _unread_pipe(command: str) -> bool:
    """nested_unread_pipe for the rules that read nested_commands themselves; a line the reader stopped on is
    asked for by their own handler, so it is no unread pipe here."""
    try:
        return nested_unread_pipe(command)
    except CommandNotRead:
        return False


def nested_envs(command: str) -> tuple[tuple[str, ...], ...]:
    """For each token tuple of nested_commands (the full reading), the hook-gate assignments it inherits from the
    simple commands that run its script (`HUSKY=0 bash -c '…'`), from the same memoised read. Raises as
    nested_commands."""
    got = _nc_cached(command, False)
    if isinstance(got, CommandNotRead):
        raise CommandNotRead(str(got))
    return got[2]


def _nc_inputs(raw: list[str]) -> list[str]:
    """The files of the input redirections among the words of one simple command."""
    out = []
    for k, t in enumerate(raw):
        if _BARE_INPUT_RE.match(t):
            out.extend(raw[k + 1 : k + 2])
        else:
            m = _INPUT_REDIRECT_RE.match(t)
            if m:
                out.append(m.group(1))
    return out


def _nc_read(text: str, depth: int, out: list, seen: set, local: bool = False,
             inputs: Optional[list] = None, bodies: Optional[list] = None, envs: Optional[list] = None,
             env: tuple = (), *, unread: list) -> None:
    """Append the simple commands of one line to out, then read what each nests one level deeper. `bodies`
    holds the here-document bodies of the whole read, so a mark in a nested script still finds its body; `envs`
    gets, for each tuple of out, `env`: the hook-gate assignments the script inherits (0.8.0). `unread` gets a
    mark for each pipe a shell reads its script from that the guard cannot read; the read goes on past it. It is
    required and keyword-only: a call without it would read such a pipe as if nothing were unread."""
    if depth > _HI_MAX_DEPTH:
        if text.strip():
            raise CommandNotRead(_HI_NOT_READ)
        return
    if bodies is None:
        bodies = []
    prepared, subs = _hi_prepare(_nc_take_heredocs(text, bodies), mark=True)
    cmds = _hi_lex(prepared)
    if cmds is None:  # an unbalanced quote: raw words between separators, brackets and backticks, ends unquoted
        parts = [[w for w in (t.strip("'\"\\") for t in tokens(p)) if w] for p in _NC_FALLBACK_SPLIT_RE.split(prepared)]
        seps = [""] * len(parts)  # separators unknown: no pipe is read
    else:
        parts = [toks for _sep, toks in cmds]
        seps = [sep for sep, _toks in cmds]
    rows = []
    for raw in parts:
        kept = _nc_kept(raw)
        toks = [raw[k] for k in kept]
        if local:
            cut = _nc_remote_word(toks)
            if cut is not None:  # the words from the container or remote tool on run elsewhere
                raw = raw[: kept[cut]]
                toks = toks[:cut]
        rows.append((raw, toks))
    # (script, the environment it inherits); substitutions outside quotes are simple commands of their own in the
    # lexer already, and a substitution runs in the environment of this text
    nested = [(s, env) for s in subs]
    fed_bars = set()  # the bars through which _nc_fed read a script: no unread pipe
    for k, (raw, toks) in enumerate(rows):
        own = env + _nc_hook_env(toks)
        # taken from the words before the redirections go: `<<<` is one
        nested.extend((s, own) for s in _nc_here_strings(raw))
        if inputs is not None:
            inputs.extend(_nc_inputs(raw))
        piped = rows[k + 1][1] if k + 1 < len(rows) and seps[k + 1].strip(" \n") in ("|", "|&") else None
        fed, runner = _nc_fed(raw, toks, piped, bodies, unread)
        if piped is not None and runner is piped:
            fed_bars.add(k + 1)
        if not fed and toks in ([], ["}"]):
            fed, runner = _nc_group_fed(rows, seps, k, bodies)
        fed_env = own if runner is toks else env + _nc_hook_env(runner or [])
        nested.extend((s, fed_env) for s in fed)
        if not toks:
            continue
        out.append(tuple(toks))
        if envs is not None:
            envs.append(env)
        nested.extend((s, own) for s in _nc_scripts(toks))
    if cmds is not None and _nc_compound_pipe(rows, seps, fed_bars):
        unread.append(True)
    for script, script_env in nested:
        if (script, script_env) not in seen:  # one read per distinct script: a repeated nest costs nothing twice
            seen.add((script, script_env))
            _nc_read(script, depth + 1, out, seen, local, inputs, bodies, envs, script_env, unread=unread)


def _nc_remote_word(toks: list[str]) -> Optional[int]:
    """The first command word of a simple command that names a container or remote tool, or None."""
    return min((i for i in command_word_indexes(toks) if os.path.basename(toks[i]) in _NC_ELSEWHERE), default=None)


READER_MSG = "{rule}: {what}. Confirm the command; the guard could not check it."
NET_MSG = ("{rule}: `{tool}` is a command the guard does not know, and the `{name}` command behind it would {verdict}"
           " on its own. Confirm the command.")
# 0.9.0, the net (decision 3b): a later word naming one of these, behind a command word no table knows, starts
# that tool's command. Text tools print their words and run none of them
_NET_TOOLS = frozenset({"git", "gh", "az"})
_NET_TEXT = frozenset("echo printf man which type tldr whereis whatis apropos info help".split())


def net_starts(toks) -> tuple:
    """(index of the unknown command word, index of the `git`, `gh` or `az` behind it) for each command word of a
    simple command that no table knows and that is no text tool, when such a word follows it before the next
    command word. Memoised per token tuple: three rules ask for the same simple commands."""
    got = _net_cached(tuple(toks))
    if isinstance(got, CommandNotRead):
        raise CommandNotRead(str(got))
    return got


@functools.lru_cache(maxsize=256)
def _net_cached(toks: tuple):
    """net_starts' memo: the pairs, or the CommandNotRead that stopped the command word walk."""
    try:
        words = sorted(command_word_indexes(toks))
    except CommandNotRead as exc:  # kept as a value, as _cwi_cached keeps it
        return exc
    tools = [j for j, t in enumerate(toks) if os.path.basename(t) in _NET_TOOLS]  # one walk of the words
    if not tools:
        return ()
    out = []
    for n, i in enumerate(words):
        name = tool_name(toks[i])
        if _known_name(name) or name in _NET_TEXT:
            continue
        k = bisect.bisect_right(tools, i)
        nxt = words[n + 1] if n + 1 < len(words) else len(toks)
        if k < len(tools) and tools[k] < nxt:  # a later command word is judged as itself
            out.append((i, tools[k]))
    return tuple(out)


def reader_pass(text: str, judge: Callable[[list[str]], Optional[Decision]], rule: str,
                local: bool = False, net: Optional[Callable[[list[str]], Optional[Decision]]] = None,
                read: Optional[list] = None) -> Optional[Decision]:
    """The token pass of a rule that first reads segments(): judge the words from every command word of every
    simple command the line runs. The first deny wins; asks are combined. Never raises: a line the reader could
    not read, or a crash, asks with the reason (a rule's own deny from its first pass is returned before this).
    With `net` (0.9.0), the words from a `git`, `gh` or `az` behind an unknown command word are judged by it too,
    and whatever it answers, ask or deny, asks: the guard does not know what the word in front does. `read`, when
    handed in, gets a mark once the reader has read the line, before the first command is judged: a caller learns
    that the read went through from it, whatever the answer says."""
    try:
        asks = []
        commands = nested_commands(text, local)
        if read is not None:
            read.append(True)
        for toks in commands:
            for i in sorted(command_word_indexes(toks)):
                d = judge(list(toks[i:]))
                if d and d[0] == "deny":
                    return d
                if d:
                    asks.append(d)
            for i, j in net_starts(toks) if net else ():
                d = net(list(toks[j:]))
                if d:
                    asks.append(("ask", NET_MSG.format(rule=rule, tool=os.path.basename(toks[i]),
                                                       name=os.path.basename(toks[j]), verdict=d[0])))
        if nested_unread_pipe(text, local):  # read past it; with no deny found, it asks with the others
            asks.append(_pipe_ask(rule))
        return combine(asks)
    except CommandNotRead as exc:  # too deep or too many words: ask rather than pass it unread
        what = str(exc)
    except Exception as exc:  # main() turns a crash into exit 1, which both harnesses let run silently: ask instead
        what = f"the command could not be read ({type(exc).__name__})"
    return "ask", READER_MSG.format(rule=rule, what=what)


def _nc_here_strings(toks: list[str]) -> list[str]:
    """The here-strings of a simple command that names a shell (`bash <<< 'script'`, `bash <<<'script'`, and
    without a space in front, `bash<<<'script'`)."""
    out = []
    shell = False
    for k, t in enumerate(toks):
        head, mark, tail = t.partition("<<<")
        shell = shell or os.path.basename(head) in _NC_SHELLS
        if mark:
            out.extend([tail] if tail else toks[k + 1 : k + 2])
    return out if shell else []


def _nc_take_heredocs(text: str, bodies: list) -> str:
    """The text with every here-document body taken out (a body is never lexed as commands of the line) and its
    operator replaced by a mark that numbers the body in `bodies`; `<<-` strips the leading tabs of the body."""
    if "<<" not in text or "\x00" in text:  # a NUL in the text: strip as before, read no body as a script
        return strip_heredocs(text)
    out: list[str] = []
    pos = scanned = emitted = 0
    stack = ["sh"]
    while True:
        m = _HEREDOC_RE.search(text, pos)
        if not m:
            break
        if scanned <= m.start():
            scanned = _quote_state(text, scanned, m.start(), stack)
        if scanned > m.start() or stack[-1] not in _SHELL_CONTEXTS:
            # in a comment or behind a backslash the walk stepped over (no operator), or
            # inside a quoted word (`bash -c 'bash <<EOF …'`): the nested read of that word takes it
            pos = m.start() + 2
            continue
        dash = "-" if m.group(1) else ""
        body = m.group(4)
        if dash:
            body = "\n".join(line.lstrip("\t") for line in body.split("\n"))
        bodies.append(body)
        after = m.end(3) + len(m.group(2))  # past the delimiter and its closing quote
        out.append(text[emitted : m.start()])
        out.append(f"<<{dash}\x00{len(bodies) - 1}\x00" + text[after : m.start(4)])
        pos = scanned = emitted = m.end()  # a body is no shell text: the quote scan goes on behind it
    out.append(text[emitted:])
    return "".join(out)


_SHELL_CONTEXTS = ("sh", "(", "`", "case")  # where a here-document belongs to a command of the text at hand
_CASE_RE = re.compile(r"case\s+\S+\s+in(?=\s|$)")
_ESAC_RE = re.compile(r"esac(?=[\s;&|)`]|$)")


def _case_word(text: str, i: int, in_case: bool) -> bool:
    """At text[i] a word `case WORD in` opens a case statement, or (in one) `esac` closes it: only where a word
    starts, so `showcase` and `esac.txt` are none."""
    if i and text[i - 1] not in _HI_WORD_START:
        return False
    return bool(_ESAC_RE.match(text, i)) if in_case and text[i] == "e" else (
        text[i] == "c" and bool(_CASE_RE.match(text, i)))


def _quote_state(text: str, start: int, end: int, stack: list) -> int:
    """Walk text[start:end] and keep `stack` (the open contexts, "sh" at the bottom) as the shell reads it:
    quotes, `$'…'`, comments, and `$( … )` or backticks, also inside double quotes, where a shell context of its
    own begins (`"$(cat <<'EOF' … EOF)"`). Returns where the walk stopped (at least `end`)."""
    i = start
    while i < end:
        c, top = text[i], stack[-1]
        if c == "\\" and top != "'":
            i += 2
            continue
        if top == "'":
            if c == "'":
                stack.pop()
        elif top == "$'":
            if c == "'":
                stack.pop()
        elif top == '"':
            if c == '"':
                stack.pop()
            elif c == "$" and text[i + 1 : i + 2] == "(":
                stack.append("(")
                i += 1
            elif c == "`":
                stack.append("`")
        elif c == "#" and (i == 0 or text[i - 1] in _HI_WORD_START):  # a comment, as _hi_prepare reads it
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
            continue
        elif c in "ce" and _case_word(text, i, top == "case"):
            # 0.9.0: inside `case … in … esac` a `)` ends a pattern, not the `$( … )` around it
            if c == "c":
                stack.append("case")
            else:
                stack.pop()
            i += 4
            continue
        elif c == "$" and text[i + 1 : i + 2] == "'":
            stack.append("$'")
            i += 1
        elif c in "'\"":
            stack.append(c)
        elif c == "(":
            stack.append("(")
        elif c == ")" and top == "(":
            stack.pop()
        elif c == "`":
            if top == "`":
                stack.pop()
            else:
                stack.append("`")
        i += 1
    return max(i, end)


def _nc_fed(raw: list[str], toks: list[str], piped: Optional[list], bodies: list,
            unread: list) -> tuple[list[str], Optional[list]]:
    """The scripts one simple command feeds to a shell (0.8.0), and the simple command that runs them: its
    here-document bodies when it runs a shell that reads standard input or an ssh without a command; and, when
    its output goes through one pipe into such a command (`piped`), the bodies of a `cat` without a file operand
    and the words of an `echo` or `printf`. A shell behind the pipe whose script is not on the line gets a mark
    in `unread` (required, so no caller can leave the mark out) and nothing is fed."""
    marks = [_NC_HEREDOC_MARK_RE.match(t) for t in raw]
    own = [bodies[int(m.group(1))] for m in marks if m and int(m.group(1)) < len(bodies)]
    if own and _nc_runs_stdin(toks):
        return own, toks
    if piped is None or not toks or not _nc_runs_stdin(piped):
        return [], None
    for i in sorted(command_word_indexes(toks)):
        name, args = os.path.basename(toks[i]), toks[i + 1 :]
        if name == "cat":
            if own and all(t == "-" or (t.startswith("-") and t != "--") for t in args):
                return own, piped
            break  # a file or the line's own input: the script is not on the line
        if name == "echo":
            k = 0
            while k < len(args) and _NC_ECHO_OPTION_RE.match(args[k]):
                k += 1
            return [" ".join(args[k:]).replace("\\n", "\n")], piped
        if name == "printf":  # -v sets a variable
            return ([] if args[:1] == ["-v"] else [" ".join(args).replace("\\n", "\n")]), piped
    if _nc_pipe_shell(piped):
        unread.append(True)
    return [], None


def _nc_group_fed(rows: list, seps: list, k: int, bodies: list) -> tuple[list[str], Optional[list]]:
    """0.9.0: the here-document bodies of the `}` or `)` that closes a group `{ …; }` or a subshell `( … )` at
    rows[k] are the standard input of the commands inside: the first shell among them that reads standard input
    gets them as its script (`{ cd repo && bash; } <<EOF`). `{ cat; } <<EOF` stays data."""
    raw, toks = rows[k]
    marks = [_NC_HEREDOC_MARK_RE.match(t) for t in raw]
    own = [bodies[int(m.group(1))] for m in marks if m and int(m.group(1)) < len(bodies)]
    if not own:
        return [], None
    brace = toks == ["}"]
    if not brace and seps[k].strip() != ")":
        return [], None
    depth = 0
    for j in range(k - 1, -1, -1):  # back to the word or bracket that opens the group
        inner = rows[j][1]
        if brace and inner[:1] == ["}"] or not brace and seps[j].strip() == ")":
            depth += 1
        opens = inner[:1] == ["{"] if brace else seps[j].strip() == "("
        if opens and depth:
            depth -= 1
        elif opens:
            for _raw, words in rows[j:k]:
                if words and _nc_runs_stdin(words):
                    return own, words
            return [], None
    return [], None


# F03: fish and ash read commands from standard input too, as _NC_STDIN_SHELLS has it (fish(1), fish 4.x: "if no
# file is given, commands are read from standard input"; ash, BusyBox 1.36, as POSIX sh(1))
_PIPE_SHELLS = frozenset("sh bash zsh dash ksh fish ash".split())
_PIPE_NOT_READ = "a shell reads its script from a pipe whose content the guard cannot read"


def _nc_compound_pipe(rows: list, seps: list, fed_bars: frozenset = frozenset()) -> bool:
    """F02, F03: a pipe with a subshell, group or compound on one side, and a shell that reads its program from
    the pipe on the other: `(cat run.sh) | bash`, `cat run.sh | (bash)`, `cat run.sh | { cd x; bash; }`, `… | if
    true; then bash; fi`. _nc_fed reads a pipe between two simple commands only; here what goes through the pipe
    is not read, so the line asks. Second fix round: a separator is read by its characters (`|⏎(`), and a row of
    redirections only behind a closer (`(cat run.sh) 2>/dev/null | bash`) stands for the subshell it closes.
    Addendum: a bar of `fed_bars` (_nc_fed read the script through it, `echo '…' | { sh; }`) is left out."""
    compact = [s.replace(" ", "").replace("\n", "") for s in seps]
    for r in range(1, len(rows)):
        if r in fed_bars:
            continue
        sep = compact[r]
        bar = sep.find("|")
        if bar < 0 or sep.replace("(", "").replace(")", "") not in ("|", "|&"):
            continue
        left = rows[r - 1][1]
        compound = (")" in sep[:bar] or left[:1] in (["}"], ["fi"], ["done"], ["esac"])
                    or (not left and ")" in compact[r - 1]))
        depth = 0
        receivers = []
        for j in range(r, len(rows)):
            s = compact[j]
            if j > r:
                depth -= s.count(")")
                if depth <= 0:
                    break
            toks = rows[j][1]
            receivers.append(toks)
            depth += (s[bar + 1 :] if j == r else s).count("(")
            if toks[:1] and toks[0] in _COMPOUND_OPENERS:
                depth += 1
            depth += sum(1 for t in toks[1:] if t == "{")  # `then {`, `{ {`: an inner group opens too
            if j > r and toks[:1] and toks[0] in _COMPOUND_CLOSERS:
                depth -= 1
            if depth <= 0:
                break
        if (compound or len(receivers) > 1 or "(" in sep[bar:]) and any(_nc_pipe_shell(t) for t in receivers if t):
            return True
    return False


def _nc_pipe_shell(toks) -> bool:
    """Decision ad (0.9.0): a shell of _PIPE_SHELLS at a command word of the command behind a pipe reads its
    program from it (no -c, no script operand), on this machine: one behind a container or remote tool is not
    decided and is left as before. Second fix round: every shell _nc_runs_stdin knows on this machine, so also
    `$SHELL`, `${SHELL}`, `sudo -s|-i` and `su` without a command."""
    words = sorted(command_word_indexes(toks))
    for i in words:
        name, args = tool_name(toks[i]), list(toks[i + 1 :])
        if name in _NC_ELSEWHERE:
            return False
        shell = name in _PIPE_SHELLS or os.path.basename(toks[i]) in _NC_STDIN_SHELLS
        if shell and _hi_shell_reads_stdin(args):
            return True
        if (name == "sudo" and _sudo_runs_shell(args)) or (name == "su" and _su_runs_shell(args)):
            return True
    return False


# the environment names that reach the hook gate (git-guard): an assignment of one of these in front of a shell
# goes with the script that shell runs (0.8.0)
_HOOK_ENV_RE = re.compile(r"^(HUSKY|LEFTHOOK|SKIP|GIT_CONFIG_KEY_\w*|GIT_CONFIG_PARAMETERS)=")


def _nc_hook_env(toks) -> tuple:
    """The hook-gate assignments in front of the last command word of a simple command (`HUSKY=0 bash -c …`,
    `env SKIP=x sh -c …`): the environment of the script a shell there runs, and of nothing else."""
    if not toks or not any(_HOOK_ENV_RE.match(t) for t in toks):
        return ()
    last = max(command_word_indexes(toks), default=0)
    return tuple(t for t in toks[:last] if _HOOK_ENV_RE.match(t))


def _nc_runs_stdin(toks) -> bool:
    """The simple command runs a script read from its standard input: a shell at a command word with no -c
    script and no script file (also behind a wrapper or in a container), or ssh with no command after the
    host (the remote login shell reads it)."""
    for i in command_word_indexes(toks):
        name, args = os.path.basename(toks[i]), list(toks[i + 1 :])
        if name in _NC_STDIN_SHELLS and _hi_shell_reads_stdin(args):
            return True
        if (name == "sudo" and _sudo_runs_shell(args)) or (name == "su" and _su_runs_shell(args)):
            return True
        if name == "ssh":
            remote = _ssh_command(args)
            if remote == []:  # no command after the host: the remote login shell reads it
                return True
            # `ssh build 'bash -s'`: a quoted word after the host is a command line for the remote shell (0.8.0).
            # A plain word is a command word of this simple command already (ssh is a wrapper), so a chain
            # `ssh h0 ssh h1 …` is read once, not once per hop
            if remote and any(_nc_line_runs_stdin(w) for w in remote if any(c.isspace() for c in w)):
                return True
    return False


@functools.lru_cache(maxsize=64)
def _nc_line_runs_stdin(line: str) -> bool:
    """A command line (the quoted remote command of ssh) has a simple command that runs a script from stdin."""
    return any(_nc_runs_stdin(drop_redirections(seg)) for _sep, seg in simple_commands(line) if seg)


def _ssh_command(args) -> Optional[list]:
    """The words after the host of an ssh call ([] when there are none), or None when ssh names no host or runs
    no command at all (`-N`). Only the letters in front of the first one that takes a value are options: the
    rest of the word is its value (`-oStrictHostKeyChecking=No`, `-lNina`)."""
    k = _ssh_options(args, 0)
    if k is None or k >= len(args):
        return None
    # 0.9.0: an option behind the host is ssh's own too (`ssh build -T`): the command starts after them
    j = _ssh_options(args, k + 1)
    return None if j is None else list(args[j:])


def _ssh_options(args, k: int) -> Optional[int]:
    """The index of the first word from args[k] on that is no ssh option (past a `--`), or None for `-N` (no
    command at all)."""
    while k < len(args):
        t = args[k]
        if t == "--":
            return k + 1
        if not t.startswith("-") or len(t) < 2:
            return k
        for n, c in enumerate(t[1:], 1):
            if c == "N":
                return None
            if c in _SSH_VALUED:
                k += 0 if t[n + 1 :] else 1  # a value glued on (`-p2222`) or in the next word
                break
        k += 1
    return k


# sudo(8): options that take a value; `-s` and `-i` without a command run the target user's shell
_SUDO_VALUED = frozenset("CDghpRrTtUu")


def _sudo_runs_shell(args: list[str]) -> bool:
    """`sudo -s` or `sudo -i` (also `--shell`, `--login`, in a cluster) with no command: the shell reads stdin."""
    shell, skip = False, False
    for t in args:
        if skip:
            skip = False
        elif t in ("--shell", "--login"):
            shell = True
        elif t.startswith("--"):
            continue
        elif t.startswith("-") and len(t) > 1:
            for n, c in enumerate(t[1:], 1):
                if c in "si":
                    shell = True
                elif c in _SUDO_VALUED:
                    skip = not t[n + 1 :]
                    break
        elif not _ASSIGN_RE.match(t):
            return False  # a command: sudo runs that, not a shell
    return shell


def _su_runs_shell(args: list[str]) -> bool:
    """su(1) without -c and with no more than the user: the user's shell reads stdin (`su - deploy`)."""
    operands, skip = 0, False
    for t in args:
        if skip:
            skip = False
        elif t in ("-c", "--command") or t.startswith("--command=") or (
                t.startswith("-") and not t.startswith("--") and "c" in t):
            return False
        elif t in ("-s", "--shell", "-g", "--group", "-G", "--supp-group", "-w", "--whitelist-environment"):
            skip = True
        elif t == "-" or t.startswith("-"):
            continue
        else:
            operands += 1
    return operands <= 1


def _nc_scripts(toks: list[str]) -> list[str]:
    """The scripts one simple command hands to another shell: `sh -c` (and su, script, flock, $SHELL), `env -S`,
    `eval`, and the quoted words of ssh, watch, parallel, trap and tmux."""
    names = sum(1 for t in toks if os.path.basename(t) in _NC_SHELLS)
    if names > _MAX_TOOL_WORDS:  # each name may walk the rest of the command: bound the cost, ask instead
        raise CommandNotRead(_TOO_MANY_TOOLS)
    scripts = []
    words = command_word_indexes(toks)
    shell = remote = env = False
    for i, t in enumerate(toks):
        name = os.path.basename(t)
        if name in _NC_SHELLS:
            shell = True  # its script follows the next -c cluster (one walk serves every shell name before it)
        elif shell and (t == "--command" or _NC_DASH_C_RE.match(t)):
            shell = False
            script = _nc_operand(toks, i + 1)
            if script is not None:
                scripts.append(script)
        elif name == "eval" and i in words:
            start = i + 2 if i + 1 < len(toks) and toks[i + 1] == "--" else i + 1
            if start < len(toks):
                scripts.append(" ".join(toks[start:]))
        elif name in _NC_SCRIPT_WORDS and not remote:  # the first is enough: its later words hold any later one's
            remote = True
            scripts.extend(r for r in toks[i + 1 :] if any(c.isspace() for c in r))
        elif tool_name(name.lower()) == "env" and not env:  # F01: also `genv` (Homebrew) and `GENV` (macOS)
            env = True
            scripts.extend(_nc_split_string(toks, i))
        if name in _NC_SCRIPT_OPTIONS and i in words:
            scripts.extend(_nc_option_scripts(toks, i, *_NC_SCRIPT_OPTIONS[name]))
    return scripts


def _nc_option_scripts(toks, i: int, sub: str, options: frozenset) -> list[str]:
    """The scripts after toks[i] that are the value of one of `options` (`nix-shell --run '…'`, also
    `--run=…`), wherever the option stands; when `sub` is set, only after that subcommand (`npm exec -c '…'`)."""
    out = []
    seen = not sub
    for k in range(i + 1, len(toks)):
        t = toks[k]
        if not seen:
            seen = t == sub
            continue
        head, eq, value = t.partition("=")
        if t in options and k + 1 < len(toks):
            out.append(toks[k + 1])
        elif eq and head in options and head.startswith("--"):
            out.append(value)
    return out


def _nc_operand(toks, j: int) -> Optional[str]:
    """The first word from toks[j] on that is not an option: the script of `-c`. `--` is skipped, and so is the
    value of -o/+o/-O/+O (`bash -c -o pipefail 'script'`). A word that holds whitespace is no option, whatever
    it starts with (`bash -c '-x; rm -rf build'`)."""
    while j < len(toks):
        t = toks[j]
        if t == "--":
            return toks[j + 1] if j + 1 < len(toks) else None
        if t in _NC_VALUED:
            j += 2
            continue
        if len(t) < 2 or not t.startswith(("-", "+")) or any(c.isspace() for c in t):
            return t
        j += 1
    return None


def _nc_split_string(toks, i: int) -> list[str]:
    """The string of `env -S '…'`, `env -S'…'`, `env --split-string '…'` or `--split-string=…` after the env at
    toks[i]."""
    out = []
    for k in range(i + 1, len(toks)):
        t = toks[k]
        if t in ("-S", "--split-string"):
            out.extend(toks[k + 1 : k + 2])
        elif t.startswith("--split-string="):
            out.append(t[len("--split-string=") :])
        elif t.startswith("-S"):
            out.append(t[2:])
    return out


def command_word_indexes(toks) -> frozenset:
    """The indexes where a command name can stand: the first word after assignments, shell words and
    `function NAME`, and what a wrapper there runs (`sudo -u bob rm`, `timeout 10 rm`, `ssh host rm`,
    `find … -exec rm`), followed through wrapper chains. `command -v` is a lookup. Raises CommandNotRead past
    _MAX_COMMAND_WORDS. Memoised per token tuple: seven rules ask for the same simple commands."""
    got = _cwi_cached(tuple(toks))
    if isinstance(got, CommandNotRead):
        raise CommandNotRead(str(got))
    return got


@functools.lru_cache(maxsize=256)
def _cwi_cached(toks: tuple):
    """command_word_indexes' memo: the indexes, or the CommandNotRead that stopped the walk."""
    try:
        return frozenset(_command_word_indexes(toks))
    except CommandNotRead as exc:  # kept as a value so the next rule does not walk the words again
        return exc


def _command_word_indexes(toks: tuple) -> set:
    """command_word_indexes without the memo."""
    n = len(toks)
    i = 0
    while i < n:
        if _ASSIGN_RE.match(toks[i]) or toks[i] in _NC_SHELL_WORDS:
            i += 1
        elif toks[i] == "function":
            i += 2  # `function NAME { …`
        else:
            break
    if i >= n:
        return set()
    found = {i}
    work = [i]  # a work list, not recursion: a chain of wrappers is as long as the line
    while work:
        j = work.pop()
        name = tool_name(toks[j])
        if name == "find":
            later = [k + 1 for k in range(j + 1, n - 1) if toks[k] in _NC_FIND_EXEC]
        elif name in _NC_FD:
            later = [k + 1 for k in range(j + 1, n - 1) if toks[k] in _NC_FD_EXEC]
        elif name == "command" and j + 1 < n and toks[j + 1] in ("-v", "-V"):
            continue
        elif name == "coproc" and j + 2 < n and toks[j + 2] in ("{", "("):
            later = _nc_wrapped(toks, j + 1, 0)  # `coproc NAME { …`: a name stands only before a compound command
        elif name in _NC_OPTION_RUNNERS:
            later = _nc_option_wrapped(toks, j, _NC_OPTION_RUNNERS[name])
        elif name in _NC_AFTER_OPTION:  # `gdb … --args <command…>`, `lldb … -- <command…>`
            later = [k + 1 for k in range(j + 1, n - 1) if toks[k] in _NC_AFTER_OPTION[name]][:1]
        elif name in _NC_WRAPPERS:
            later = _nc_wrapped(toks, j, _NC_WRAPPERS[name])
        elif name in _NC_SUB_WRAPPERS:
            later = _nc_sub_wrapped(toks, j, _NC_SUB_WRAPPERS[name])
        else:
            continue
        for k in later:
            if k not in found:
                found.add(k)
                if len(found) > _MAX_COMMAND_WORDS:  # each candidate may walk the rest: bound the cost, ask
                    raise CommandNotRead(_TOO_MANY_WORDS)
                work.append(k)
    return found


def _nc_wrapped(toks, j: int, before: int) -> list[int]:
    """The indexes where the command run by the wrapper at toks[j] may stand. `before` plain words come first;
    an option without `=` may take the next plain word as its value (a "maybe"), so a plain word is a candidate
    when the plain words before it, less the maybes among them, are at most `before`, and at least `before`."""
    out = []
    plain = maybes = 0
    may_be_value = False
    for k in range(j + 1, len(toks)):
        t = toks[k]
        if t == "--":
            out.extend(range(k + 1, min(k + 2, len(toks))))
            break
        if t.startswith("-") and len(t) > 1:
            may_be_value = "=" not in t
            continue
        if _ASSIGN_RE.match(t) or t in _NC_SHELL_WORDS:  # `time { rm …`, `coproc { rm …`: `{` is not the command
            may_be_value = False
            continue
        if plain - maybes <= before <= plain:
            out.append(k)
        plain += 1
        maybes += may_be_value
        may_be_value = False
        if plain - maybes > before:
            break
    return out


def _nc_sub_wrapped(toks, j: int, subs: dict) -> list[int]:
    """The indexes where the command run by the runner or container tool at toks[j] may stand: find its
    subcommand (`run`, `compose run`) past the tool's options, with subcommand_hit's rule for an option's value,
    then read as a wrapper with that many plain words first. The word after the first `--` that follows the
    subcommand counts too (`mise exec node@20 -- rm`)."""
    path: tuple = ()
    may_be_value = False
    for k in range(j + 1, len(toks)):
        t = toks[k]
        if t == "--":
            return []
        if t.startswith("-") and len(t) > 1:
            may_be_value = "=" not in t
            continue
        step = (*path, t)
        if step in subs:
            out = _nc_wrapped(toks, k, subs[step])
            for m in range(k + 1, len(toks) - 1):
                if toks[m] == "--":
                    out.append(m + 1)
                    break
            return out
        if any(p[: len(step)] == step for p in subs):  # `compose`, `container`: the next word decides
            path, may_be_value = step, False
            continue
        if not may_be_value:
            return []
        may_be_value = False
    return []


def _nc_option_wrapped(toks, j: int, subs: dict) -> list[int]:
    """The index of the command run by `nix develop … -c <command…>` at toks[j]: find the subcommand past the
    tool's options, with subcommand_hit's rule for an option's value, then the word after the first of its
    options that hands over a command (`-c`, `--command`)."""
    may_be_value = False
    for k in range(j + 1, len(toks)):
        t = toks[k]
        if t == "--":
            return []
        if t.startswith("-") and len(t) > 1:
            may_be_value = "=" not in t
            continue
        if t in subs:
            return [m + 1 for m in range(k + 1, len(toks) - 1) if toks[m] in subs[t]][:1]
        if not may_be_value:
            return []
        may_be_value = False
    return []


def _is_redirection(t: str) -> bool:
    """A redirection word (`>out`, `2>&1`, `<<<word`); a quoted script such as `'>log rm -rf x'` holds whitespace
    and is no redirection."""
    return bool(_REDIRECT_TOKEN_RE.match(t)) and (t.startswith("<<<") or not any(c.isspace() for c in t))


def drop_redirections(args: list[str]) -> list[str]:
    """The arguments without redirections (`>out`, `2>1`, `> out`): a file name after `>` is no subcommand."""
    return [args[k] for k in _nc_kept(args)]


def _nc_kept(args: list[str]) -> list[int]:
    """The indexes of the words that are no redirection and no redirection's target."""
    out = []
    skip = False
    for k, t in enumerate(args):
        if skip:
            skip = False
        elif _BARE_REDIRECT_TOKEN_RE.match(t):
            skip = True  # the target is the next token
        elif not _is_redirection(t):
            out.append(k)
    return out


def subcommand_hit(args: list[str], verbs: frozenset, pairs: dict) -> Optional[str]:
    """The verb or pair ("apply", "compose down") a tool's arguments name as their subcommand, or None.

    The reader cannot know which options take a value, so an option without `=` may be followed by its value:
    that word is skipped once. Any other word is the real subcommand, and not one of ours."""
    first = ""  # the first word of a pair: the next word decides
    may_be_value = False
    for t in drop_redirections(args):
        if t == "--" or t in _NC_HELP:  # `terraform -help apply` prints help
            return None
        if t.startswith("-") and len(t) > 1:
            may_be_value = "=" not in t
            continue
        if first:
            if t in pairs[first]:
                return f"{first} {t}"
        elif t in verbs:
            return t
        elif t in pairs:
            first, may_be_value = t, False
            continue
        if not may_be_value:
            return None
        may_be_value = False
    return None


# ----------------------------------------------------------------------------
# Names in capitals (0.8.0): the owner's file system ignores case, so `GIT`, `/usr/bin/GIT`, `SUDO` and `BASH -c`
# run the real tools (measured). Every shell rule judges the command as written and, when a known tool name is
# written with a capital letter, also the text with those names folded to the spelling the tables use.
# ----------------------------------------------------------------------------

# the names the shell rules and the reader compare a command's name with: the keys of their tables, plus the names
# that stand only in an expression or a comparison of the code (SHELL_RE, FIND_RE, GIT_RE, TOOL_RE, CODE_RE,
# SCRIPT_RE, _SQL_CLIENT_RE, _DEPLOY_PATTERNS, _HI_COARSE, `head == "…"`, `name in ("…", …)`). Verbs, options and
# shell keywords are none; a key that is not lower-case itself (`$SHELL`) is not a folding target
_NAMES_IN_CODE = frozenset(
    "git gh sed az aws eval find xargs parallel curl wget http https xh cat echo printf tracker tracker.py ssh env"
    " export command coproc source node ruby perl python python3 pip pip3 sudo exec time nohup doas rm rmdir unlink"
    " trash shred truncate mise npm pnpm yarn brew cargo docker kubectl helm dropdb prisma rclone rsync bun deno"
    " bash sh zsh dash ksh tsx ts-node php psql mysql mariadb cqlsh snowsql duckdb cockroach hbase clickhouse"
    " terraform tofu hcloud pvesh qm pulumi cdk ansible-playbook flux del rd".split()
)
_FOLD_NAMES = frozenset(
    k for table in (
        _WRAPPERS, _RM_CLASS, _DELETE_TOOLS, _WRITERS_LAST, _WRITERS_ALL, _SEARCH_TOOLS, _DEPLOY_TABLE, _DEPLOY_ADDED,
        _OTHER_LLM_CLIS, _HI_TABLE, _HI_PAIRS, _HI_PAIRS_ONLY, _HI_BARE, _HI_SELF_FETCH, _HI_SHELLS, _HI_DOWNLOADERS,
        _HI_WRAPPERS, _HI_REMOTE, _NC_SHELLS, _NC_WRAPPERS, _NC_SUB_WRAPPERS, _NC_OPTION_RUNNERS, _NC_SCRIPT_OPTIONS,
        _NC_FD, _NC_ELSEWHERE, _NC_SCRIPT_WORDS, _NC_STDIN_SHELLS, _NC_AFTER_OPTION, _GNU_G_NAMES, _SECRET_STORES,
        _NAMES_IN_CODE, _CLOUD_CLIS,
    ) for k in table if k == k.lower()
)
_FOLD_RUN_RE = re.compile(r"[^\s;|&()<>`]+")  # a candidate: a run of characters between the shell's separators


def _known_name(name: str) -> bool:
    """A tool name the rules compare with, or a form _PIP_RE and _PYTHON_RE accept (`pip3.12`, `python3`)."""
    return name in _FOLD_NAMES or bool(_PIP_RE.match(name) or _PYTHON_RE.match(name))


def fold_names(text: str) -> str:
    """The text with every known tool name that is written with a capital letter replaced by the spelling the
    tables use. Of a run only the part after its last `/` counts; quotes and backslashes in it are looked through
    and kept (`G"I"T` -> `g"i"t`, `\\GIT` -> `\\git`). A part is folded only when it is no known name as written and
    its lower-case form is one, so `.ENV`, `FOO=GIT`, `$BASH`, `GIT-123-fix`, options and verbs stay as written."""
    if text == text.lower():
        return text
    out: list[str] = []
    last = 0
    for m in _FOLD_RUN_RE.finditer(text):
        run = m.group(0)
        if run == run.lower():
            continue
        # the script of an option starts behind its quote (`env -S'GIT …'`, `--run='GIT …'`, 0.8.0); an option
        # without a quote (`--name=GIT`) is read as before
        quotes = [q for q in (run.find("'"), run.find('"')) if q >= 0] if run[0] == "-" else []
        cut = max(run.rfind("/") + 1, min(quotes) + 1 if quotes else 0)
        part = run[cut:]
        bare = part.replace('"', "").replace("'", "").replace("\\", "")
        if _known_name(bare) or not _known_name(bare.lower()):
            continue
        out.append(text[last : m.start() + cut])
        out.append(part.lower())
        last = m.end()
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


def judged_twice(name: str, rule: "Rule") -> "Rule":
    """A shell rule that answers for the command as written and, when fold_names changes the text, also for the
    folded text: a deny from either wins, asks are combined. A command without a capital name is judged once,
    by the same code path as before. Two readings, not a `.lower()` at each comparison: three passes are
    expressions over the raw text, some matches are case-sensitive on purpose (the SQL keyword TRUNCATE), and with
    the reading as written kept nothing can get weaker."""

    @functools.wraps(rule)
    def judge(ev: Event, cfg: dict) -> Optional[Decision]:
        first = rule(ev, cfg)
        if ev.kind != "shell" or not ev.command:
            return first
        try:
            folded = fold_names(ev.command)
        except Exception as exc:  # main() turns a crash into exit 1, which both harnesses let run silently: ask
            return combine([d for d in (first, ("ask", READER_MSG.format(
                rule=name, what=f"the command could not be read ({type(exc).__name__})"))) if d])
        if folded == ev.command:
            return first
        twin = copy.copy(ev)
        twin.command = folded
        second = rule(twin, cfg)
        for d in (first, second):
            if d and d[0] == "deny":
                return d
        return combine([d for d in (first, second) if d])

    return judge


# ----------------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------------

Rule = Callable[[Event, dict], Optional[Decision]]
RULES: dict[str, Rule] = {
    "delete-guard": judged_twice("delete-guard", rule_delete_guard),
    "secret-write": rule_secret_write,
    "secret-read": rule_secret_read,
    "secret-shell": judged_twice("secret-shell", rule_secret_shell),
    "git-guard": judged_twice("git-guard", rule_git_guard),
    "deploy-ask": judged_twice("deploy-ask", rule_deploy_ask),
    "egress-guard": judged_twice("egress-guard", rule_egress_guard),
    "scratch-md": rule_scratch_md,
    "protected-branch": judged_twice("protected-branch", rule_protected_branch),
    "fan-out": rule_fan_out,
    "guard-config": judged_twice("guard-config", rule_guard_config),
    "tracker-guard": judged_twice("tracker-guard", rule_tracker_guard),
    "host-install": judged_twice("host-install", rule_host_install),
    "cloud-launch": judged_twice("cloud-launch", rule_cloud_launch),
    "github-tools": rule_github_tools,
}
PRE_RULES = list(RULES)


# ----------------------------------------------------------------------------
# Capture (plan step 1.3): record what each harness really sends
# ----------------------------------------------------------------------------

_SECRET_RES = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    # Azure DevOps PAT, current format: 84 chars, `AZDO` at [76:80]; the legacy 52-char base32 form is left
    # out (it matches any lower-case base32 run). Same pattern as the egress screen.
    re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{76}AZDO[A-Za-z0-9_-]{4}(?![A-Za-z0-9_-])"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT: Entra tokens for ADO
]


def redact(obj):
    home = os.path.expanduser("~")
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        s = obj.replace(home, "~") if home and home != "/" else obj
        for rx in _SECRET_RES:
            s = rx.sub("<redacted>", s)
        return s
    return obj


def capture(raw: dict, cfg: dict) -> int:
    ev = Event(raw)
    out_dir = os.path.join(telemetry_dir(cfg), "captures", ev.harness)
    try:
        os.makedirs(out_dir, exist_ok=True)
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        name = f"{ev.event or 'event'}-{ev.tool or 'none'}-{stamp}.json"
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            json.dump(redact(raw), fh, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        print(f"guard: capture failed: {exc}", file=sys.stderr)
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def _read_event() -> dict:
    data = sys.stdin.read()
    if not data.strip():
        raise ValueError("empty stdin; expected one JSON hook event")
    obj = json.loads(data)
    if not isinstance(obj, dict):
        raise ValueError("hook event must be a JSON object")
    return obj


# Both wirings cut the pre hook at 5 s, and a cut hook fails open (the call runs unjudged): answer before that.
# No environment variable sets it, since whoever starts a session could switch the budget off; tests set this.
# The rules run in a forked child that the hook kills at the budget. A SIGALRM timer was not enough: before
# Python 3.11 no signal handler runs inside one `re` search (measured on 3.9.6: a 1 MB `rsync a ` line answered
# after 26 s), and a watchdog thread would wait for the same interpreter lock that search holds.
HOOK_BUDGET_S = 3.5
BUDGET_MSG = (
    "guard: this call could not be judged within the hook's {budget} s budget (the command is {size} characters "
    "long); rules that did not judge it: {rules}. Confirm it yourself."
)
STOPPED_MSG = (
    "guard: the rules stopped before they finished judging this call (the command is {size} characters long); "
    "rules that did not judge it: {rules}. Confirm it yourself."
)
Verdicts = list  # [(rule name, Optional[Decision])] in the order the rules ran
_PIPE_DECODER = json.JSONDecoder()  # its own instance: the child's lines are ours, whatever replaces json.loads


def _rules_in_process(names: list, ev: Event, cfg: dict) -> Verdicts:
    """Run the rules in this process, without a budget: the path where there is no fork."""
    return [(name, RULES[name](ev, cfg)) for name in names]


def _rules_child(names: list, ev: Event, cfg: dict, wfd: int) -> None:
    """The forked child: one JSON line per rule's verdict, then `done`, or one `error` line. Never returns."""
    code = 0
    try:
        with os.fdopen(wfd, "w", encoding="utf-8") as out:
            try:
                for name in names:
                    out.write(json.dumps({"rule": name, "decision": RULES[name](ev, cfg)}) + "\n")
                    out.flush()
                out.write(json.dumps({"done": True}) + "\n")
            except Exception as exc:  # the parent raises it, so main prints the same `guard: error` as before
                out.write(json.dumps({"error": str(exc)}) + "\n")
    except BaseException:  # the pipe broke (the parent gave up) or the exit was asked for: nothing left to tell
        code = 1
    finally:
        try:
            sys.stderr.flush()  # a rule's warning on stderr; stdout belongs to the parent and is never flushed here
        except Exception:  # the child is leaving either way; a broken stderr changes nothing
            pass
        os._exit(code)  # never back into the caller: no second response, no log line, no test runner teardown


def _stop_child(pid: int) -> None:
    """Kill the child (gone already is fine) and reap it, so no process is left behind."""
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:  # it has exited and been reaped already
        pass
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:  # reaped elsewhere (SIGCHLD ignored by an embedding caller): nothing to wait for
        pass


def _read_verdicts(rfd: int, deadline: float) -> tuple:
    """(verdicts, outcome) from the child's pipe: outcome is done, budget (time ran out) or stopped (pipe ended)."""
    verdicts: Verdicts = []
    pending = b""
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return verdicts, "budget"
        ready, _, _ = select.select([rfd], [], [], left)
        if not ready:
            return verdicts, "budget"
        chunk = os.read(rfd, 65536)
        if not chunk:
            return verdicts, "stopped"  # killed or died: only the complete lines before count
        pending += chunk
        if b"\n" not in chunk:
            continue
        *lines, pending = pending.split(b"\n")
        for line in lines:
            try:
                msg = _PIPE_DECODER.decode(line.decode("utf-8"))
            except ValueError:  # not a line the child wrote whole: treat the rest as not judged
                return verdicts, "stopped"
            if "error" in msg:
                raise RuntimeError(msg["error"])  # str() is the rule's own text: main prints it as before
            if msg.get("done"):
                return verdicts, "done"
            d = msg.get("decision")
            verdicts.append((msg.get("rule"), tuple(d) if d else None))


def _run_rules(names: list, ev: Event, cfg: dict) -> tuple:
    """(verdicts, outcome) of the rules, run in a child the hook kills at HOOK_BUDGET_S.

    Where os.fork does not exist (Windows) or the fork fails, the rules run here without a budget, as before
    0.7.0: a named limit."""
    if not hasattr(os, "fork"):
        return _rules_in_process(names, ev, cfg), "done"
    rfd, wfd = os.pipe()
    deadline = time.monotonic() + HOOK_BUDGET_S
    try:
        pid = os.fork()
    except OSError:  # no process left to make (limits, memory): judge without a budget rather than not at all
        os.close(rfd)
        os.close(wfd)
        return _rules_in_process(names, ev, cfg), "done"
    if pid == 0:
        os.close(rfd)
        _rules_child(names, ev, cfg, wfd)
    os.close(wfd)
    try:
        return _read_verdicts(rfd, deadline)
    finally:
        os.close(rfd)
        _stop_child(pid)


POST_TAIL_BYTES = 128 * 1024  # the post hook reads this much of the log's end: an asked call is a recent line


def _call_id(ev: Event) -> Optional[str]:
    """The harness's id of this tool call: Claude Code sends tool_use_id before and after the call, Copilot none."""
    call = ev.raw.get("tool_use_id")
    return call if isinstance(call, str) and call else None


def _asked_rules(path: str, session: str, call: str) -> Optional[dict]:
    """The rules that asked about this call, from the tail of the log; None when it was not asked or already ran."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        start = max(0, fh.tell() - POST_TAIL_BYTES)
        fh.seek(start)
        lines = fh.read().split(b"\n")
    if start:
        lines = lines[1:]  # the first line is cut by the seek
    asked = None
    for line in lines:
        try:
            row = json.loads(line.decode("utf-8"))
        except ValueError:  # a broken or half-written line (UnicodeDecodeError is one too): not the call's
            continue
        if not isinstance(row, dict) or row.get("session") != session or row.get("call") != call:
            continue
        if row.get("verdict") == "ran":
            return None  # recorded already: a repeated event writes no second line
        rules = row.get("rules")
        if row.get("verdict") == "ask" and isinstance(rules, dict):
            asked = {name: "ran" for name, verdict in rules.items() if verdict == "ask"}
    return asked or None


def run_post() -> int:
    """PostToolUse and PostToolUseFailure: append a `ran` line when the guard asked about this call. Prints
    nothing and exits 0 in every case: the call has already happened, so there is nothing left to block."""
    try:
        raw = _read_event()
    except ValueError:  # empty, not JSON or not an object (JSONDecodeError is a ValueError): no call to record
        return 0
    ev = Event(raw)
    if ev.harness == "copilot":  # Copilot sends no call id, so no line of its log can be tied to this event
        return 0
    call = _call_id(ev)
    if call is None:  # without the id the ask cannot be tied to this call; guessing would invent evidence
        return 0
    cfg = load_config(str(raw.get("cwd") or os.getcwd()))
    try:
        rules = _asked_rules(os.path.join(telemetry_dir(cfg), "decisions.jsonl"), ev.session, call)
    except OSError:  # no log yet, or not readable: nothing was asked that this hook could find
        return 0
    if rules:
        log_decision(("ran", ""), rules, ev, cfg)
    return 0


# ----------------------------------------------------------------------------
# The box (item #66, plan step 1.0b): the facts the profile `box` reads, gathered by one function
# ----------------------------------------------------------------------------

BOX_MARKER = "/etc/agent-box/box.json"  # written by root at the box's start (tools/box/marker.py)
DOCKERENV = "/.dockerenv"
BOX_SCHEMA = "agent-box/1"
_MARKER_MAX = 64 * 1024  # a marker is a few hundred bytes; a larger file is no marker
# the facts of a machine with no marker; box_facts answers these when anything goes wrong
_NO_MARKER_FACTS = {"dockerenv": False, "marker_exists": False, "marker": None, "marker_uid": None,
                    "marker_writable": False, "marker_dir_writable": False, "guard_writable": True, "euid": None}


def box_facts() -> dict:
    """Everything the profile `box` reads (D1), and the only code that touches the marker and /.dockerenv.
    `marker` is the parsed JSON object, or None when the marker is missing, unreadable, no JSON object, too large
    or a symlink. Callers call it through the module global, once per hook call, and pass the dict on. Any error
    gives the facts of a machine with no marker."""
    try:
        me = os.path.realpath(__file__)
        exists = os.path.lexists(BOX_MARKER)
        st = os.lstat(BOX_MARKER) if exists else None
        marker = None
        if st is not None and stat.S_ISREG(st.st_mode):
            try:
                fd = os.open(BOX_MARKER, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
                try:
                    data = os.read(fd, _MARKER_MAX + 1)
                finally:
                    os.close(fd)
                parsed = json.loads(data.decode("utf-8")) if len(data) <= _MARKER_MAX else None
                marker = parsed if isinstance(parsed, dict) else None
            except (OSError, ValueError, RecursionError):  # unreadable or no JSON (a decode error is a ValueError)
                marker = None
        return {
            "dockerenv": os.path.exists(DOCKERENV),
            "marker_exists": exists,
            "marker": marker,
            "marker_uid": st.st_uid if st is not None else None,
            "marker_writable": os.access(BOX_MARKER, os.W_OK),
            "marker_dir_writable": os.access(os.path.dirname(BOX_MARKER), os.W_OK),
            "guard_writable": os.access(me, os.W_OK) or os.access(os.path.dirname(me), os.W_OK),
            "euid": os.geteuid(),
        }
    except Exception:  # a guard that cannot read its facts runs as on a machine with no marker
        return dict(_NO_MARKER_FACTS)


def in_box(facts: dict) -> bool:
    """A marker exists, /.dockerenv too, and this guard is a copy the session cannot write (the judge). The last
    fact is no security check (D2): it tells the judge, a read-only mount and the only copy the box's hooks run,
    from a working copy, whose tests answer as in CI. A missing fact counts against the box."""
    return bool(facts.get("dockerenv") and facts.get("marker_exists") and not facts.get("guard_writable", True))


def box_valid(facts: dict, cfg: dict) -> bool:
    """in_box, and the marker is root's, neither it nor its folder is writable by this process, the guard does not
    run as root, the marker says schema agent-box/1 and boundary own, and the effective boundary is own (D2)."""
    marker = facts.get("marker")
    euid = facts.get("euid")
    return (in_box(facts) and facts.get("marker_uid") == 0 and facts.get("marker_writable") is False
            and facts.get("marker_dir_writable") is False and isinstance(euid, int) and euid != 0
            and isinstance(marker, dict) and marker.get("schema") == BOX_SCHEMA and marker.get("boundary") == "own"
            and cfg.get("boundary") == "own")


def guard_root() -> str:
    """The folder of this guard's repository: three folders above its real path (`/judge` for
    `/judge/tools/guard/guard.py`). In a box the configuration is read there (D3)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


# The profile names where the session runs (D1 of item #65); step 1.0b adds `box`. Each entry: whether rules_off
# counts, and what an ask becomes (None: it stays an ask). Every ask of a rule or of the guard itself passes
# through the table where rules_off is applied: the combined ask is turned, so a deny keeps its own reasons.
CLOUD_ASK_MSG = ("cloud session (CLAUDE_CODE_REMOTE): this would ask on the owner's machine, and nobody can answer "
                 "here, so it is denied. {reason}")
PROFILES = {
    "host": {"rules_off": True, "ask": None},
    "cloud": {"rules_off": False, "ask": CLOUD_ASK_MSG},
}


def profile(environ: Optional[Mapping[str, str]] = None) -> str:
    """`cloud` when CLAUDE_CODE_REMOTE is true (the truth test of disposable_environment), else `host`."""
    env = os.environ if environ is None else environ
    return "cloud" if str(env.get("CLAUDE_CODE_REMOTE", "")).lower() not in ("", "0", "false") else "host"


def run_hook(target: str, wrapper: Optional[str]) -> int:
    if target == "post":  # never blocks, so it runs without the budget
        return run_post()
    raw = _read_event()
    cfg = load_config(str(raw.get("cwd") or os.getcwd()))
    if target == "capture":  # never blocks, so it runs without the budget
        return capture(raw, cfg)
    ev = Event(raw)
    # One Copilot path only: VS Code reads both .claude/settings.json and
    # .github/hooks; the github wrapper does the work there.
    if wrapper == "claude" and ev.harness == "copilot":
        return 0
    names = PRE_RULES if target == "pre" else [target]
    table = PROFILES[profile()]
    # rules_off silences a rule's asks in an own repo where the profile lets it; its denies stand, and any other
    # boundary keeps everything
    off = set(cfg["rules_off"]) if table["rules_off"] and cfg.get("boundary") == "own" else set()
    if host_install_silent(cfg):  # its knob silences host-install under every boundary; logged as skipped below
        off.add("host-install")
    decisions: list[Decision] = []
    fired: dict[str, str] = {}
    skipped: dict[str, str] = {}
    if target == "pre" and ev.unreadable:
        decisions.append(("ask", "guard: the tool arguments arrived as a string that is not JSON; no rule could read "
                                 "this call. Confirm it, and capture the event shape for the fixtures."))
        fired["unreadable-args"] = "ask"
    for name in names:
        if name not in RULES:
            raise ValueError(f"unknown rule: {name}")
    verdicts, outcome = _run_rules(names, ev, cfg)
    for name, d in verdicts:
        if d and name in off and d[0] == "ask":  # the rule still runs, so the log shows how often it was silenced
            skipped[name] = "skipped"
        elif d:
            decisions.append(d)
            fired[name] = d[0]
    if outcome != "done":  # the verdicts that arrived stand; a deny among them still wins in combine()
        late = ", ".join(names[len(verdicts):])
        msg = BUDGET_MSG if outcome == "budget" else STOPPED_MSG
        decisions.append(("ask", msg.format(budget=HOOK_BUDGET_S, size=len(ev.command or ""), rules=late)))
        fired["budget"] = "ask"
    final = combine(decisions)
    if final and final[0] == "ask" and table["ask"]:  # the profile's table; a deny keeps its own reasons
        final = "deny", table["ask"].format(reason=final[1])
        fired = {name: "deny" if v == "ask" else v for name, v in fired.items()}
    if final:
        log_decision(final, fired, ev, cfg)
    if skipped:
        log_decision(("skipped", "rules_off"), skipped, ev, cfg)
    return respond(final, ev.event or "PreToolUse")


def log_decision(decision: Decision, fired: dict[str, str], ev: Event, cfg: dict) -> None:
    """One line per ask/deny in <telemetry>/decisions.jsonl, so `ledger.py cost` can show prompt fatigue per rule.
    `rules` maps each rule that spoke to its own verdict; `verdict` is the combined one. A rule that would have
    spoken but is in `rules_off`, or host-install silenced by its knob (`off`, or `auto` in a disposable
    environment), is logged as `skipped` (its own line), so a month-long override stays visible.
    `guard` names the version that judged; `call` is the harness's tool_use_id when it sends one, and the post
    hook's `ran` line carries the same id, so an ask can be tied to the call that went ahead.
    No command text or paths: the rule names and the tool are enough to tune thresholds."""
    entry = {
        "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": decision[0],
        "rules": fired,
        "tool": ev.tool,
        "event": ev.event,
        "harness": ev.harness,
        "session": ev.session,
        "guard": VERSION,
        "profile": profile(),
    }
    call = _call_id(ev)
    if call:
        entry["call"] = call
    path = os.path.join(telemetry_dir(cfg), "decisions.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"guard: decision log failed: {exc}", file=sys.stderr)


def main(argv: list[str]) -> int:
    args = list(argv)
    wrapper = None
    if "--wrapper" in args:
        i = args.index("--wrapper")
        wrapper = args[i + 1] if i + 1 < len(args) else None
        del args[i : i + 2]
    if not args or args[0] in ("help", "-h", "--help"):
        print(__doc__.strip())
        return 0
    if args[0] == "version":
        print(VERSION)
        return 0
    if args[0] == "rules":
        for n in RULES:
            print(n)
        return 0
    if args[0] == "hook" and len(args) >= 2:
        try:
            return run_hook(args[1], wrapper)
        except Exception as exc:  # the guard failing is reported, never hidden
            print(f"guard: error: {exc}", file=sys.stderr)
            return 1
    print(__doc__.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
