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
  guard.py rules | help | version
"""

import datetime as _dt
import json
import os
import re
import shlex
import socket
import subprocess
import sys
from typing import Callable, Optional

VERSION = "0.5.0"

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
    "scratch_md_allow": [
        "docs/", ".claude/", ".github/", "skills/", "agents/", ".agents/", "evidence/",
        "README.md", "DECISIONS.md", "AGENTS.md", "CLAUDE.md", "CHANGELOG.md", "CONTRIBUTING.md",
        "SECURITY.md", "LICENSE.md", "**/README.md", "**/SKILL.md", "**/AGENTS.md",
    ],
}


def load_config(start: str) -> dict:
    """Merge DEFAULTS <- nearest .claude/guard.json (walking up) <- KZ_* env."""
    cfg = dict(DEFAULTS)
    d = os.path.abspath(start)
    while True:
        candidate = os.path.join(d, ".claude", "guard.json")
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    cfg.update(data)
            except (OSError, ValueError) as exc:  # a broken config must not silently vanish
                print(f"guard: ignoring unreadable {candidate}: {exc}", file=sys.stderr)
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
    r"|(TRUNCATE|truncate)\s|(DELETE|delete)\s+(FROM|from)\s|rclone\s+(delete|purge|sync)|rsync\s.*--delete"
)
CODE_RE = (
    r"os\.(remove|unlink|rmdir|removedirs)|shutil\.rmtree|\.unlink\(|\.rmdir\(|send2trash"
    r"|fs\.(rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)|fsPromises\.(rm|unlink|rmdir)|rimraf|del\s*\("
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


def rule_delete_guard(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    if DELETE_RE.search(ev.command):
        return "ask", DELETE_MSG.format(what="command contains a delete/discard pattern")
    for m in SCRIPT_RE.finditer(ev.command):
        script = m.group(3)
        p = script if os.path.isabs(script) else os.path.join(ev.cwd, script)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                if DELETE_RE.search(fh.read()):
                    return "ask", DELETE_MSG.format(
                        what=f"script {script} contains a delete/discard pattern"
                    )
        except OSError:
            continue  # not a readable file: nothing to scan
    return None



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
    """Token lists for each simple command of a compound line, wrappers and assignments stripped."""
    out = []
    for part in _SEP_RE.split(command):
        toks = tokens(part)
        while toks and (_ASSIGN_RE.match(toks[0]) or toks[0] in _WRAPPERS):
            toks = toks[1:]
            while toks and toks[0].startswith("-") and toks[0] != "--":
                toks = toks[1:]
        if toks:
            out.append(toks)
    return out


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


def rule_secret_shell(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    writes, reads = [], []
    command = strip_heredocs(ev.command)
    for target in _REDIRECT_RE.findall(command):
        target = target.strip("\"'`,;)")
        if secret_class(_expand(target, ev.cwd)) == "secret":
            writes.append(target)
    for seg in segments(command):
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
            if secret_class(_expand(t, ev.cwd)) == "secret":
                writes.append(t)
        for t in paths:
            if t not in targets and secret_class(_expand(t, ev.cwd)) == "secret":
                reads.append(t)
    if writes:
        return "deny", SECRET_WRITE_MSG.format(path=", ".join(dict.fromkeys(writes)))
    if reads:
        return "ask", SECRET_READ_MSG.format(path=", ".join(dict.fromkeys(reads)))
    return None


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


def rule_git_guard(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    protected = protected_branches(cfg)
    for seg in segments(strip_heredocs(ev.command)):
        sub, rest = _git_subcommand(seg)
        if sub is None:
            continue
        if "--no-verify" in rest or (sub == "commit" and "-n" in rest):
            return "deny", GIT_MSG.format(what=f"`git {sub} --no-verify` skips the commit gate")
        if sub != "push":
            continue
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
            branch = current_branch(ev.cwd)
            if branch in protected:
                return "deny", GIT_MSG.format(what=f"push to protected branch '{branch}'")
            continue
        for r in refspecs:
            if r.startswith("+"):
                return "deny", GIT_MSG.format(what=f"force refspec {r}")
            dest = r.split(":", 1)[1] if ":" in r else r
            if dest.startswith("refs/heads/"):
                dest = dest[len("refs/heads/") :]
            if dest == "HEAD":
                dest = current_branch(ev.cwd) or dest
            if dest in protected:
                return "deny", GIT_MSG.format(what=f"push to protected branch '{dest}'")
    return None


# ----------------------------------------------------------------------------
# deploy-ask: anything that changes a live environment needs an explicit yes
# ----------------------------------------------------------------------------

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


def rule_deploy_ask(ev: Event, cfg: dict) -> Optional[Decision]:
    if ev.event != "PreToolUse" or ev.kind != "shell" or not ev.command:
        return None
    for part in _SEP_RE.split(strip_heredocs(ev.command)):
        if _DRY_RE.search(part):
            continue
        for rx, label in _DEPLOY_RES:
            if rx.search(" " + part.strip()) or rx.search(part):
                return "ask", DEPLOY_MSG.format(what=label)
    return None


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
        for seg in segments(strip_heredocs(ev.command)):
            sub, _rest = _git_subcommand(seg)
            if sub != "commit":
                continue
            where = _git_c_dir(seg, ev.cwd)
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
        if part == ".claude" and last and (_SETTINGS_RE.match(nxt) or nxt == "guard.json"):
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
_TEMP_ALLOWED_LABELS = {"agent-loop", "handoff"}  # until step 3.8 moves the private app repo's loop onto the tracker
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


def _az_tracker_guard(seg: list[str]) -> Optional[Decision]:
    """`az boards work-item` writes, `az devops invoke`, `az rest` writes to _apis/wit, PR completion shortcuts."""
    words: list[str] = []
    for t in seg[1:]:  # az finds its command in the words before the first option
        if t.startswith("-"):
            break
        words.append(t)
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
        head = os.path.basename(seg[0])
        if head == "az":
            d = _az_tracker_guard(seg)
            if d:
                return d
        if head == "gh" and len(seg) >= 3 and seg[1] == "issue" and seg[2] in _GH_ISSUE_REPLACEMENT:
            label = _flag_value(seg, {"--label", "-l"})
            if seg[2] == "create" and label and set(label.split(",")) <= _TEMP_ALLOWED_LABELS:
                continue
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


def run_hook(target: str, wrapper: Optional[str]) -> int:
    raw = _read_event()
    cfg = load_config(str(raw.get("cwd") or os.getcwd()))
    if target == "capture":
        return capture(raw, cfg)
    ev = Event(raw)
    # One Copilot path only: VS Code reads both .claude/settings.json and
    # .github/hooks; the github wrapper does the work there.
    if wrapper == "claude" and ev.harness == "copilot":
        return 0
    names = PRE_RULES if target == "pre" else [target]
    decisions: list[Decision] = []
    fired: dict[str, str] = {}
    for name in names:
        rule = RULES.get(name)
        if rule is None:
            raise ValueError(f"unknown rule: {name}")
        d = rule(ev, cfg)
        if d:
            decisions.append(d)
            fired[name] = d[0]
    final = combine(decisions)
    if final:
        log_decision(final, fired, ev, cfg)
    return respond(final, ev.event or "PreToolUse")


def log_decision(decision: Decision, fired: dict[str, str], ev: Event, cfg: dict) -> None:
    """One line per ask/deny in <telemetry>/decisions.jsonl, so `ledger.py cost` can show prompt fatigue per rule.
    `rules` maps each rule that spoke to its own verdict; `verdict` is the combined one.
    No command text or paths: the rule names and the tool are enough to tune thresholds."""
    entry = {
        "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": decision[0],
        "rules": fired,
        "tool": ev.tool,
        "event": ev.event,
        "harness": ev.harness,
        "session": ev.session,
    }
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
