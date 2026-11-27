"""The conformance run of the guard (tracker item #116): the golden file is what the Python guard answers now, from
any case root; two false programs fail it; and each answer keeps the verdict its source names. The golden file is
recorded through `python3 tools/guard/guard.py` in place from one root and compared with `control` (conftest.py),
an unpatched copy at <tmp>/tools/guard/guard.py started through a launcher from another root: one equality shows that
the file is what the guard answers now and that neither the case root, nor the guard's place, nor the way it is
started changes an answer. When the guard or its corpus changes, recording
the file again is the only act needed: the numbers below are floors or derived from the file."""
import ast
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
FLOORS = {"fixture": 1573, "shape": 28, "crash": 3, "table": 3234, "cli": 22, "knob": 42}  # the counts of 0.12.2
RECORD = 'python3 tools/guard/tests/conformance/conformance_runner.py record --guard "python3 tools/guard/guard.py"'

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


def test_counts(cases, golden):
    kinds: dict = {}
    for case in cases:
        kinds[_kind(case.id)] = kinds.get(_kind(case.id), 0) + 1
    assert set(kinds) == set(FLOORS) and all(kinds[k] >= FLOORS[k] for k in FLOORS), kinds
    assert len(cc.table_rows()) == kinds["table"]
    assert list(golden) == sorted(c.id for c in cases), f"the cases changed: record the golden file again: {RECORD}"


def test_the_golden_files_name_holds_its_version(golden):
    version = golden["cli:version"]["calls"][0]["stdout"].strip()
    assert cr.GOLDEN.name == f"guard-{version}.jsonl", f"the file holds the answers of {version}: rename it and GOLDEN"


def test_the_guards_main_block_is_what_the_launcher_repeats():
    """The launcher of conftest.py is guard.py's own start only while the file ends with this block and has no other."""
    tree = ast.parse((HERE.parent.parent / "guard.py").read_text(encoding="utf-8"))
    want = ast.dump(ast.parse('if __name__ == "__main__":\n    sys.exit(main(sys.argv[1:]))\n').body[0])
    mains = [n for n in tree.body if isinstance(n, ast.If) and "__name__" in ast.dump(n.test)]
    assert ast.dump(tree.body[-1]) == want and len(mains) == 1, "change the launcher in conftest.py with it"


def test_golden_is_sorted_complete_and_small(cases, golden):
    text = cr.GOLDEN.read_text(encoding="utf-8")
    assert text == cr.golden_text(golden), f"one sorted JSON line per case: write it with `record` only: {RECORD}"
    assert len(text.encode("utf-8")) <= 6_000_000


def test_golden_is_what_the_guard_answers_now_from_any_root_and_place(golden, control):
    diff = cr.differing(golden, control)
    assert diff == [], (f"{len(diff)} cases differ; if the guard changed on purpose, record the golden file again: "
                        f"{RECORD}\n" + cr.describe(diff[0], golden.get(diff[0]), control.get(diff[0])))


def test_two_false_programs_fail_the_run(cases, golden, tmp_path):
    silent = _program(tmp_path, "silent", "exit 0\n")
    deny = _program(tmp_path, "deny", "printf '%s\\n' '{\"permissionDecision\": \"deny\", "
                                      "\"permissionDecisionReason\": \"no\"}'\necho no >&2\nexit 2\n")
    spoke = {k for k, a in golden.items() if a["files"] or any(c["exit"] != 0 or c["stdout"] or c["stderr"]
                                                               for c in a["calls"])}
    for argv, fails in ((silent, spoke), (deny, set(golden))):
        got = cr.run_cases(cases, argv, tmp_path / "root", JOBS)
        assert set(cr.differing(golden, got)) == fails, argv


def test_the_command_line_exit_codes(tmp_path, capsys):
    root = ["--root", str(tmp_path), "--only", "cli:version", "--only", "crash:"]
    assert cr.main(["run", "--guard", " ".join(GUARD), *root]) == 0
    assert " cases, 0 differ" in capsys.readouterr().out
    assert cr.main(["run", "--guard", " ".join(_program(tmp_path, "silent", "")), *root]) == 1
    assert "\n  cli:version\n" in capsys.readouterr().out
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
