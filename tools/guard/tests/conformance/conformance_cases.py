"""The cases of the guard's conformance run (tracker item #116), built at run time from the files on disk.

A case is one fresh folder and one or more calls of the guard's command line in it, in order. Kinds and ids:
  fixture:<rule>/<harness>/<word>/<file>  every rule fixture, as `hook <rule> --wrapper claude|github`
  shape:<harness>/<file>, crash:<file>    the recorded envelopes and the broken inputs, as `hook pre`
  <module>.<TABLE>:<n>                    each text-table row test_never_weaker.py reads, `hook pre --wrapper claude`
  cli:<name>, knob:<knob>:<event>         the command line itself, and the environment and configuration knobs
Standard library only, Python 3.9 and later: nothing is imported from the guard or from the test modules.
"""
import ast
import copy
import json
import pathlib
from dataclasses import dataclass, field
from typing import Optional, Union

TESTS = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = TESTS / "fixtures"
REPO = "/work/repo"  # the cwd a fixture records; every occurrence in an event becomes the case's repo/ folder
ORDER = {"silent": 0, "none": 0, "allow": 0, "ask": 1, "deny": 2}

# the tables test_never_weaker.py:167 (_table_inputs) reads; None: every upper-case ROWS_* table and FILE_ROWS
TABLES = {
    "test_table_forms": None,
    "test_bypass_forms": ("PINNED", "CLOSED", "CAPS", "OWN", "FIX", "FIX2", "FILES", "FIX_FILES"),
    "test_deploy_ask": ("REVIEW",),
}
FILE_TABLES = ("FILE_ROWS", "FILES", "FIX_FILES")
FILE_INPUT = {
    "Read": lambda p: {"file_path": p},
    "Write": lambda p: {"file_path": p, "content": "NAME=value\n"},
    "Edit": lambda p: {"file_path": p, "old_string": "a", "new_string": "b"},
}


@dataclass
class Call:
    args: list[str]  # appended to the program's command line
    stdin: bytes = b""  # REPO stands for the case's repo/ folder
    env: dict[str, str] = field(default_factory=dict)  # on top of the runner's environment


@dataclass
class Case:
    id: str
    calls: list[Call]
    config: Union[dict, str] = field(default_factory=dict)  # repo/.claude/guard.json (a str is written as is)
    local: Union[dict, str, None] = None  # repo/.claude/guard.local.json, when not None
    branch: Optional[str] = None  # repo/ is a git repository on this branch, when not None
    files: dict[str, str] = field(default_factory=dict)  # path relative to the case folder -> text
    expect: Optional[str] = None  # the verdict the source names (fixture folder, row), for the faithfulness test


def _event(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


def fixture_cases() -> list[Case]:
    out = []
    for path in sorted(FIXTURES.glob("*/*/*/*.json")):
        rel = path.relative_to(FIXTURES)
        rule, harness, word = rel.parts[:3]
        if rule.startswith("_"):
            continue
        fixture = json.loads(path.read_text(encoding="utf-8")).get("_fixture", {})
        wrapper = "claude" if harness == "claude" else "github"
        out.append(Case(
            f"fixture:{rel.as_posix()}", [Call(["hook", rule, "--wrapper", wrapper], path.read_bytes())],
            config=fixture.get("config", {}),
            # test_fixtures.py: scratch-md's recorded cwd is a repository root; workflow files go to the user folder
            branch="feat/x" if rule == "scratch-md" else None,
            files={f"claude-config/{k}": v for k, v in fixture.get("files", {}).items()},
            expect="silent" if word == "allow" else word))
    return out


def envelope_cases() -> list[Case]:
    out = []
    for kind, folder in (("shape", "_shapes"), ("crash", "_crash")):
        for path in sorted(p for p in (FIXTURES / folder).rglob("*") if p.is_file()):
            rel = path.relative_to(FIXTURES / folder).as_posix()
            out.append(Case(f"{kind}:{rel}", [Call(["hook", "pre"], path.read_bytes())]))
    return out


def _string_constants(path: pathlib.Path) -> dict[str, str]:
    """The module's top-level `NAME = "<str>"` assignments, read with ast: the table modules import pytest."""
    out = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            out[node.targets[0].id] = node.value.value
    return out


def table_rows() -> list[tuple]:
    """(id, event, branch, boundary, expected) for every row, read as test_never_weaker.py reads it."""
    out = []
    for module, names in TABLES.items():
        consts = _string_constants(TESTS / f"{module}.py")
        for name in names or sorted(k for k in consts if k.isupper() and (k.startswith("ROWS_") or k == "FILE_ROWS")):
            lines = [ln for ln in consts[name].splitlines() if ln.strip() and not ln.startswith("#")]
            for n, line in enumerate(lines):
                rid = f"{module}.{name}:{n}"
                if module == "test_deploy_ask":  # <rule> <ask|none> <command>, "ML:" holds \n for a newline
                    _rule, expected, command = line.split(None, 2)
                    if command.startswith("ML:"):
                        command = command[3:].replace("\\n", "\n")
                    branch, boundary = "feat/x", "own"
                else:
                    _tag, where, _rule, expected, command = (p.strip() for p in line.split(" | ", 4))
                    if name in FILE_TABLES:
                        out.append((rid, {"hook_event_name": "PreToolUse", "tool_name": where,
                                          "tool_input": FILE_INPUT[where](command), "cwd": REPO},
                                    "feat/x", "own", expected))
                        continue
                    if command.startswith('"'):
                        command = json.loads(command)
                    branch, _, boundary = where.partition("@")
                    boundary = boundary or "own"
                out.append((rid, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                  "tool_input": {"command": command}, "cwd": REPO}, branch, boundary, expected))
    return out


def table_cases() -> list[Case]:
    return [Case(rid, [Call(["hook", "pre", "--wrapper", "claude"], _event(ev))], config={"boundary": boundary},
                 branch=branch, expect=expected) for rid, ev, branch, boundary, expected in table_rows()]


def _shape(rel: str, **changes) -> dict:
    raw = json.loads((FIXTURES / "_shapes" / rel).read_text(encoding="utf-8"))
    raw.pop("_fixture", None)
    raw.update(changes)
    return raw


def _bash(command: str, harness: str = "claude", **changes) -> dict:
    raw = _shape("claude/PreToolUse-Bash.json" if harness == "claude" else "copilot/PreToolUse-bash.json", **changes)
    raw["tool_input"] = {"command": command}
    return raw


def cli_cases() -> list[Case]:
    pre = ["hook", "pre", "--wrapper", "claude"]
    rm = _event(_bash("rm -rf build"))
    token = "ghp_" + "A1b2C3d4" * 5  # built here, so no scanner reads a token in this file
    agent = _event(_shape("claude/PreToolUse-Agent.json"))
    start = _event(_shape("claude/SubagentStart-none.json"))
    post = _shape("claude/PostToolUse-Bash.json")
    post["tool_input"] = {"command": "rm -rf build"}
    post_failure = dict(post, hook_event_name="PostToolUseFailure")
    copilot_rm = _event(_bash("rm -rf build", "copilot"))
    calls = {
        "version": [Call(["version"])],
        "rules": [Call(["rules"])],
        "help": [Call(["help"])],
        "help-flag": [Call(["--help"])],
        "no-arguments": [Call([])],
        "unknown-command": [Call(["bogus"])],
        "hook-without-target": [Call(["hook"], rm)],
        "unknown-rule": [Call(["hook", "no-such-rule"], rm)],
        "wrapper-without-value": [Call(["hook", "pre", "--wrapper"], rm)],
        "capture": [Call(["hook", "capture"], _event(_bash(f"echo {token} > /dev/null")))],
        "capture-copilot": [Call(["hook", "capture", "--wrapper", "github"], copilot_rm)],
        "post-after-ask": [Call(pre, rm), Call(["hook", "post", "--wrapper", "claude"], _event(post)),
                           Call(["hook", "post", "--wrapper", "claude"], _event(post))],
        "post-failure-after-ask": [Call(pre, rm), Call(["hook", "post"], _event(post_failure))],
        "post-without-ask": [Call(["hook", "post"], _event(post))],
        "post-empty-stdin": [Call(["hook", "post"], b"")],
        "fan-out-six-agents": [Call(["hook", "fan-out", "--wrapper", "claude"], agent)] * 7,
        "fan-out-after-starts": [Call(["hook", "fan-out"], start)] * 5 + [Call(["hook", "fan-out"], agent)] * 2,
        "fan-out-through-pre": [Call(pre, agent)] * 6,
        "copilot-through-claude-wrapper": [Call(pre, copilot_rm)],
        "copilot-through-github-wrapper": [Call(["hook", "pre", "--wrapper", "github"], copilot_rm)],
        "not-utf-8": [Call(pre, _event(_bash("echo x")).replace(b"echo x", b"rm -rf \xff\xfe"))],
        "deny-reason-on-stderr": [Call(pre, _event(_bash("git push --force origin main")))],
    }
    return [Case(f"cli:{name}", c) for name, c in calls.items()]


KNOB_EVENTS = {
    "rm": _bash("rm -rf build"),  # delete-guard asks
    "pip": _bash("pip install requests"),  # host-install asks
    "commit": _bash("git commit -m x"),  # protected-branch denies on a protected branch
    "md": _shape("claude/PreToolUse-Write.json", tool_input={"file_path": "notes.md", "content": "x"}),  # scratch-md
    "openai": _bash("curl https://api.openai.com/v1/models"),  # egress-guard, by boundary
}
OWN = {"boundary": "own"}
# knob -> (events, env, guard.json, guard.local.json, branch); every case of a knob runs its events one per folder
KNOBS = {
    "rules-off-env": (("rm", "pip", "commit"), {"KZ_RULES_OFF": "delete-guard,host-install"}, OWN, None, "main"),
    "rules-off-env-no-git": (("rm",), {"KZ_RULES_OFF": "delete-guard"}, OWN, None, None),
    "rules-off-env-default-boundary": (("rm",), {"KZ_RULES_OFF": "delete-guard"}, {}, None, "feat/x"),
    "rules-off-env-unknown-rule": (("rm", "pip"), {"KZ_RULES_OFF": "no-such-rule,delete-guard"}, OWN, None, "feat/x"),
    "rules-off-env-client": (("rm",), {"KZ_RULES_OFF": "delete-guard"}, {"boundary": "client"}, None, "feat/x"),
    "rules-off-env-empty": (("rm",), {"KZ_RULES_OFF": ""}, OWN, {"rules_off": ["delete-guard"]}, "feat/x"),
    "rules-off-config": (("rm", "pip"), {}, dict(OWN, rules_off=["host-install"]), None, "feat/x"),
    "boundary-client-env": (("openai", "rm", "md"), {"KZ_BOUNDARY": "client"}, {}, None, "feat/x"),
    "boundary-own-env-on-client": (("openai",), {"KZ_BOUNDARY": "own"}, {"boundary": "client"}, None, "feat/x"),
    "boundary-unknown-env": (("openai",), {"KZ_BOUNDARY": "moon"}, {}, None, "feat/x"),
    "boundary-unknown-config": (("openai",), {}, {"boundary": "moon"}, None, "feat/x"),
    "host-install-off": (("pip", "rm"), {"KZ_HOST_INSTALL": "off"}, {}, None, "feat/x"),
    "host-install-off-client": (("pip",), {"KZ_HOST_INSTALL": "off"}, {"boundary": "client"}, None, "feat/x"),
    "host-install-unknown": (("pip",), {"KZ_HOST_INSTALL": "sometimes"}, {}, None, "feat/x"),
    "protected-env-on-release": (("commit", "md"), {"KZ_PROTECTED_BRANCHES": "release, hotfix"}, {}, None, "release"),
    "protected-env-on-main": (("commit",), {"KZ_PROTECTED_BRANCHES": "release"}, {}, None, "main"),
    "protected-config-none": (("commit",), {}, {"protected_branches": []}, None, "main"),
    "scratch-md-deny": (("md",), {"KZ_SCRATCH_MD": "deny"}, {}, None, "feat/x"),
    "scratch-md-off": (("md",), {"KZ_SCRATCH_MD": "off"}, {}, None, "feat/x"),
    "scratch-md-config-deny": (("md",), {}, {"scratch_md_mode": "deny"}, None, "feat/x"),
    "cloud": (("rm", "commit", "pip"), {"CLAUDE_CODE_REMOTE": "1"}, {}, None, "main"),
    "cloud-rules-off": (("rm",), {"CLAUDE_CODE_REMOTE": "true", "KZ_RULES_OFF": "delete-guard"}, OWN, None, "feat/x"),
    "cloud-false": (("rm",), {"CLAUDE_CODE_REMOTE": "false"}, {}, None, "feat/x"),
    "local-rules-off": (("rm", "pip"), {}, OWN, {"rules_off": ["delete-guard"]}, "feat/x"),
    "local-rules-off-client": (("rm",), {}, {"boundary": "client"}, {"rules_off": ["delete-guard"]}, "feat/x"),
    "local-rules-off-no-git": (("rm",), {}, OWN, {"rules_off": ["delete-guard"]}, None),
    "local-other-keys": (("commit", "openai"), {}, OWN, {"boundary": "client", "protected_branches": []}, "main"),
    "local-malformed": (("rm",), {}, OWN, {"rules_off": "delete-guard"}, "feat/x"),
    "local-broken-json": (("rm",), {}, OWN, "{not json", "feat/x"),
    "config-broken-json": (("rm",), {}, "{not json", None, "feat/x"),
}


def knob_cases() -> list[Case]:
    out = []
    for knob, (events, env, config, local, branch) in KNOBS.items():
        for name in events:
            call = Call(["hook", "pre", "--wrapper", "claude"], _event(copy.deepcopy(KNOB_EVENTS[name])), env)
            out.append(Case(f"knob:{knob}:{name}", [call], config=config, local=local, branch=branch))
    return out


def all_cases() -> list[Case]:
    cases = fixture_cases() + envelope_cases() + table_cases() + cli_cases() + knob_cases()
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case ids must be unique")
    return sorted(cases, key=lambda c: c.id)
