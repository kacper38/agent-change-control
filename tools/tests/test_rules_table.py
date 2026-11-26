"""Rules table (Phase 1 plan step 1.6, tracker item #70): `docs/RULES.md` has a row for every rule of `AGENTS.md`
that names its enforcer or says judgment, every named enforcer exists, and no relaxation is in force past its end."""
import ast
import datetime
import json
import pathlib
import re
import shlex

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
LATEST_END = datetime.date(2026, 12, 31)  # Phase 1 plan, section 5: each relaxation ends at delivery, by this date
# id prefix -> the `AGENTS.md` section whose items are rules; `## Harness notes` says which harness reads which file
SECTIONS = {"NN": "Non-negotiables", "CP": "Coding principles", "WF": "Working files",
            "ST": "Default stack choices", "MR": "Model routing", "OR": "Orchestration"}
EXTRA_RULE_IDS = {"MR-5", "MR-6"}  # the paragraph under the model table, which `items` does not count
D12_IDS = {"D12-1", "D12-2", "D12-3", "D12-4", "D12-5"}  # plan rev 3, D12: the controls `docs/RULES.md` lists
RELAXATION_IDS = {"P5-1", "P5-2", "P5-3", "P5-4", "P5-5", "P5-6", "L-fleet", "L-rules-off", "S-1", "S-2"}
TESTPATHS = re.findall(r'"([^"]+)"', re.search(r"testpaths\s*=\s*\[(.*?)\]",
                                               (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1))
PROJECT_DIR = "${CLAUDE_PROJECT_DIR:-.}/"  # how a hook command of `.claude/settings.json` starts a repository path
ENFORCER_RE = re.compile(r"`([a-z]+):([^`]+)`")
JUDGMENT = "judgment"


def norm(text: str) -> str:
    return " ".join(text.replace("**", "").split())


def sections(md: str) -> dict:
    """`## Heading` -> the text below it, up to the next `## `."""
    out, name = {}, None
    for line in md.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = []
        elif name is not None:
            out[name].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def section(md: str, prefix: str) -> str:
    found = [text for name, text in sections(md).items() if name.startswith(prefix)]
    assert len(found) == 1, f"one section starting with {prefix!r} expected, found {len(found)}"
    return found[0]


def items(text: str, prefix: str) -> dict:
    """A section's rules by id: each top-level `1.` or `-` item (its nested `-` items instead, when it has some) and
    each body row of a table; continuation lines join the item above."""
    out, top, sub, current, header = {}, 0, 0, None, False
    for line in text.splitlines():
        if line.startswith("|"):
            current = None
            if not header:
                header = True  # a table's first row names its columns
            elif not re.match(r"\|\s*-", line):
                top, sub = top + 1, 0
                out[f"{prefix}-{top}"] = line
        elif re.match(r"(\d+\.|-) ", line):
            top, sub = top + 1, 0
            current = f"{prefix}-{top}"
            out[current] = line
        elif re.match(r"\s+- ", line) and top:
            out.pop(f"{prefix}-{top}", None)  # an item with nested items is their heading, not a rule
            sub += 1
            current = f"{prefix}-{top}.{sub}"
            out[current] = line
        elif line.startswith(" ") and line.strip() and current:
            out[current] += " " + line
        else:
            current = None
    return {k: norm(v) for k, v in out.items()}


def table(md: str, prefix: str) -> list:
    """Body rows of the first table in the section, as lists of stripped cells."""
    rows = [line for line in section(md, prefix).splitlines() if line.startswith("|")]
    return [[c.strip() for c in row.strip().strip("|").split("|")] for row in rows[2:]]


def guard_rules(root: pathlib.Path) -> set:
    tree = ast.parse((root / "tools/guard/guard.py").read_text(encoding="utf-8"))
    for node in tree.body:
        targets = getattr(node, "targets", None) or [getattr(node, "target", None)]  # `RULES: dict = {...}` too
        if isinstance(getattr(node, "value", None), ast.Dict) and any(
                isinstance(t, ast.Name) and t.id == "RULES" for t in targets):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


def ci_jobs(root: pathlib.Path) -> set:
    """Jobs of the workflows that a pull request starts (`pull_request` under `on:`)."""
    jobs = set()
    for wf in sorted((root / ".github/workflows").glob("*.yml")):
        block, keys = None, {"on": set(), "jobs": set()}
        for line in wf.read_text(encoding="utf-8").splitlines():
            top = re.match(r"([A-Za-z]+):", line)
            if top:
                block = top.group(1) if top.group(1) in keys else None
            elif block:
                m = re.match(r"  ([A-Za-z0-9_-]+):", line)
                if m:
                    keys[block].add(m.group(1))
        if "pull_request" in keys["on"]:
            jobs |= keys["jobs"]
    return jobs


def hook_commands(root: pathlib.Path) -> list:
    hooks = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8")).get("hooks", {})
    return [h.get("command", "") for groups in hooks.values() for g in groups for h in g.get("hooks", [])]


def enforcer_problem(kind: str, ref: str, root: pathlib.Path) -> str:
    """'' when the enforcer exists, else what is wrong."""
    if kind == "guard":
        return "" if ref in guard_rules(root) else f"`guard:{ref}` is no key of RULES in tools/guard/guard.py"
    if kind == "ci":
        ok = ref in ci_jobs(root)
        return "" if ok else f"`ci:{ref}` is no job of a workflow in .github/workflows/ that a pull request starts"
    if kind == "hook":
        words = {w[len(PROJECT_DIR):] if w.startswith(PROJECT_DIR) else w
                 for c in hook_commands(root) for w in shlex.split(c)}  # the script's path is one word of a command
        ok = (root / ref).is_file() and ref in words
        return "" if ok else f"`hook:{ref}` is no file that a hook of .claude/settings.json runs"
    if kind == "test":
        path, _, name = ref.partition("::")
        file = root / path
        collected = re.fullmatch(r"test_.*\.py|.*_test\.py", file.name)  # pytest's default `python_files`
        if not file.is_file() or not collected or not any(path.startswith(p.rstrip("/") + "/") for p in TESTPATHS):
            return f"`test:{ref}`: {path} is no test file (test_*.py, *_test.py) under pytest's testpaths {TESTPATHS}"
        body = ast.parse(file.read_text(encoding="utf-8")).body
        tests = [n for n in body if isinstance(n, ast.FunctionDef)]  # module level, or a method of a class pytest
        for c in body:                                                 # collects: `Test*` and no `__init__`
            if isinstance(c, ast.ClassDef) and c.name.startswith("Test"):
                methods = [m for m in c.body if isinstance(m, ast.FunctionDef)]
                tests += [] if any(m.name == "__init__" for m in methods) else methods
        ok = name.startswith("test_") and any(n.name == name for n in tests)
        return "" if ok else f"`test:{ref}`: no test function {name!r} that pytest collects in {path}"
    return f"`{kind}:{ref}`: unknown enforcer kind (guard, ci, hook, test)"


def enforcer_problems(rid: str, cell: str, root: pathlib.Path, judgment_only: bool = False) -> list:
    found = ENFORCER_RE.findall(cell)
    rest = ENFORCER_RE.sub("", cell).replace(JUDGMENT, "").replace(",", "").strip()
    if rest or not (found or JUDGMENT in cell):
        return [f"{rid}: the enforcer cell must hold `kind:ref` entries and/or the word judgment, got {cell!r}"]
    if judgment_only and found:
        return [f"{rid}: a judgment control of D12 names an enforcer ({cell!r})"]
    return [f"{rid}: {p}" for p in (enforcer_problem(k, r, root) for k, r in found) if p]


def rule_problems(rules_md: str, agents_md: str, plan_md: str, root: pathlib.Path) -> list:
    problems, rows = [], {}
    for row in table(rules_md, "Rules"):
        if len(row) != 4:
            problems.append(f"rules table: a row needs 4 cells, got {row}")
            continue
        rid, quote, cell, _note = row
        if rid in rows:
            problems.append(f"{rid}: two rows")
        rows[rid] = (quote, cell)
    for prefix, name in SECTIONS.items():
        text = section(agents_md, name)
        expected = items(text, prefix)
        if not expected:
            problems.append(f"`AGENTS.md` ## {name}: no rule found; the reader no longer fits the file")
        problems += [f"{rid}: `AGENTS.md` ## {name} has this rule and the table no row"
                     for rid in expected if rid not in rows]
        for rid, (quote, cell) in rows.items():
            if not rid.startswith(prefix + "-"):
                continue
            if rid not in expected and rid not in EXTRA_RULE_IDS:
                problems.append(f"{rid}: `AGENTS.md` ## {name} has no such item")
                continue
            where = expected.get(rid, norm(text))
            if not quote or norm(quote) not in where:
                problems.append(f"{rid}: the quote {quote!r} is not in {'that item' if rid in expected else name}")
            problems += enforcer_problems(rid, cell, root)
    problems += [f"{rid}: id prefix names no section of AGENTS.md" for rid in rows if rid.split("-")[0] not in SECTIONS]
    problems += [f"{rid}: no row for this rule of the paragraph under the model table"
                 for rid in sorted(EXTRA_RULE_IDS - set(rows))]
    if "**D12 —" not in plan_md:
        return problems + ["plan rev 3 has no block `**D12 —`"]
    d12 = norm(plan_md.split("**D12 —", 1)[1].split("**D13 —", 1)[0])
    seen = set()
    for row in table(rules_md, "Judgment controls"):
        rid, quote, cell = (row + ["", "", ""])[:3]
        if rid in seen:
            problems.append(f"{rid}: two rows")
        seen.add(rid)
        if not quote or norm(quote) not in d12:
            problems.append(f"{rid}: the quote {quote!r} is not in plan rev 3, D12")
        problems += enforcer_problems(rid, cell, root, judgment_only=True)
    problems += [f"{rid}: no row for this judgment control of D12" for rid in sorted(D12_IDS - seen)]
    return problems


def relaxation_problems(rules_md: str, today: datetime.date) -> list:
    problems, seen = [], set()
    for row in table(rules_md, "Relaxations"):
        if len(row) != 5:
            problems.append(f"relaxations table: a row needs 5 cells, got {row}")
            continue
        rid, _what, _source, ends, state = row
        if rid in seen:
            problems.append(f"{rid}: two rows")
        seen.add(rid)
        try:
            end = datetime.date.fromisoformat(ends)
        except ValueError:
            problems.append(f"{rid}: end {ends!r} is no date (YYYY-MM-DD)")
            continue
        if end > LATEST_END:
            problems.append(f"{rid}: ends {end}, after {LATEST_END}, the latest end the Phase 1 plan allows")
        if state == "in force":
            if end < today:
                problems.append(f"{rid}: in force past its end ({end}); end it, or the owner gives it a new end")
        elif state != f"ended {ends}" or end > today:
            problems.append(f"{rid}: state must be `in force`, or `ended {ends}` (its end, not after today), "
                            f"got {state!r}")
    problems += [f"{rid}: no row for this relaxation" for rid in sorted(RELAXATION_IDS - seen)]
    return problems


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def real_rule_problems(rules_md: str = "", agents_md: str = "") -> list:
    return rule_problems(rules_md or read("docs/RULES.md"), agents_md or read("AGENTS.md"),
                         read("docs/PLAN-2026-11-orchestration-ci.md"), ROOT)


def test_every_rule_has_a_row_and_every_enforcer_exists():
    assert real_rule_problems() == []


def test_no_relaxation_is_in_force_past_its_end():
    assert relaxation_problems(read("docs/RULES.md"), datetime.date.today()) == []


def test_every_non_negotiable_is_counted():
    found = items(section(read("AGENTS.md"), "Non-negotiables"), "NN")
    assert {"NN-1", "NN-5", "NN-6.1", "NN-6.9", "NN-8"} <= set(found) and "NN-6" not in found


@pytest.mark.parametrize("token", ["`guard:no-such-rule`", "`ci:no-such-job`", "`ci:lint`", "`hook:tools/no_such.py`",
                                   "`hook:py`", "`hook:tools/scan`",
                                   "`test:tools/tests/test_agents.py::test_no_such_test`",
                                   "`test:tools/no/such_test.py::test_x`", "`lint:ruff`", "nothing"])
def test_a_missing_enforcer_fails(token):
    md = read("docs/RULES.md")
    row = next(line for line in md.splitlines() if line.startswith("| NN-6.9 |"))
    cells = row.split("|")
    cells[3] = f" {token} "
    problems = real_rule_problems(rules_md=md.replace(row, "|".join(cells)))
    assert len(problems) == 1 and problems[0].startswith("NN-6.9: "), problems


def test_a_new_rule_without_a_row_fails():
    agents = read("AGENTS.md").replace("8. **Wrong path", "9. **A new rule.** Text.\n8. **Wrong path", 1)
    assert any(p.startswith("NN-9: ") for p in real_rule_problems(agents_md=agents))


def test_a_quote_that_left_agents_md_fails():
    agents = read("AGENTS.md").replace("**Plan first.**", "**Plan early.**", 1)
    assert any(p.startswith("NN-1: the quote") for p in real_rule_problems(agents_md=agents))


def test_a_d12_control_with_an_enforcer_fails():
    md = read("docs/RULES.md")
    row = next(line for line in md.splitlines() if line.startswith("| D12-1 |"))
    problems = real_rule_problems(rules_md=md.replace(row, row.replace("| judgment |", "| `guard:cloud-launch` |", 1)))
    assert any(p.startswith("D12-1: a judgment control") for p in problems), problems


def test_a_relaxation_past_its_end_fails():
    problems = relaxation_problems(read("docs/RULES.md"), LATEST_END + datetime.timedelta(days=1))
    in_force = [r[0] for r in table(read("docs/RULES.md"), "Relaxations") if r[4] == "in force"]
    assert in_force and sorted(p.split(":")[0] for p in problems) == sorted(in_force)


def test_an_end_after_delivery_fails():
    md = read("docs/RULES.md").replace("| 2026-12-31 | in force |", "| 2027-01-15 | in force |", 1)
    assert any("after 2026-12-31" in p for p in relaxation_problems(md, datetime.date(2026, 11, 23)))


def all_problems(md: str, today: datetime.date = datetime.date(2026, 11, 23)) -> list:
    return real_rule_problems(rules_md=md) + relaxation_problems(md, today)


def row_of(md: str, rid: str) -> str:
    return next(line for line in md.splitlines() if line.startswith(f"| {rid} |"))


@pytest.mark.parametrize("rid", ["NN-7", "MR-5", "MR-6", "D12-5", "S-1", "S-2", "P5-1", "L-fleet"])
def test_a_missing_row_fails(rid):
    md = read("docs/RULES.md")
    problems = all_problems(md.replace(row_of(md, rid) + "\n", "", 1))
    assert [p for p in problems if p.startswith(f"{rid}: ")] and all(p.startswith(f"{rid}: ") for p in problems)


@pytest.mark.parametrize("after, extra, why", [
    ("NN-8", "| NN-6.10 | x | judgment | |", "NN-6.10: `AGENTS.md` ## Non-negotiables has no such item"),
    ("NN-8", "| NN-1 | Plan first. | judgment | |", "NN-1: two rows"),
    ("NN-8", "| XX-1 | x | judgment | |", "XX-1: id prefix names no section"),
    ("D12-5", "| D12-5 | its `allow_remote_sessions` policy is off | judgment | |", "D12-5: two rows"),
    ("S-1", "| P5-2 | x | y | 2026-12-31 | in force |", "P5-2: two rows"),
])
def test_a_stray_or_doubled_row_fails(after, extra, why):
    md = read("docs/RULES.md")
    problems = all_problems(md.replace(row_of(md, after), row_of(md, after) + "\n" + extra, 1))
    assert len(problems) == 1 and problems[0].startswith(why), problems


@pytest.mark.parametrize("rid, old, new, today", [
    ("P5-2", "| in force |", "| paused |", datetime.date(2026, 11, 23)),
    ("P5-1", "| ended 2026-11-21 |", "| ended 2026-11-20 |", datetime.date(2026, 11, 23)),  # not its end
    ("P5-1", "| ended 2026-11-21 |", "| ended 2026-11-21 |", datetime.date(2026, 11, 20)),  # ended in the future
    ("P5-2", "| 2026-12-31 |", "| 31.12.2026 |", datetime.date(2026, 11, 23)),
])
def test_a_bad_state_or_end_fails(rid, old, new, today):
    md = read("docs/RULES.md")
    row = row_of(md, rid)
    problems = relaxation_problems(md.replace(row, row.replace(old, new, 1), 1), today)
    assert len(problems) == 1 and problems[0].startswith(f"{rid}: "), problems


def test_an_enforcer_counts_only_where_it_runs(tmp_path):
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/push.yml").write_text("on:\n  push:\njobs:\n  build:\n    runs-on: x\n")
    (tmp_path / ".claude").mkdir()
    command = 'python3 "${CLAUDE_PROJECT_DIR:-.}"/tools/x.py hook'
    (tmp_path / ".claude/settings.json").write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": command}]}]}}))
    (tmp_path / "tools/tests").mkdir(parents=True)
    (tmp_path / "tools/x.py").write_text("")
    (tmp_path / "x.py").write_text("")  # exists, but the hook runs tools/x.py
    (tmp_path / "tools/tests/test_x.py").write_text(
        "def test_ok():\n    def test_inner():\n        pass\n\nclass TestC:\n    def test_m(self):\n        pass\n\n"
        "class Helper:\n    def test_h(self):\n        pass\n\n"
        "class TestI:\n    def __init__(self):\n        pass\n\n    def test_i(self):\n        pass\n")
    (tmp_path / "tools/tests/helpers.py").write_text("def test_y():\n    pass\n")
    assert enforcer_problem("ci", "build", tmp_path)  # no pull_request trigger
    (tmp_path / ".github/workflows/pr.yml").write_text("on:\n  pull_request:\njobs:\n  build:\n    runs-on: x\n")
    assert enforcer_problem("ci", "build", tmp_path) == ""
    assert enforcer_problem("hook", "tools/x.py", tmp_path) == ""
    assert enforcer_problem("hook", "x.py", tmp_path) and enforcer_problem("hook", "tools", tmp_path)
    assert enforcer_problem("test", "tools/tests/test_x.py::test_ok", tmp_path) == ""
    assert enforcer_problem("test", "tools/tests/test_x.py::test_m", tmp_path) == ""
    for name in ("test_inner", "test_h", "test_i"):  # nested; a class pytest skips; a class with __init__
        assert "pytest collects" in enforcer_problem("test", f"tools/tests/test_x.py::{name}", tmp_path), name
    assert "no test file" in enforcer_problem("test", "tools/tests/helpers.py::test_y", tmp_path)
