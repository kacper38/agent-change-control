"""The conformance run of the guard (tracker item #116): the golden file is what the Python guard answers now, from
any case root; two false programs fail it; and each answer keeps the verdict its source names."""
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import conformance_cases as cc  # noqa: E402 (the folder is no package)
import conformance_runner as cr  # noqa: E402

GUARD = [sys.executable, str(HERE.parent.parent / "guard.py")]
JOBS = cr.DEFAULT_JOBS
COUNTS = {"fixture": 1573, "shape": 28, "crash": 3, "table": 3234, "cli": 22, "knob": 42}
SILENT_FAILS, DENY_FAILS = 3319, 4902  # cases the always-silent and the always-denying program fail

# Faithfulness (scope item 5). A fixture's answer has its folder's verdict (allow = silent); a table row's `hook pre`
# answer is at least as strict as the row's own word. Every difference: id | source's word | answer | reason. An
# unlisted difference fails, and so does a listed one that no longer happens (the pattern of CHANGES in
# test_never_weaker.py). At 0.12.2 there is none: the table is empty.
DIFFERENCES = r"""
"""


def _kind(case_id: str) -> str:
    head = case_id.split(":", 1)[0]
    return "table" if "." in head else head


def _verdict(answer: dict) -> str:
    out = answer["calls"][-1]["stdout"]
    return json.loads(out)["permissionDecision"] if out else "silent"


def _program(tmp_path: pathlib.Path, name: str, body: str) -> list:
    script = tmp_path / f"{name}.sh"
    script.write_text("#!/bin/sh\ncat > /dev/null\n" + body, encoding="utf-8")
    return ["/bin/sh", str(script)]


@pytest.fixture(scope="module")
def cases():
    return cr.select(None)


@pytest.fixture(scope="module")
def live(cases, tmp_path_factory):
    return cr.run_cases(cases, GUARD, tmp_path_factory.mktemp("root-a"), JOBS)


def test_counts(cases):
    kinds: dict = {}
    for case in cases:
        kinds[_kind(case.id)] = kinds.get(_kind(case.id), 0) + 1
    assert kinds == COUNTS
    assert len(cc.table_rows()) == COUNTS["table"]


def test_golden_is_sorted_complete_and_small(cases, golden):
    text = cr.GOLDEN.read_text(encoding="utf-8")
    assert text == cr.golden_text(golden), "one sorted JSON line per case: write it with `record` only"
    assert list(golden) == sorted(c.id for c in cases)
    assert len(text.encode("utf-8")) <= 6_000_000


def test_golden_is_what_the_guard_answers_now(golden, live):
    diff = cr.differing(golden, live)
    assert diff == [], cr.describe(diff[0], golden.get(diff[0]), live.get(diff[0]))


def test_the_answers_do_not_depend_on_the_case_root(live, control):
    """`live` ran guard.py in place from one root; `control` (conftest.py) a copy at <tmp>/tools/guard/guard.py from
    a root of another name and depth: neither the case root nor the guard's place changes an answer."""
    diff = cr.differing(live, control)
    assert diff == [], cr.describe(diff[0], live.get(diff[0]), control.get(diff[0]))


def test_two_false_programs_fail_the_run(cases, golden, tmp_path):
    silent = _program(tmp_path, "silent", "exit 0\n")
    deny = _program(tmp_path, "deny", "printf '%s\\n' '{\"permissionDecision\": \"deny\", "
                                      "\"permissionDecisionReason\": \"no\"}'\necho no >&2\nexit 2\n")
    for argv, fails in ((silent, SILENT_FAILS), (deny, DENY_FAILS)):
        got = cr.run_cases(cases, argv, tmp_path / "root", JOBS)
        assert len(cr.differing(golden, got)) == fails, argv


def test_the_command_line_exit_codes(tmp_path, capsys):
    root = ["--root", str(tmp_path), "--only", "cli:version", "--only", "crash:"]
    assert cr.main(["run", "--guard", " ".join(GUARD), *root]) == 0
    assert "4 cases, 0 differ" in capsys.readouterr().out
    assert cr.main(["run", "--guard", " ".join(_program(tmp_path, "silent", "")), *root]) == 1
    assert "crash:array.json" in capsys.readouterr().out
    assert cr.main(["run", "--guard", "no-such-program-here", *root]) == 2
    assert cr.main(["run", "--guard", " ".join(GUARD), "--reference", " ".join(GUARD), *root]) == 0
    below = tmp_path / "repo" / "deep"
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert cr.main(["run", "--guard", " ".join(GUARD), "--root", str(below), "--only", "cli:version"]) == 2
    assert ".git lies above the case root" in capsys.readouterr().err


def test_bytes_that_are_not_utf_8_survive_the_golden_file(tmp_path):
    raw = _program(tmp_path, "raw", "printf 'a\\377\\376b'\nprintf '\\200' >&2\n")
    got = cr.run_cases(cr.select(["cli:version"]), raw, tmp_path, 1)
    call = got["cli:version"]["calls"][0]
    assert call["stdout"] == {"base64": "Yf/+Yg=="} and call["stderr"] == {"base64": "gA=="}
    assert json.loads(cr.golden_text(got)) == got["cli:version"]


def _listed() -> dict:
    out = {}
    for line in DIFFERENCES.splitlines():
        if line.strip() and not line.startswith("#"):
            rid, word, got, why = (p.strip() for p in line.split(" | ", 3))
            out[rid] = (word, got, why)
    return out


def test_each_answer_keeps_its_sources_verdict(cases, golden):
    listed, seen, unlisted = _listed(), set(), []
    for case in cases:
        if case.expect is None:
            continue
        got = _verdict(golden[case.id])
        if case.id.startswith("fixture:"):
            ok = got == case.expect
        else:
            ok = cc.ORDER[got] >= cc.ORDER[case.expect]
        if ok:
            continue
        seen.add(case.id)
        if listed.get(case.id, (None, None))[:2] != (case.expect, got):
            unlisted.append(f"{case.id} | {case.expect} | {got}")
    missing = [f"{rid}: listed {w} -> {g} ({why}), did not happen" for rid, (w, g, why) in listed.items()
               if rid not in seen]
    assert unlisted == [] and missing == [], "\n".join(unlisted + missing)
