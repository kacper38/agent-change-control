"""The skill `orchestrate` and its section in AGENTS.md (plan step 1.3)."""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills" / "orchestrate"


def brief_lint():
    spec = importlib.util.spec_from_file_location("brief_lint", ROOT / "tools" / "orchestration" / "brief_lint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agents_md_has_an_orchestration_section_of_at_most_12_lines():
    lines = (ROOT / "AGENTS.md").read_text().splitlines()
    start = lines.index("## Orchestration")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = lines[start:end]
    while section and not section[-1].strip():
        section.pop()
    assert 2 <= len(section) <= 12, section
    assert lines.index("## Model routing (which tier does what)") < start
    text = "\n".join(section)
    for word in ("orchestrate", "brief_lint.py", "assert_run.py", "merge-ready", "gap"):
        assert word in text, word


def test_the_skill_has_its_three_files_and_front_matter():
    for name in ("SKILL.md", "brief-template.md", "brief-example.md"):
        assert (SKILL / name).is_file(), name
    head = (SKILL / "SKILL.md").read_text().split("---")[1]
    assert "name: orchestrate" in head and "description: " in head and "user_invocable: true" in head


def test_the_template_fails_the_linter_and_the_example_passes():
    bl = brief_lint()
    template = bl.lint((SKILL / "brief-template.md").read_text())
    assert len(template) == 11 and all(p.endswith("is empty") for p in template), template
    assert bl.lint((SKILL / "brief-example.md").read_text()) == []


def test_the_template_points_at_the_worker_result_shape():
    assert "worker-result/1" in (SKILL / "brief-template.md").read_text()
