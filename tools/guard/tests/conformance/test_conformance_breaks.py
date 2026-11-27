"""Planted breaks (tracker item #116): each is one replacement in a copy of guard.py at the same depth
(<tmp>/tools/guard/guard.py), and the run on the cases that can see it must fail and name the cases it caught. The
unpatched copy at that place passes every case: the control, and proof that the answers do not depend on where the
guard file lies (the copy and its run are conftest.py's)."""
import pathlib
import re
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import conformance_runner as cr  # noqa: E402 (the folder is no package)

LOG_WRITE = '            fh.write(json.dumps(entry, sort_keys=True) + "\\n")\n    except OSError as exc:\n' \
            '        print(f"guard: decision log failed'

# what is changed | the text, which must stand exactly once | its replacement | the cases run | how many differ
BREAKS = [
    ("a rule stays silent", '    "secret-write": rule_secret_write,', '    "secret-write": lambda ev, cfg: None,',
     ["fixture:secret-write/"], 22),
    ("an ask turned into a deny", '    verdict = "deny" if top == 2 else "ask"', '    verdict = "deny"',
     ["fixture:delete-guard/claude/"], 77),
    ("a changed reason text", '"Ask the owner explicitly."', '"Ask the owner."', ["fixture:delete-guard/"], 154),
    ("a wrong exit code on deny", "        return 2\n", "        return 1\n", ["fixture:git-guard/"], 42),
    ("a crash swallowed into exit 0", 'print(f"guard: error: {exc}", file=sys.stderr)\n            return 1',
     'print(f"guard: error: {exc}", file=sys.stderr)\n            return 0', ["crash:", "cli:unknown-rule"], 4),
    ("a field dropped from the decision log", '        "guard": VERSION,\n', "", ["knob:cloud"], 5),
    ("a lost stderr line on deny", '        sys.stderr.write(reason + "\\n")', "        pass",
     ["fixture:git-guard/"], 42),
    ("a changed spacing in the JSON answer", "sys.stdout.write(json.dumps(payload) + ",
     'sys.stdout.write(json.dumps(payload, separators=(",", ":")) + ', ["fixture:egress-guard/claude/"], 20),
    ("a changed key order in the JSON answer", "sys.stdout.write(json.dumps(payload) + ",
     "sys.stdout.write(json.dumps(payload, sort_keys=True) + ", ["fixture:egress-guard/claude/"], 20),
    ("a rule left out of hook pre", "PRE_RULES = list(RULES)",
     'PRE_RULES = [n for n in RULES if n != "secret-read"]', ["test_bypass_forms.FILES:"], 39),
    ("a skipped line no longer written", "    if skipped:", "    if False:", ["knob:"], 7),
    ("a changed key order in the decision log", LOG_WRITE, LOG_WRITE.replace("sort_keys=True", "sort_keys=False"),
     ["knob:boundary-"], 6),
    ("the fan-out threshold moved", "FANOUT_FIRST, FANOUT_EVERY = 6, 10", "FANOUT_FIRST, FANOUT_EVERY = 7, 10",
     ["cli:fan-out"], 3),
    ("no `ran` line after an asked call", '        log_decision(("ran", ""), rules, ev, cfg, facts)', "        pass",
     ["cli:post"], 2),
    ("a Copilot event judged through the claude wrapper", '    if wrapper == "claude" and ev.harness == "copilot":',
     "    if False:", ["cli:copilot"], 1),
    ("a changed indent of a capture file", "json.dump(redact(raw), fh, indent=2, sort_keys=True)",
     "json.dump(redact(raw), fh, indent=1, sort_keys=True)", ["cli:capture"], 2),
]


def _run(capsys, guard: str, root: pathlib.Path, only: list) -> tuple:
    args = ["run", "--guard", guard, "--root", str(root)]
    code = cr.main(args + [a for p in only for a in ("--only", p)])
    return code, capsys.readouterr().out


@pytest.mark.parametrize("what, old, new, only, caught", BREAKS, ids=[b[0] for b in BREAKS])
def test_a_planted_break_is_caught(guard_copy, tmp_path, capsys, what, old, new, only, caught):
    code, out = _run(capsys, guard_copy(tmp_path / "copy", old, new), tmp_path / "root", only)
    total, differ = map(int, re.search(r"(\d+) cases, (\d+) differ", out).groups())
    named = re.findall(r"^  (\S+:\S*)$", out, re.MULTILINE)
    assert code == 1 and named and all(n.startswith(tuple(only)) for n in named), out
    assert differ == caught, f"{what}: {differ} of {total} cases caught it, the table says {caught}"


def test_the_unpatched_copy_passes_every_case(golden, control):
    diff = cr.differing(golden, control)
    assert diff == [], cr.describe(diff[0], golden.get(diff[0]), control.get(diff[0]))
