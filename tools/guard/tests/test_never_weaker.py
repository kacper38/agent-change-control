"""Never weaker (item #65, plan step 1.7, D10): every row and fixture of guard 0.9.0 keeps its verdict or gets a
stricter one, and every change is listed here with the decision that makes it.

baseline-0.9.0.jsonl holds, per input, what guard 0.9.0 (commit 5664b5a) answered: `pre`, the combined answer of
`hook pre` (silent < ask < deny), and `rule`, the answer of the rule the row or fixture names (for rule `shell`
the strongest of the eight shell rules). It was written by this module run as a script:

    git show 5664b5a:tools/guard/guard.py > /tmp/guard-0.9.0.py
    python3 tools/guard/tests/test_never_weaker.py --write /tmp/guard-0.9.0.py

Covered inputs: the text tables of test_table_forms.py (every ROWS_* table and FILE_ROWS), of test_bypass_forms.py
(PINNED, CLOSED, CAPS, OWN, FIX, FIX2, FILES, FIX_FILES) and of test_deploy_ask.py (REVIEW), and every fixture under
fixtures/<rule>/ as of 5664b5a (the baseline keeps the event; the file name only labels it). Not covered: the
parametrize lists of the other modules (code, not text tables; each keeps its own expectation and runs on its own),
the cases that need a real tree or prior state (protected-branch, scratch-md and fan-out against a repository or a
spawn count: here `current_branch` gives the row's branch, `git_root` finds no repository and `log_spawn` counts 1,
so the answers do not depend on the machine), the rows added for 0.10.0 (they state their own expectations), and
fixtures/_shapes and _crash (envelopes and broken stdin, judged by no rule).

Each input is judged as the row tests judge it: a shell row as a Bash call in /nonexistent-scratch on the row's
branch and boundary, a file row as that tool on the path, a fixture as recorded with its cwd moved under
/nonexistent-scratch. `pre` goes through run_hook in process, with no cloud variable, KZ_RULES_OFF unset and
host_install `ask` (the knob is a knob, not a verdict: test_host_install.py covers it).
"""
import argparse
import contextlib
import copy
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
BASELINE = HERE / "baseline-0.9.0.jsonl"
FIXTURES = HERE / "fixtures"
SCRATCH = "/nonexistent-scratch"
SHELL_RULES = ("delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
               "tracker-guard", "host-install")
TABLES = {
    "test_table_forms": None,  # every upper-case text table of the module
    "test_bypass_forms": ("PINNED", "CLOSED", "CAPS", "OWN", "FIX", "FIX2", "FILES", "FIX_FILES"),
    "test_deploy_ask": ("REVIEW",),
}
FILE_TABLES = ("FILE_ROWS", "FILES", "FIX_FILES")
FILE_INPUT = {
    "Read": lambda p: {"file_path": p},
    "Write": lambda p: {"file_path": p, "content": "NAME=value\n"},
    "Edit": lambda p: {"file_path": p, "old_string": "a", "new_string": "b"},
}
ORDER = {"silent": 0, "ask": 1, "deny": 2}

# The changed verdicts: id | which (pre or rule) | 0.9.0 | 0.10.0 | decision. Every one is stricter; a change that
# is not listed fails, and a listed change that did not happen fails too.
CHANGES = r"""
# D7: the CI workflows and the tracker join guard-config's paths. D8: a read of the owner's stored GitHub
# credentials is denied (it asked as a stored secret at 0.9.0). D9: a write of a remote-tracking ref is denied.
test_table_forms.FILE_ROWS:29 | pre | silent | ask | D7
test_table_forms.FILE_ROWS:29 | rule | silent | ask | D7
test_table_forms.FILE_ROWS:32 | pre | silent | ask | D7
test_table_forms.FILE_ROWS:32 | rule | silent | ask | D7
fixture:guard-config/claude/allow/04-github-workflows-ci-yml.json | pre | silent | ask | D7
fixture:guard-config/claude/allow/04-github-workflows-ci-yml.json | rule | silent | ask | D7
fixture:guard-config/claude/allow/05-tools-tracker-cli-py.json | pre | silent | ask | D7
fixture:guard-config/claude/allow/05-tools-tracker-cli-py.json | rule | silent | ask | D7
fixture:guard-config/copilot/allow/04-github-workflows-ci-yml.json | pre | silent | ask | D7
fixture:guard-config/copilot/allow/04-github-workflows-ci-yml.json | rule | silent | ask | D7
fixture:guard-config/copilot/allow/05-tools-tracker-cli-py.json | pre | silent | ask | D7
fixture:guard-config/copilot/allow/05-tools-tracker-cli-py.json | rule | silent | ask | D7
test_table_forms.ROWS_B4:176 | pre | ask | deny | D8
test_table_forms.ROWS_B4:176 | rule | ask | deny | D8
test_table_forms.ROWS_B4:178 | pre | ask | deny | D8
test_table_forms.ROWS_B4:178 | rule | ask | deny | D8
test_table_forms.ROWS_B4:179 | pre | ask | deny | D8
test_table_forms.ROWS_B4:179 | rule | ask | deny | D8
test_table_forms.ROWS_B4:186 | pre | ask | deny | D8
test_table_forms.ROWS_B4:186 | rule | ask | deny | D8
test_table_forms.ROWS_B4:187 | pre | ask | deny | D8
test_table_forms.ROWS_B4:187 | rule | ask | deny | D8
test_table_forms.ROWS_B4:205 | pre | ask | deny | D8
test_table_forms.ROWS_B4:205 | rule | ask | deny | D8
test_table_forms.ROWS_B4:206 | pre | ask | deny | D8
test_table_forms.ROWS_B4:206 | rule | ask | deny | D8
test_table_forms.ROWS_B4:207 | pre | ask | deny | D8
test_table_forms.ROWS_B4:207 | rule | ask | deny | D8
test_table_forms.ROWS_B4:211 | pre | ask | deny | D8
test_table_forms.ROWS_B4:211 | rule | ask | deny | D8
test_table_forms.ROWS_B4:218 | pre | ask | deny | D8
test_table_forms.ROWS_B4:218 | rule | ask | deny | D8
test_table_forms.ROWS_B4:219 | pre | ask | deny | D8
test_table_forms.ROWS_B4:219 | rule | ask | deny | D8
test_table_forms.ROWS_B4:221 | pre | ask | deny | D8
test_table_forms.ROWS_B4:221 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:125 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:125 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:126 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:126 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:127 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:127 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:128 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:128 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:129 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:129 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:130 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:130 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:165 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:165 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:166 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:166 | rule | ask | deny | D8
test_table_forms.ROWS_FIX:185 | pre | ask | deny | D8
test_table_forms.ROWS_FIX:185 | rule | ask | deny | D8
test_bypass_forms.FILES:20 | pre | ask | deny | D8
test_bypass_forms.FILES:20 | rule | ask | deny | D8
test_bypass_forms.FILES:21 | pre | ask | deny | D8
test_bypass_forms.FILES:21 | rule | ask | deny | D8
test_bypass_forms.FILES:22 | pre | ask | deny | D8
test_bypass_forms.FILES:22 | rule | ask | deny | D8
test_bypass_forms.FILES:33 | pre | ask | deny | D8
test_bypass_forms.FILES:33 | rule | ask | deny | D8
test_bypass_forms.FILES:34 | pre | ask | deny | D8
test_bypass_forms.FILES:34 | rule | ask | deny | D8
fixture:secret-read/claude/ask/06-config-gh-hosts-yml.json | pre | ask | deny | D8
fixture:secret-read/claude/ask/06-config-gh-hosts-yml.json | rule | ask | deny | D8
fixture:secret-read/copilot/ask/06-config-gh-hosts-yml.json | pre | ask | deny | D8
fixture:secret-read/copilot/ask/06-config-gh-hosts-yml.json | rule | ask | deny | D8
test_table_forms.ROWS_B4:121 | pre | silent | deny | D9
test_table_forms.ROWS_B4:121 | rule | silent | deny | D9
"""  # noqa: E501


def _changes() -> dict:
    out = {}
    for line in CHANGES.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        rid, which, old, new, why = (p.strip() for p in line.split(" | ", 4))
        assert ORDER[new] > ORDER[old], f"a listed change must be stricter: {line}"
        assert (rid, which) not in out, f"listed twice: {line}"
        out[(rid, which)] = (old, new, why)
    return out


# ----------------------------------------------------------------------------
# The inputs
# ----------------------------------------------------------------------------

def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _table_inputs() -> list:
    """(id, input) for every row of the covered text tables."""
    out = []
    for module, names in TABLES.items():
        mod = _load(f"_never_weaker_{module}", HERE / f"{module}.py")
        for name in names or sorted(k for k, v in vars(mod).items() if k.isupper() and isinstance(v, str)
                                    and (k.startswith("ROWS_") or k == "FILE_ROWS")):
            lines = [ln for ln in getattr(mod, name).splitlines() if ln.strip() and not ln.startswith("#")]
            for n, line in enumerate(lines):
                rid = f"{module}.{name}:{n}"
                if module == "test_deploy_ask":  # <rule> <ask|none> <command>, "ML:" holds \n for a newline
                    rule, _verdict, command = line.split(None, 2)
                    if command.startswith("ML:"):
                        command = command[3:].replace("\\n", "\n")
                    out.append((rid, {"branch": "feat/x", "boundary": "own", "rule": rule, "command": command}))
                    continue
                tag, where, rule, _expected, text = (p.strip() for p in line.split(" | ", 4))
                if name in FILE_TABLES:
                    out.append((rid, {"tool": where, "rule": rule, "path": text}))
                    continue
                if text.startswith('"'):
                    text = json.loads(text)
                branch, _, boundary = where.partition("@")
                out.append((rid, {"branch": branch, "boundary": boundary or "own", "rule": rule, "command": text}))
    return out


# the keys of a recorded event that a verdict can depend on; the rest (ids, transcript paths) is left out
_RAW_KEYS = ("hook_event_name", "hookEventName", "tool_name", "toolName", "tool_input", "toolArgs", "cwd",
             "timestamp")


def _fixture_inputs() -> list:
    """(id, input) for every fixture on disk. The input holds the event itself, not the file name: the corpus is
    regenerated when a case moves (an allow case of 0.9.0 that asks at 0.10.0), and the names shift with it."""
    out = []
    for path in sorted(FIXTURES.glob("*/*/*/*.json")):
        rel = path.relative_to(FIXTURES)
        if rel.parts[0].startswith("_"):
            continue
        raw = json.loads(path.read_text())
        inp = {"fixture": {k: raw[k] for k in _RAW_KEYS if k in raw}, "rule": rel.parts[0]}
        if raw.get("_fixture", {}).get("config"):
            inp["config"] = raw["_fixture"]["config"]
        out.append((f"fixture:{rel.as_posix()}", inp))
    return out


def _event(inp: dict) -> tuple:
    """(raw event, branch, boundary, rule, extra config) for one input."""
    if "fixture" in inp:
        raw = copy.deepcopy(inp["fixture"])
        raw["cwd"] = SCRATCH + str(raw.get("cwd") or "/")
        extra = inp.get("config", {})
        return raw, None, extra.get("boundary", "own"), inp["rule"], extra
    if "tool" in inp:
        raw = {"hook_event_name": "PreToolUse", "tool_name": inp["tool"], "tool_input": FILE_INPUT[inp["tool"]](
            inp["path"]), "cwd": SCRATCH}
        return raw, "feat/x", "own", inp["rule"], {}
    raw = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": inp["command"]},
           "cwd": SCRATCH}
    return raw, inp["branch"], inp["boundary"], inp["rule"], {}


def _word(d) -> str:
    return d[0] if d else "silent"


def answers(guard, inp: dict) -> tuple:
    """(pre, rule) as guard (a loaded guard module) answers for one input."""
    raw, branch, boundary, rule, extra = _event(inp)
    seen: list = []
    env = {k: v for k, v in os.environ.items()
           if k not in ("KZ_RULES_OFF", "KZ_BOUNDARY", "KZ_PROTECTED_BRANCHES", "KZ_SCRATCH_MD", "CLAUDE_CODE_REMOTE")}
    env["KZ_HOST_INSTALL"] = "ask"
    if boundary != "own":
        env["KZ_BOUNDARY"] = boundary
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, env, clear=True))
        for name, value in (("current_branch", lambda cwd: branch), ("git_root", lambda d: None),
                            ("log_spawn", lambda ev, cfg: 1),
                            ("_run_rules", lambda names, ev, cfg: (guard._rules_in_process(names, ev, cfg), "done")),
                            ("_read_event", lambda: copy.deepcopy(raw)),
                            ("respond", lambda final, name: seen.append(final) or 0)):
            stack.enter_context(mock.patch.object(guard, name, value))
        guard.run_hook("pre", None)
        cfg = {**guard.load_config(raw["cwd"]), "host_install": "ask", **extra}
        ev = guard.Event(copy.deepcopy(raw))
        names = SHELL_RULES if rule == "shell" else (rule,)
        got = [_word(guard.RULES[n](ev, cfg)) for n in names]
    return _word(seen[-1] if seen else None), max(got, key=ORDER.__getitem__)


def inputs() -> list:
    return _table_inputs() + _fixture_inputs()


# ----------------------------------------------------------------------------
# The test
# ----------------------------------------------------------------------------

def _baseline() -> list:
    return [json.loads(ln) for ln in BASELINE.read_text().splitlines() if ln.strip()]


def test_the_baseline_covers_the_tables_and_fixtures_of_090():
    ids = [row["id"] for row in _baseline()]
    assert len(ids) == len(set(ids)) and len(ids) > 4000, len(ids)
    assert sum(i.startswith("fixture:") for i in ids) > 1000
    assert {i.split(":")[0] for i in ids if not i.startswith("fixture:")} >= {
        "test_table_forms.ROWS_B", "test_table_forms.FILE_ROWS", "test_bypass_forms.CAPS", "test_deploy_ask.REVIEW"}


def test_every_090_verdict_holds_or_gets_stricter(guard):
    changes = _changes()
    weaker, unlisted, wrong, seen = [], [], [], set()
    for row in _baseline():
        pre, rule = answers(guard, row["in"])
        for which, old, new in (("pre", row["pre"], pre), ("rule", row["rule"], rule)):
            key = (row["id"], which)
            if new == old:
                continue
            seen.add(key)
            what = f"{row['id']} {which}: {old} -> {new} {json.dumps(row['in'])}"
            if ORDER[new] < ORDER[old]:
                weaker.append(what)
            elif key not in changes:
                unlisted.append(what)
            elif changes[key][:2] != (old, new):
                wrong.append(f"{what}; listed as {changes[key][0]} -> {changes[key][1]}")
    missing = [f"{rid} {which}: listed {old} -> {new} ({why}), did not happen"
               for (rid, which), (old, new, why) in changes.items() if (rid, which) not in seen]
    assert weaker == [], "a move toward silence:\n" + "\n".join(weaker)
    assert unlisted == [] and wrong == [] and missing == [], "\n".join(unlisted + wrong + missing)


# ----------------------------------------------------------------------------
# Writing the baseline (run once with guard 0.9.0)
# ----------------------------------------------------------------------------

def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", metavar="GUARD_PY", required=True, help="the guard.py of 0.9.0")
    ns = ap.parse_args(argv)
    guard = _load("guard", pathlib.Path(ns.write))
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"KZ_TELEMETRY_DIR": tmp}):
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            lines = []
            for rid, inp in inputs():
                pre, rule = answers(guard, inp)
                lines.append(json.dumps({"id": rid, "in": inp, "pre": pre, "rule": rule}, sort_keys=True))
        finally:
            os.chdir(cwd)
    BASELINE.write_text("\n".join(lines) + "\n")
    print(f"guard {guard.VERSION}: {len(lines)} inputs written to {BASELINE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
