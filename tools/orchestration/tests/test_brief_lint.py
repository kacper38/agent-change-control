"""brief_lint.py (plan step 1.3): a brief names every field once, none empty, the done evidence as a command."""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
FIELDS = ["Goal", "Decisions not to reopen", "Scope", "Writable paths", "Forbidden paths", "Forbidden actions",
          "What to ignore", "Done evidence", "Output format", "Report fields", "Size limit"]


@pytest.fixture(scope="module")
def bl():
    spec = importlib.util.spec_from_file_location("brief_lint", HERE.parent / "brief_lint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def brief(**bodies):
    parts = ["# Brief: example packet\n"]
    for f in FIELDS:
        body = bodies.get(f, "`pytest -q` exits 0" if f == "Done evidence" else "At most 3 files." if f == "Size limit"
                          else f"Text for {f}.")
        if body is not None:
            parts.append(f"## {f}\n\n{body}\n")
    return "\n".join(parts)


def lint(bl, tmp_path, text):
    p = tmp_path / "brief.md"
    p.write_text(text)
    return bl.lint(text), p


def test_a_full_brief_passes(bl, tmp_path, capsys):
    problems, p = lint(bl, tmp_path, brief() + "\n### a sub-heading\n\n## Notes\n\nfree text\n")
    assert problems == []
    assert bl.main([str(p)]) == 0
    assert capsys.readouterr().out == f"brief_lint: {p}: ok\n"


@pytest.mark.parametrize("body", ["", "   \n\n", "<!-- what goes here -->", "<!-- a\nmulti-line comment -->\n"])
def test_an_empty_field_fails(bl, tmp_path, body, capsys):
    problems, p = lint(bl, tmp_path, brief(Scope=body))
    assert problems == ['field "Scope" is empty']
    assert bl.main([str(p)]) == 1
    assert capsys.readouterr().out == f'brief_lint: {p}: field "Scope" is empty\n'


def test_missing_and_doubled_fields_fail(bl, tmp_path):
    problems, _ = lint(bl, tmp_path, brief(Goal=None) + "\n## Scope\n\nagain\n")
    assert len(problems) == 2 and any("Goal" in p for p in problems) and any("Scope" in p for p in problems)


def test_done_evidence_needs_a_command(bl, tmp_path):
    problems, _ = lint(bl, tmp_path, brief(**{"Done evidence": "the tests pass"}))
    assert len(problems) == 1 and "Done evidence" in problems[0]
    assert lint(bl, tmp_path, brief(**{"Done evidence": "```\npytest -q\n```\nexits 0"}))[0] == []
    assert len(lint(bl, tmp_path, brief(**{"Done evidence": "<!-- `pytest` -->the tests pass"}))[0]) == 1


def test_size_limit_needs_a_number(bl, tmp_path):
    problems, _ = lint(bl, tmp_path, brief(**{"Size limit": "small"}))
    assert len(problems) == 1 and "Size limit" in problems[0]


def test_unreadable_file_and_usage(bl, tmp_path, capsys):
    assert bl.main([str(tmp_path / "none.md")]) == 1
    assert "none.md" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        bl.main([])
    assert exc.value.code == 2
