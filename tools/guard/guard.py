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

import datetime as _dt
import functools
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
from collections.abc import Mapping
from typing import Callable, Optional

VERSION = "0.6.1"

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
        self.kind = CLAUDE_TOOLS.get(self.tool) or COPILOT_TOOLS.get(self.tool) or "other"
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


def load_config(start: str) -> dict:
    """Merge DEFAULTS <- nearest .claude/guard.json (walking up) <- its sibling guard.local.json <- KZ_* env.

    guard.local.json is the owner's uncommitted override (gitignored): only its `rules_off` is read, so a
    session can silence rules without a diff in the reviewable policy and nothing else moves. rules_off is
    dropped unless guard.json sits beside `.git` and says `boundary: own` itself (not the default)."""
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
    env = os.environ.get("KZ_BOUNDARY")
    if env:
        cfg["boundary"] = env.strip()
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
    # SQL TRUNCATE only where a statement can start (line start, ; quote paren backtick): not prose such as
    # "may truncate the description" (0.7.0); the coreutils `truncate` command still asks through SHELL_RE
    r"|(?:^|[;\"'(`])\s*(?:TRUNCATE|truncate)\s"
    r"|(DELETE|delete)\s+(FROM|from)\s|rclone\s+(delete|purge|sync)|rsync\s.*--delete"
)
CODE_RE = (
    r"os\.(remove|unlink|rmdir|removedirs)|shutil\.rmtree|\.unlink\(|\.rmdir\(|send2trash"
    r"|fs\.(rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)|fsPromises\.(rm|unlink|rmdir)|rimraf"
    # Python `del (x)` as a word: not the tail of "model (" or "load_model(x)" (0.7.0)
    r"|\bdel\s*\("
    r"|remove_dir_all|remove_file|std::fs::remove|File\.(delete|unlink)|FileUtils\.(rm|remove)"
    r"|Remove-Item|Directory\.Delete|(^|\s)del\s+/[sq]|(^|\s)rd\s+/s"
)
DELETE_RE = re.compile("|".join([SHELL_RE, FIND_RE, GIT_RE, TOOL_RE, CODE_RE]), re.MULTILINE)
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
_DELETE_TOOLS: dict = {
    "mise": (frozenset({"uninstall", "prune"}), {}),
    "npm": (frozenset({"uninstall", "rm", "un", "r", "unlink"}), {}),
    "pnpm": (frozenset({"remove", "rm", "uninstall"}), {}),
    "yarn": (frozenset({"remove"}), {}),
    "brew": (frozenset({"uninstall", "remove", "rm"}), {}),
    "pip": (frozenset({"uninstall"}), {}),
    "cargo": (frozenset({"uninstall"}), {}),
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
    "uv": (frozenset(), {"pip": frozenset({"uninstall"}), "tool": frozenset({"uninstall"})}),
}
_SWITCH_DISCARDS = frozenset({"--discard-changes", "-f", "--force"})


def _git_discards(sub: str, rest: list[str]) -> bool:
    """`git checkout` and `git switch` forms that overwrite uncommitted work: checkout with `-- <path>`, `-f` or
    the operand `.`; switch with --discard-changes or -f."""
    if sub == "switch":
        return bool(_SWITCH_DISCARDS & set(rest))
    if sub != "checkout":
        return False
    if "-f" in rest or "--force" in rest or "." in rest:
        return True
    return "--" in rest and rest.index("--") + 1 < len(rest)  # `git checkout main --` names no path


def delete_what(command: str) -> Optional[str]:
    """What a command line would delete, read from the tokens of every simple command it runs, or None."""
    for toks in nested_commands(command):
        at_word = command_word_indexes(toks)
        named = 0
        for i, t in enumerate(toks):
            name = os.path.basename(t)
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
                if sub and (_GIT_DELETE_RE.match(" ".join(["git", sub, *rest])) or _git_discards(sub, rest)):
                    return f"`git {sub}` discards work"
                continue
            hit = subcommand_hit(list(toks[i + 1 :]), *entry)
            if hit:
                return f"`{name} {hit}` deletes"
    return None


def _delete_judge(ev: Event) -> Optional[str]:
    """What the command would delete: the text pass, the scan of a script it names, then the token pass."""
    if DELETE_RE.search(ev.command):
        return "command contains a delete/discard pattern"
    for m in SCRIPT_RE.finditer(ev.command):
        script = m.group(3)
        p = script if os.path.isabs(script) else os.path.join(ev.cwd, script)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                if DELETE_RE.search(fh.read()):
                    return f"script {script} contains a delete/discard pattern"
        except (OSError, ValueError):
            continue  # not a readable file (missing, a directory, a NUL byte in the name): nothing to scan
    return delete_what(strip_heredocs(ev.command))


def rule_delete_guard(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    try:
        what = _delete_judge(ev)
    except CommandNotRead as exc:  # too deep or too many tools: ask rather than pass it unread
        what = str(exc)
    except Exception as exc:  # main() turns a crash into exit 1, which both harnesses let run silently: ask instead
        what = f"the command could not be read ({type(exc).__name__})"
    return ("ask", DELETE_MSG.format(what=what)) if what else None



# ----------------------------------------------------------------------------
# Shell helpers
# ----------------------------------------------------------------------------

_SEP_RE = re.compile(r"\|\||&&|[;|]|\n")
_WRAPPERS = {"sudo", "env", "command", "exec", "time", "nohup", "doas", "builtin"}
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


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
            i += 1
            while i < len(toks) and toks[i].startswith("-") and toks[i] != "--":
                i += 1
        if i < len(toks):
            out.append(tuple(toks[i:]))
    return tuple(out)


def _expand(tok: str, cwd: str) -> str:
    t = os.path.expanduser(tok.replace("$HOME", "~"))
    return t if os.path.isabs(t) else os.path.normpath(os.path.join(cwd, t))


_HEREDOC_RE = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)(?:\n\2(?:\n|$)|\Z)", re.DOTALL
)


def strip_heredocs(command: str) -> str:
    """Drop here-document bodies: they are data for a command, not commands (the delete-guard keeps them)."""
    return _HEREDOC_RE.sub(lambda m: m.group(0)[: m.start(3) - m.start(0)], command)


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
    """'secret' (deny on write, ask on read), 'tfvars' (ask on write), or None."""
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
    if secret_class(ev.abspath()) == "secret":
        return "ask", SECRET_READ_MSG.format(path=ev.path)
    return None


_REDIRECT_RE = re.compile(r"(?<![<>])>{1,2}\s*([^\s;&|]+)")
_WRITERS_LAST = {"cp", "mv", "install", "scp", "rsync", "ln"}
_WRITERS_ALL = {"tee", "truncate", "touch", "chmod", "chown"}


def _secret_seg(seg: list[str], cwd: str, writes: list[str], reads: list[str]) -> None:
    """Add the secret files one simple command writes and reads to the two lists."""
    head = os.path.basename(seg[0])
    paths = [t for t in seg[1:] if not t.startswith("-") and t != "--"]
    targets: list[str] = []
    if head in _WRITERS_LAST and paths:
        targets = paths[-1:]
    elif head in _WRITERS_ALL:
        targets = paths
    elif head == "sed" and any(t.startswith("-i") for t in seg):
        targets = paths
    elif head == "git" and len(seg) > 1 and seg[1] in ("add", "stage"):
        targets = paths[1:] if paths and paths[0] in ("add", "stage") else paths
    for t in targets:
        if secret_class(_expand(t, cwd)) == "secret":
            writes.append(t)
    for t in paths:
        if t not in targets and secret_class(_expand(t, cwd)) == "secret":
            reads.append(t)


def _secret_verdict(writes: list[str], reads: list[str]) -> Optional[Decision]:
    if writes:
        return "deny", SECRET_WRITE_MSG.format(path=", ".join(dict.fromkeys(writes)))
    if reads:
        return "ask", SECRET_READ_MSG.format(path=", ".join(dict.fromkeys(reads)))
    return None


def rule_secret_shell(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    writes: list[str] = []
    reads: list[str] = []
    command = strip_heredocs(ev.command)
    for target in _REDIRECT_RE.findall(command):
        target = target.strip("\"'`,;)")
        if secret_class(_expand(target, ev.cwd)) == "secret":
            writes.append(target)
    for seg in segments(command):
        _secret_seg(seg, ev.cwd, writes, reads)
    if writes:
        return _secret_verdict(writes, reads)
    # the reader pass adds to the same lists, so one message names every file of both passes
    failed = reader_pass(command, lambda seg: _secret_seg(seg, ev.cwd, writes, reads), "secret-shell")
    return combine([d for d in (_secret_verdict(writes, reads), failed) if d])


# ----------------------------------------------------------------------------
# git-guard: no force push, no push to a protected branch, no --no-verify
# ----------------------------------------------------------------------------

_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
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


def _git_guard_seg(seg: list[str], cwd: str, protected: set) -> Optional[Decision]:
    """The git-guard verdict on one simple command: a hook bypass, a forced push, a push to a protected branch."""
    sub, rest = _git_subcommand(seg)
    if sub is None:
        return None
    if "--no-verify" in rest or (sub == "commit" and "-n" in rest):
        return "deny", GIT_MSG.format(what=f"`git {sub} --no-verify` skips the commit gate")
    if sub != "push":
        return None
    if any(t in _FORCE_FLAGS or t.startswith("--force-with-lease=") for t in rest):
        return "deny", GIT_MSG.format(what="force push")
    if "--all" in rest or "--mirror" in rest:
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
        branch = current_branch(cwd)
        if branch in protected:
            return "deny", GIT_MSG.format(what=f"push to protected branch '{branch}'")
        return None
    for r in refspecs:
        if r.startswith("+"):
            return "deny", GIT_MSG.format(what=f"force refspec {r}")
        dest = r.split(":", 1)[1] if ":" in r else r
        if dest.startswith("refs/heads/"):
            dest = dest[len("refs/heads/") :]
        if dest == "HEAD":
            dest = current_branch(cwd) or dest
        if dest in protected:
            return "deny", GIT_MSG.format(what=f"push to protected branch '{dest}'")
    return None


def rule_git_guard(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    protected = protected_branches(cfg)
    command = strip_heredocs(ev.command)
    for seg in segments(command):
        d = _git_guard_seg(seg, ev.cwd, protected)
        if d:
            return d
    return reader_pass(command, lambda seg: _git_guard_seg(seg, ev.cwd, protected), "git-guard")


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
    "kubectl": (_verbs("label annotate set run taint expose autoscale"), {}),
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
_AWS_DESTROY = ("delete-", "terminate-")
_AWS_UPDATES = {"ecs": _verbs("update-service"),
                "lambda": _verbs("update-function-code update-function-configuration")}
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


def _az_changes(args: list[str]) -> Optional[str]:
    """0.6.0's az expressions in token form: pipeline runs, deployments, and delete/create past the first word."""
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
    if {"deploy", "update", "up"} & set(args[1:]) and not _NC_HELP & set(args):  # 0.7.0 words
        return "az changes resources"
    return None


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
        return _az_changes(args)
    if name == "ansible-playbook":
        return label if _ansible_runs(args, at_command_word) else None
    hit = subcommand_hit(args, verbs, pairs)
    if not hit:
        return _deploy_added(name, args, label)
    if hit == "s3 sync" and "--delete" not in args:
        return None
    return "aws s3 deletes" if name == "aws" and hit.startswith("s3 ") else label


def _deploy_added(name: str, args: list[str], label: str) -> Optional[str]:
    """The label when the 0.7.0 rows find a change; a help probe anywhere in the call is none."""
    if name == "aws":
        hit = _aws_hit(args)
        label = ("aws deletes or terminates resources" if hit and hit.split()[1].startswith(_AWS_DESTROY)
                 else "aws updates a service or function")
    elif name in _DEPLOY_ADDED:
        hit = subcommand_hit(args, *_DEPLOY_ADDED[name])
    else:
        return None
    if not hit or _NC_HELP & set(args):
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
    try:
        text = strip_heredocs(ev.command)
        what = _deploy_text(text) or deploy_what(text)  # the 0.6.0 verdict OR the token verdict
    except CommandNotRead as exc:  # too deep or too many tools: ask rather than pass it unread
        what = str(exc)
    except Exception as exc:  # main() turns a crash into exit 1, which both harnesses let run silently: ask instead
        what = f"the command could not be read ({type(exc).__name__})"
    return ("ask", DEPLOY_MSG.format(what=what)) if what else None


# ----------------------------------------------------------------------------
# egress-guard: inside a client boundary, other-vendor LLM tools need a yes
# ----------------------------------------------------------------------------

_OTHER_LLM_CLIS = {"agy", "gemini", "codex", "llm", "openai", "ollama", "aider", "cursor-agent"}
_LLM_HOSTS_RE = re.compile(
    r"api\.openai\.com|generativelanguage\.googleapis\.com|openrouter\.ai|api\.mistral\.ai|api\.together\.xyz|api\.anthropic\.com"
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
    for seg in segments(strip_heredocs(ev.command)):
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
        for seg in segments(command):
            d = _commit_on_protected(seg, ev.cwd, protected)
            if d:
                return d
        # the local reading: a commit behind ssh or inside a container happens in another checkout
        return reader_pass(command, lambda seg: _commit_on_protected(seg, ev.cwd, protected), "protected-branch",
                           local=True)
    return None


def _commit_on_protected(seg: list[str], cwd: str, protected: set) -> Optional[Decision]:
    """Deny when one simple command is a `git commit` in a checkout whose branch is protected."""
    sub, _rest = _git_subcommand(seg)
    if sub != "commit":
        return None
    where = _git_c_dir(seg, cwd)
    branch = current_branch(where)
    if branch in protected:
        return "deny", PROTECTED_MSG.format(what="`git commit`", branch=branch, root=where)
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
GUARD_CONFIG_MSG = (
    "Guard-the-guard: {path} is {what}; it polices this very session, so a human confirms every change "
    "(and AGENTS.md rule 4 wants the why in DECISIONS.md)."
)


def guard_config_class(path: Optional[str]) -> Optional[str]:
    """What kind of hook configuration a path is, or None for an ordinary file."""
    if not path:
        return None
    home_claude = os.path.join(os.path.expanduser("~"), ".claude")
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
        if part == "tools" and nxt == "guard":
            return "the guard itself"
    return None


def rule_guard_config(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind not in ("write", "edit"):
        return None
    what = guard_config_class(ev.abspath())
    if what is None:
        return None
    return "ask", GUARD_CONFIG_MSG.format(path=ev.path, what=what)


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
    for seg in segments(command):
        d = _tracker_seg(seg)
        if d:
            return d
    return reader_pass(command, _tracker_seg, "tracker-guard")


def _tracker_seg(seg: list[str]) -> Optional[Decision]:
    """The tracker-guard verdict on one simple command: a write to issues, labels or work items past the tracker."""
    head = os.path.basename(seg[0])
    if head == "az":
        d = _az_tracker_guard(seg)
        if d:
            return d
    if head == "gh" and len(seg) >= 3 and seg[1] == "issue" and seg[2] in _GH_ISSUE_REPLACEMENT:
        return "deny", TRACKER_MSG.format(what=f"`gh issue {seg[2]}` bypasses the tracker",
                                          use=_GH_ISSUE_REPLACEMENT[seg[2]])
    if head == "gh" and len(seg) >= 3 and seg[1] == "label" and seg[2] in ("create", "edit", "delete", "clone"):
        return "deny", TRACKER_MSG.format(what=f"`gh label {seg[2]}` bypasses the tracker",
                                          use="`tracker owner labels-sync` (a human runs it)")
    if head == "gh" and len(seg) >= 3 and seg[1] == "api":
        path, skip = "", False
        for t in seg[2:]:
            if skip:
                skip = False
            elif t in _GH_API_VALUE_FLAGS:
                skip = True
            elif not t.startswith("-"):
                path = t
                break
        method = (_flag_value(seg, {"-X", "--method"}) or "GET").upper()
        mutating = method != "GET" or any(t in _GH_API_MUTATING_FLAGS for t in seg)
        if _ISSUE_API_RE.search(path) and mutating:
            return "deny", TRACKER_MSG.format(what=f"`gh api {method} {path}` writes issues or labels",
                                              use="the tracker verbs")
    if head in ("curl", "wget", "http", "https", "xh"):
        url = next((t for t in seg[1:] if ("api.github.com/repos/" in t and _ISSUE_API_RE.search(t))
                    or _ADO_WIT_RE.search(t)), "")
        if url and _http_writes(seg, head, url):
            return "deny", TRACKER_MSG.format(what=f"`{head}` writes to {url}", use="the tracker verbs")
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
# a wrapper that reaches one of these first hands over to a container or another machine: not judged (decision 7)
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
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if tick and c == "`":
            return j
        if not tick and c in "()":
            depth += 1 if c == "(" else -1
            if depth == 0:
                return j
        j += 1
    return len(text)


def _hi_prepare(text: str) -> tuple[str, list[str]]:
    """One quote-aware pass before the lexer. Drops backslash-newline and comments, takes the `&` out of a
    redirection (2>&1, >&2, &>) so it does not split the command, and collects the body of every $( … ) and
    backtick substitution written inside double quotes: the host shell runs it."""
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
            out.append(c)
            i += 2
            continue
        elif c == "&" and text[i + 1 : i + 2] == ">":  # &>, &>>
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
    for j in range(1, len(toks)):
        name = os.path.basename(toks[j])
        if name in _HI_REMOTE:
            return []  # the container or remote route, also behind a wrapper (decision 7)
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


def _hi_shell_reads_stdin(args: list[str]) -> bool:
    """A shell reads its program from stdin: no -c script, and no operand unless -s is given."""
    if _hi_dash_c(args) is not None:
        return False
    s_flag, skip, options = False, False, True
    for t in args:
        if skip:
            skip = False
        elif options and t in ("-o", "+o"):
            skip = True
        elif options and t == "--":
            options = False
        elif options and t.startswith(("-", "+")):
            s_flag = s_flag or (not t.startswith("--") and "s" in t[1:])
        else:
            return s_flag  # an operand is a script file, unless -s reads the program from stdin
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
    """Walk a table tool's tokens left to right (decision 10)."""
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
    head, args = os.path.basename(toks[0]), toks[1:]
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
    """Judge each simple command, then the downloaded-script forms that span commands (decision 9)."""
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

    # the local reading: what this machine runs; a container or remote tool ends the simple command
    return reader_pass(command, judge, "host-install", local=True)


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
_BARE_REDIRECT_TOKEN_RE = re.compile(r"^\d*(<|>|>>|<<|<<-|<<<|<>)$")
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
}
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
    **dict.fromkeys("docker-compose podman-compose kubectl oc".split(), {("run",): 1, ("exec",): 1}),
    "devcontainer": {("exec",): 0},
}
# the local reading ends at these command words: the command after them runs in a container or on another host
_NC_ELSEWHERE = _HI_REMOTE | {"podman-compose"}
# names whose quoted words are command lines for a shell: `ssh host '…'`, `watch '…'`, `parallel '…' ::: a`,
# `trap '…' EXIT`, `tmux send-keys '…' Enter`
_NC_SCRIPT_WORDS = frozenset("ssh watch parallel trap tmux".split())
_NC_FIND_EXEC = frozenset("-exec -execdir -ok -okdir".split())
_NC_HELP = frozenset("-h -help --help".split())
_NC_FALLBACK_SPLIT_RE = re.compile(r"\|\||&&|[;|\n()`]")


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
    return got


@functools.lru_cache(maxsize=16)
def _nc_cached(command: str, local: bool = False):
    """nested_commands' memo: the token tuples, or the CommandNotRead that stopped the read."""
    out: list[tuple[str, ...]] = []
    try:
        _nc_read(command, 0, out, set(), local)
    except CommandNotRead as exc:  # kept as a value so the second rule does not read the line again
        return exc
    return tuple(out)


def _nc_read(text: str, depth: int, out: list, seen: set, local: bool = False) -> None:
    """Append the simple commands of one line to out, then read what each nests one level deeper."""
    if depth > _HI_MAX_DEPTH:
        if text.strip():
            raise CommandNotRead(_HI_NOT_READ)
        return
    prepared, subs = _hi_prepare(text)
    cmds = _hi_lex(prepared)
    if cmds is None:  # an unbalanced quote: raw words between separators, brackets and backticks, ends unquoted
        parts = [[w for w in (t.strip("'\"\\") for t in tokens(p)) if w] for p in _NC_FALLBACK_SPLIT_RE.split(prepared)]
    else:
        parts = [toks for _sep, toks in cmds]
    nested = list(subs)  # substitutions outside quotes are simple commands of their own in the lexer already
    for raw in parts:
        kept = _nc_kept(raw)
        toks = [raw[k] for k in kept]
        if local:
            cut = _nc_remote_word(toks)
            if cut is not None:  # the words from the container or remote tool on run elsewhere
                raw = raw[: kept[cut]]
                toks = toks[:cut]
        nested.extend(_nc_here_strings(raw))  # taken from the words before the redirections go: `<<<` is one
        if not toks:
            continue
        out.append(tuple(toks))
        nested.extend(_nc_scripts(toks))
    for script in nested:
        if script not in seen:  # one read per distinct script: a repeated nest costs nothing twice
            seen.add(script)
            _nc_read(script, depth + 1, out, seen, local)


def _nc_remote_word(toks: list[str]) -> Optional[int]:
    """The first command word of a simple command that names a container or remote tool, or None."""
    return min((i for i in command_word_indexes(toks) if os.path.basename(toks[i]) in _NC_ELSEWHERE), default=None)


READER_MSG = "{rule}: {what}. Confirm the command; the guard could not check it."


def reader_pass(text: str, judge: Callable[[list[str]], Optional[Decision]], rule: str,
                local: bool = False) -> Optional[Decision]:
    """The token pass of a rule that first reads segments(): judge the words from every command word of every
    simple command the line runs. The first deny wins; asks are combined. Never raises: a line the reader could
    not read, or a crash, asks with the reason (a rule's own deny from its first pass is returned before this)."""
    try:
        asks = []
        for toks in nested_commands(text, local):
            for i in sorted(command_word_indexes(toks)):
                d = judge(list(toks[i:]))
                if d and d[0] == "deny":
                    return d
                if d:
                    asks.append(d)
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
        elif name == "env" and not env:
            env = True
            scripts.extend(_nc_split_string(toks, i))
    return scripts


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
        name = os.path.basename(toks[j])
        if name == "find":
            later = [k + 1 for k in range(j + 1, n - 1) if toks[k] in _NC_FIND_EXEC]
        elif name == "command" and j + 1 < n and toks[j + 1] in ("-v", "-V"):
            continue
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
# Registry
# ----------------------------------------------------------------------------

Rule = Callable[[Event, dict], Optional[Decision]]
RULES: dict[str, Rule] = {
    "delete-guard": rule_delete_guard,
    "secret-write": rule_secret_write,
    "secret-read": rule_secret_read,
    "secret-shell": rule_secret_shell,
    "git-guard": rule_git_guard,
    "deploy-ask": rule_deploy_ask,
    "egress-guard": rule_egress_guard,
    "scratch-md": rule_scratch_md,
    "protected-branch": rule_protected_branch,
    "fan-out": rule_fan_out,
    "guard-config": rule_guard_config,
    "tracker-guard": rule_tracker_guard,
    "host-install": rule_host_install,
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
# No environment variable sets it, since whoever starts a session could switch the timer off; tests set this.
HOOK_BUDGET_S = 3.5
BUDGET_MSG = (
    "guard: this call could not be judged within the hook's {budget} s budget (the command is {size} characters "
    "long); rules that did not judge it: {rules}. Confirm it yourself."
)


class BudgetExceeded(BaseException):
    """Raised by the SIGALRM handler; a BaseException, so a rule's `except Exception` cannot swallow it."""


def _on_budget(signum, frame) -> None:
    """SIGALRM handler: stop the running rule (a handler that raises also stops a running `re` match)."""
    raise BudgetExceeded()


def _arm_budget() -> Optional[tuple]:
    """Start the wall-clock budget; return (previous handler,), or None where nothing was armed."""
    if not (hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM")):
        return None  # Windows: no interval timer, the hook runs as before 0.7.0
    try:
        previous = signal.signal(signal.SIGALRM, _on_budget)
    except ValueError:  # not the main thread (an embedding caller): run without a budget rather than fail
        return None
    signal.setitimer(signal.ITIMER_REAL, HOOK_BUDGET_S)
    return (previous,)


def _disarm_budget(armed: Optional[tuple]) -> None:
    """Stop the timer, then put the previous handler back; harmless when called twice."""
    if armed is None:
        return
    signal.setitimer(signal.ITIMER_REAL, 0)
    previous = armed[0]
    signal.signal(signal.SIGALRM, signal.SIG_DFL if previous is None else previous)  # None: set outside Python


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
    # rules_off silences a rule's asks in an own repo; its denies stand, and any other boundary keeps everything
    off = set(cfg["rules_off"]) if cfg.get("boundary") == "own" else set()
    if host_install_silent(cfg):  # its knob silences host-install under every boundary; logged as skipped below
        off.add("host-install")
    decisions: list[Decision] = []
    fired: dict[str, str] = {}
    skipped: dict[str, str] = {}
    if target == "pre" and ev.unreadable:
        decisions.append(("ask", "guard: the tool arguments arrived as a string that is not JSON; no rule could read "
                                 "this call. Confirm it, and capture the event shape for the fixtures."))
        fired["unreadable-args"] = "ask"
    judged = 0  # rules whose verdict is recorded; the rest are named in the budget ask
    armed = _arm_budget()
    try:
        for name in names:
            rule = RULES.get(name)
            if rule is None:
                raise ValueError(f"unknown rule: {name}")
            d = rule(ev, cfg)
            if d and name in off and d[0] == "ask":  # the rule still runs, so the log shows how often it was silenced
                skipped[name] = "skipped"
            elif d:
                decisions.append(d)
                fired[name] = d[0]
            judged += 1  # counted after the verdict is kept: an alarm in between names the rule, never drops it
        _disarm_budget(armed)  # inside the try: an alarm that fires before the timer is off is still caught
    except BudgetExceeded:  # the finished rules' verdicts stand; a deny among them still wins in combine()
        _disarm_budget(armed)
        decisions.append(("ask", BUDGET_MSG.format(budget=HOOK_BUDGET_S, size=len(ev.command or ""),
                                                   rules=", ".join(names[judged:]))))
        fired["budget"] = "ask"
    finally:
        _disarm_budget(armed)
    final = combine(decisions)
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
