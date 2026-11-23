"""Rules table (Phase 1 plan step 1.6, tracker item #70): `docs/RULES.md` has a row for every rule of `AGENTS.md`
that names its enforcer or says judgment, every named enforcer exists, and no relaxation is in force past its end."""
import ast
import datetime
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
LATEST_END = datetime.date(2026, 12, 31)  # Phase 1 plan, section 5: each relaxation ends at delivery, by this date
# id prefix -> the `AGENTS.md` section whose items are rules; `## Harness notes` says which harness reads which file
SECTIONS = {"NN": "Non-negotiables", "CP": "Coding principles", "WF": "Working files",
            "ST": "Default stack choices", "MR": "Model routing", "OR": "Orchestration"}
D12_IDS = {"D12-1", "D12-2", "D12-3"}  # plan rev 3, row 1.6: who starts a cloud session, `/web-setup`, the App
RELAXATION_IDS = {"P5-1", "P5-2", "P5-3", "P5-4", "P5-5", "P5-6", "L-fleet", "L-rules-off"}
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
    jobs = set()
    for wf in sorted((root / ".github/workflows").glob("*.yml")):
        inside = False
        for line in wf.read_text(encoding="utf-8").splitlines():
            if re.match(r"jobs:\s*$", line):
                inside = True
            elif inside and re.match(r"\S", line):
                inside = False
            elif inside:
                m = re.match(r"  ([A-Za-z0-9_-]+):\s*$", line)
                if m:
                    jobs.add(m.group(1))
    return jobs


def hook_commands(root: pathlib.Path) -> list:
    hooks = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8")).get("hooks", {})
    return [h.get("command", "") for groups in hooks.values() for g in groups for h in g.get("hooks", [])]


def enforcer_problem(kind: str, ref: str, root: pathlib.Path) -> str:
    """'' when the enforcer exists, else what is wrong."""
    if kind == "guard":
        return "" if ref in guard_rules(root) else f"`guard:{ref}` is no key of RULES in tools/guard/guard.py"
    if kind == "ci":
        return "" if ref in ci_jobs(root) else f"`ci:{ref}` is no job in .github/workflows/*.yml"
    if kind == "hook":
        ok = any(ref in c for c in hook_commands(root))
        return "" if ok else f"`hook:{ref}` is run by no hook of .claude/settings.json"
    if kind == "test":
        path, _, name = ref.partition("::")
        file = root / path
        if not file.is_file():
            return f"`test:{ref}`: {path} does not exist"
        tree = ast.parse(file.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        ok = name.startswith("test_") and name in names
        return "" if ok else f"`test:{ref}`: no test function {name!r} in {path}"
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
            where = expected.get(rid, norm(text))
            if not quote or norm(quote) not in where:
                problems.append(f"{rid}: the quote {quote!r} is not in {'that item' if rid in expected else name}")
            problems += enforcer_problems(rid, cell, root)
    problems += [f"{rid}: id prefix names no section of AGENTS.md" for rid in rows if rid.split("-")[0] not in SECTIONS]
    if "**D12 —" not in plan_md:
        return problems + ["plan rev 3 has no block `**D12 —`"]
    d12 = norm(plan_md.split("**D12 —", 1)[1].split("**D13 —", 1)[0])
    seen = set()
    for row in table(rules_md, "Judgment controls"):
        rid, quote, cell = (row + ["", "", ""])[:3]
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
        elif not re.fullmatch(r"ended \d{4}-\d{2}-\d{2}", state):
            problems.append(f"{rid}: state must be `in force` or `ended YYYY-MM-DD`, got {state!r}")
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


@pytest.mark.parametrize("token", ["`guard:no-such-rule`", "`ci:no-such-job`", "`hook:tools/no_such.py`",
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
