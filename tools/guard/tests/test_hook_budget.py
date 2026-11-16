"""The hook's time budget and a linear segments() (guard 0.7.0, step A2).

Both wirings cut the pre hook at 5 s and a cut hook fails open, so run_hook arms SIGALRM at HOOK_BUDGET_S and
answers with an ask named `budget` when the rules have not finished by then."""

import io
import json
import pathlib
import random
import shlex
import signal
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HAS_TIMER = hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM")

# rows of the approved slow-shapes list (name, prefix, unit, suffix): prefix + unit * (100000 // len(unit)) + suffix
SLOW_SHAPES = [
    (";A=", " ", ";A=", " "),  # the delete text pass backtracks
    ("az x (", " ", "az x (", " "),  # the deploy text pass backtracks
]
SUDO_A = ("sudo -a", " ", "sudo -a ", " ")  # segments() copied the token list once per option


def _shape(prefix, unit, suffix):
    return prefix + unit * (100000 // len(unit)) + suffix


def _raw(command, tmp_path):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path), "session_id": "s1",
            "transcript_path": "/t", "tool_input": {"command": command}}


def _decisions(tmp_path):
    path = tmp_path / "telemetry" / "decisions.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _run_in_process(guard, monkeypatch, capsys, raw, target="pre"):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(raw)))
    code = guard.run_hook(target, "claude")
    return code, capsys.readouterr().out


def _sleeper(ev, cfg):
    """A rule that runs past any budget and, like the real rules, catches Exception."""
    try:
        time.sleep(5)
    except Exception:  # must not swallow the budget's BaseException
        return None
    return None


@pytest.fixture
def own_alarm_handler():
    """Install a recognisable SIGALRM handler, so the test can see that run_hook puts it back."""
    if not HAS_TIMER:
        yield None
        return

    def handler(signum, frame):
        pass

    before = signal.signal(signal.SIGALRM, handler)
    yield handler
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, before)


def test_a_slow_rule_turns_into_a_budget_ask(guard, monkeypatch, capsys, tmp_path, own_alarm_handler):
    if not HAS_TIMER:  # Windows: there is no SIGALRM timer, nothing is armed
        return
    monkeypatch.setattr(guard, "HOOK_BUDGET_S", 0.2)
    monkeypatch.setitem(guard.RULES, "deploy-ask", _sleeper)
    t0 = time.monotonic()
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert time.monotonic() - t0 < 2
    assert code == 0
    got = json.loads(out)
    assert got["permissionDecision"] == "ask"
    reason = got["permissionDecisionReason"]
    assert "could not be judged within" in reason and "7 characters" in reason
    assert "deploy-ask" in reason and "host-install" in reason and "delete-guard" not in reason
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) is own_alarm_handler
    lines = _decisions(tmp_path)
    assert [line["rules"] for line in lines] == [{"budget": "ask"}]


def test_a_deny_before_the_budget_stays_a_deny(guard, monkeypatch, capsys, tmp_path, own_alarm_handler):
    if not HAS_TIMER:  # Windows: there is no SIGALRM timer, nothing is armed
        return
    monkeypatch.setattr(guard, "HOOK_BUDGET_S", 0.2)
    monkeypatch.setitem(guard.RULES, "delete-guard", lambda ev, cfg: ("deny", "fake deny"))
    monkeypatch.setitem(guard.RULES, "git-guard", _sleeper)
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert code == 2
    got = json.loads(out)
    assert got["permissionDecision"] == "deny" and got["permissionDecisionReason"] == "fake deny"
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) is own_alarm_handler
    assert _decisions(tmp_path)[0]["rules"] == {"delete-guard": "deny", "budget": "ask"}


def test_a_fast_hook_leaves_the_timer_off_and_the_handler_back(guard, monkeypatch, capsys, tmp_path,
                                                               own_alarm_handler):
    if not HAS_TIMER:  # Windows: there is no SIGALRM timer, nothing is armed
        return
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert (code, out) == (0, "")
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) is own_alarm_handler


def test_without_a_timer_nothing_is_armed(guard, monkeypatch, capsys, tmp_path):
    """Windows has neither setitimer nor SIGALRM: the hook runs as before 0.7.0."""
    monkeypatch.delattr(guard.signal, "setitimer", raising=False)
    monkeypatch.setitem(guard.RULES, "deploy-ask", lambda ev, cfg: ("ask", "fake ask"))
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert code == 0 and json.loads(out)["permissionDecisionReason"] == "fake ask"


def test_capture_runs_without_the_budget(guard, monkeypatch, capsys, tmp_path):
    def no_arming():
        raise AssertionError("capture armed the budget")

    monkeypatch.setattr(guard, "_arm_budget", no_arming)
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path), target="capture")
    assert (code, out) == (0, "")


def test_no_environment_variable_sets_the_budget(guard):
    source = (ROOT / "tools" / "guard" / "guard.py").read_text(encoding="utf-8")
    assert "HOOK_BUDGET" not in "".join(line for line in source.splitlines() if "environ" in line)
    assert guard.HOOK_BUDGET_S == 3.5


def _hook(guard_path, command, tmp_path):
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, guard_path, "hook", "pre", "--wrapper", "claude"],
                       input=json.dumps(_raw(command, tmp_path)), capture_output=True, text=True, timeout=30,
                       cwd=str(tmp_path))
    return r, time.monotonic() - t0


@pytest.mark.parametrize("name,prefix,unit,suffix", SLOW_SHAPES, ids=[s[0] for s in SLOW_SHAPES])
def test_a_slow_shape_asks_before_the_harness_cuts_the_hook(guard_path, tmp_path, name, prefix, unit, suffix):
    if not HAS_TIMER:  # Windows: there is no SIGALRM timer, the shape still runs past the harness timeout
        return
    r, seconds = _hook(guard_path, _shape(prefix, unit, suffix), tmp_path)
    assert seconds < 4.5, f"{name}: {seconds:.2f} s"
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["permissionDecision"] == "ask"
    assert "could not be judged within" in got["permissionDecisionReason"]
    assert any("budget" in line["rules"] for line in _decisions(tmp_path))


def test_sudo_options_at_100_kb_finish_well_under_the_budget(guard_path, tmp_path):
    """0.6.1: 0.5 s per rule in segments(); measured 2.1 s for the whole hook."""
    r, seconds = _hook(guard_path, _shape(*SUDO_A[1:]), tmp_path)
    assert seconds < 2.0, f"{seconds:.2f} s"
    assert r.returncode == 0, r.stderr
    assert "could not be judged within" not in r.stdout


@pytest.mark.parametrize("wiring", [".claude/settings.json", ".github/hooks/guard.json"])
def test_the_wiring_cuts_the_pre_hook_after_the_budget(guard, wiring):
    data = json.loads((ROOT / wiring).read_text(encoding="utf-8"))
    found = []
    for groups in data["hooks"].values():
        for group in groups:
            for hook in group.get("hooks", [group]):
                command = hook.get("command") or hook.get("bash") or ""
                if "guard.py hook pre" in command:
                    found.append(hook["timeout"])
    assert found and all(t >= 5 > guard.HOOK_BUDGET_S for t in found), (wiring, found)


# ---- segments(): the same output as 0.6.1 ---------------------------------------------------------------

_SEP_RE_061 = r"\|\||&&|[;|]|\n"


def _segments_061(guard, command):
    """segments() as it was at 0.6.1, copied verbatim (do not edit when the function changes)."""
    out = []
    for part in guard.re.split(_SEP_RE_061, command):
        toks = guard.tokens(part)
        while toks and (guard._ASSIGN_RE.match(toks[0]) or toks[0] in guard._WRAPPERS):
            toks = toks[1:]
            while toks and toks[0].startswith("-") and toks[0] != "--":
                toks = toks[1:]
        if toks:
            out.append(toks)
    return out


_WORDS = ["sudo", "env", "command", "exec", "time", "nohup", "doas", "builtin", "A=1", "B_2=x y", "-u", "-a",
          "--", "-", "--x=1", "rm", "-rf", "git", "push", "ls", "'q", "\"q", "a'b", "''", "x=", "=y", "\\", "$(ls)"]
_SEPS = [" ", " ", " ", ";", "|", "||", "&&", "\n", "; ;", " | "]


def _generated(n=400, seed=7):
    rnd = random.Random(seed)
    for _ in range(n):
        parts = [rnd.choice(_WORDS) for _ in range(rnd.randint(0, 14))]
        yield "".join(p + rnd.choice(_SEPS) for p in parts)


@pytest.mark.parametrize("command", ["", " ", ";", "sudo", "sudo -u root rm -rf x", "A=1 B=2 env -i -- ls",
                                     "env A=1 sudo -E -- git push", "ls 'unbalanced", "sudo -a -b", "x; ;y",
                                     "time -p nohup doas -n cmd", "-- rm", "builtin cd ..; exec -a n ls"])
def test_segments_match_061_on_written_cases(guard, command):
    assert guard.segments(command) == _segments_061(guard, command)


def test_segments_match_061_on_generated_lines(guard):
    lines = list(_generated())
    assert len(lines) == 400
    for command in lines:
        assert guard.segments(command) == _segments_061(guard, command), command


def test_segments_hands_out_fresh_lists(guard):
    command = "sudo rm -rf " + shlex.quote("a b")
    first = guard.segments(command)
    first[0].append("changed")
    first.append(["more"])
    assert guard.segments(command) == [["rm", "-rf", "a b"]]


def test_segments_is_linear_in_the_options(guard):
    command = _shape(*SUDO_A[1:])
    t0 = time.monotonic()
    guard._segments_cached.cache_clear()
    assert guard.segments(command) == []
    assert time.monotonic() - t0 < 0.5
