"""The delete text pass on prose (guard 0.7.0, step A1).

The text pass (`DELETE_RE`) is the 0.6.0 one with two exceptions: `del\\s*\\(` needs a word boundary
(`\\bdel\\s*\\(`), so "model (" stops asking, and `truncate` counts as SQL only where a statement can start,
so "may truncate the description" stops asking. Rows copied from the owner-approved case list.
"""

import pathlib

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[2]

# (kind, expected, text): `command` rows are command lines; `script` rows are the content of a script that
# `python3 <file>.py` names
CASES = [
    ("script", "silent", "# Data model (step 2.4)\nprint(\"x\")"),
    ("script", "silent", "result = load_model(path)\nprint(result)"),
    ("script", "silent", "# long items may truncate the description in the export\nprint(\"x\")"),
    ("script", "silent", "\"\"\"Notes: the export will truncate the title when it is too long.\"\"\""),
    ("script", "ask", "cache = {}\ndel (cache)"),
    ("script", "ask", "cache = {}\ndel(cache)"),
    ("script", "ask", "client.del(key)"),
    ("script", "ask", "import os\nos.remove(\"x\")"),
    ("script", "ask", "QUERY = \"truncate users\""),
    ("script", "ask", "cur.execute(\"TRUNCATE TABLE audit\")"),
    ("script", "ask", "BEGIN; truncate users;"),
    ("script", "ask", "truncate users;"),
    ("command", "silent", "echo \"this may truncate the output\""),
    ("command", "silent", "grep -n \"Data model (\" tools/tracker/tracker.py"),
    ("command", "silent", "python3 -c \"print(model (1))\""),
    ("command", "ask", "psql -c \"truncate users\""),
    ("command", "ask", "psql -c 'TRUNCATE TABLE x'"),
    ("command", "ask", "truncate -s 0 app.log"),
    ("command", "ask", "python3 -c \"del (x)\""),
    ("command", "ask", "node -e \"client.del('k')\""),
]


def _ev(guard, command, cwd):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
                        "tool_input": {"command": command}})


@pytest.mark.parametrize("kind,expected,text", CASES, ids=[f"{c[0]}-{c[1]}-{i}" for i, c in enumerate(CASES)])
def test_case(guard, tmp_path, kind, expected, text):
    if kind == "script":
        (tmp_path / "step.py").write_text(text + "\n", encoding="utf-8")
        command = "python3 step.py"
    else:
        command = text
    got = guard.rule_delete_guard(_ev(guard, command, tmp_path), {})
    if expected == "silent":
        assert got is None, f"{kind} {text!r}: {got}"
    else:
        assert got is not None and got[0] == "ask", f"{kind} {text!r}: {got}"


@pytest.mark.parametrize("text", ["model (", "load_model(x)", "handel(", "may truncate the description",
                                  "echo \"this may truncate the output\""])
def test_prose_does_not_match_the_text_pass(guard, text):
    assert not guard.DELETE_RE.search(text), text


@pytest.mark.parametrize("text", ["del (x)", "del(x)", "client.del(key)", "psql -c \"truncate users\"",
                                  "psql -c 'TRUNCATE TABLE x'", "truncate users;", "BEGIN; truncate x",
                                  "cur.execute(\"truncate users\")", "x = 1\ntruncate users;"])
def test_code_and_sql_still_match_the_text_pass(guard, text):
    assert guard.DELETE_RE.search(text), text


@pytest.mark.parametrize("rel", ["tracker/tracker.py", "tracker/evidence_export.py"])
def test_the_tracker_sources_no_longer_match(guard, rel):
    """37 of a week's 117 asks came from one comment in tracker.py; evidence_export.py tripped on prose too."""
    text = (TOOLS / rel).read_text(encoding="utf-8")
    m = guard.DELETE_RE.search(text)
    assert m is None, f"{rel}: {m.group(0)!r}"
