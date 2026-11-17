"""The hook's time budget and a linear segments() (guard 0.7.0, step A2 and its fix).

Both wirings cut the pre hook at 5 s and a cut hook fails open, so the rules run in a forked child and the hook
answers with an ask named `budget` when they have not finished within HOOK_BUDGET_S. A timer was not enough:
before Python 3.11 no signal handler runs inside one `re` search (a 1 MB `rsync a ` line answered after 26 s)."""

import io
import json
import os
import pathlib
import random
import re
import shlex
import signal
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HAS_FORK = hasattr(os, "fork")

# rows of the approved slow-shapes list (name, prefix, unit, suffix, size): prefix + unit * (size // len(unit)) + suffix
SLOW_SHAPES = [
    (";A=", " ", ";A=", " ", 100000),  # the delete text pass backtracks
    ("az x (", " ", "az x (", " ", 100000),  # the deploy text pass backtracks
    ("rsync a 1MB", "", "rsync a ", " ls", 1000000),  # one DELETE_RE search no signal stops on 3.9: 26 s there
]
SUDO_A = ("sudo -a", " ", "sudo -a ", " ")  # segments() copied the token list once per option


def _shape(prefix, unit, suffix, size=100000):
    return prefix + unit * (size // len(unit)) + suffix


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
    except Exception:  # a rule's own handler must not keep the hook waiting
        return None
    return None


def _one_long_search(ev, cfg):
    """A rule that sits in one `re` search: about 26 s on Python 3.9, 6 s on 3.13; no signal handler stops it."""
    re.search(r"rsync\s.*--delete", "rsync a " * 125_000)
    return None


def _endless(ev, cfg):
    """A rule that never returns (a Python loop)."""
    while True:
        pass


def _suicide(ev, cfg):
    """A rule that kills its own process."""
    os.kill(os.getpid(), signal.SIGKILL)


def _reason(out):
    got = json.loads(out)
    return got["permissionDecision"], got["permissionDecisionReason"]


def test_one_long_search_turns_into_a_budget_ask(guard, monkeypatch, capsys, tmp_path):
    """The regression: on Python 3.9 the SIGALRM timer of 346af3e answered only when the search returned."""
    if not HAS_FORK:  # Windows: no fork, the rules run in the hook process without a budget (a named limit)
        return
    monkeypatch.setattr(guard, "HOOK_BUDGET_S", 0.5)
    monkeypatch.setitem(guard.RULES, "deploy-ask", _one_long_search)
    t0 = time.monotonic()
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert time.monotonic() - t0 < 2
    assert code == 0
    verdict, reason = _reason(out)
    assert verdict == "ask" and "could not be judged within" in reason and "deploy-ask" in reason


def test_a_slow_rule_turns_into_a_budget_ask(guard, monkeypatch, capsys, tmp_path):
    if not HAS_FORK:  # Windows: no fork, the rules run in the hook process without a budget (a named limit)
        return
    monkeypatch.setattr(guard, "HOOK_BUDGET_S", 0.2)
    monkeypatch.setitem(guard.RULES, "deploy-ask", _sleeper)
    t0 = time.monotonic()
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert time.monotonic() - t0 < 2
    assert code == 0
    verdict, reason = _reason(out)
    assert verdict == "ask"
    assert "could not be judged within" in reason and "7 characters" in reason
    assert "deploy-ask" in reason and "host-install" in reason and "delete-guard" not in reason
    lines = _decisions(tmp_path)
    assert [line["rules"] for line in lines] == [{"budget": "ask"}]


def test_a_rule_that_never_returns_asks_at_the_budget(guard, monkeypatch, capsys, tmp_path):
    if not HAS_FORK:  # Windows: no fork, the rules run in the hook process without a budget (a named limit)
        return
    monkeypatch.setattr(guard, "HOOK_BUDGET_S", 0.3)
    monkeypatch.setitem(guard.RULES, "git-guard", _endless)
    t0 = time.monotonic()
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert time.monotonic() - t0 < 2
    verdict, reason = _reason(out)
    assert (code, verdict) == (0, "ask")
    assert "git-guard" in reason and "deploy-ask" in reason and "host-install" in reason
    assert "delete-guard" not in reason


def test_a_deny_before_the_budget_stays_a_deny(guard, monkeypatch, capsys, tmp_path):
    if not HAS_FORK:  # Windows: no fork, the rules run in the hook process without a budget (a named limit)
        return
    monkeypatch.setattr(guard, "HOOK_BUDGET_S", 0.2)
    monkeypatch.setitem(guard.RULES, "delete-guard", lambda ev, cfg: ("deny", "fake deny"))
    monkeypatch.setitem(guard.RULES, "git-guard", _sleeper)
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert code == 2
    assert _reason(out) == ("deny", "fake deny")
    assert _decisions(tmp_path)[0]["rules"] == {"delete-guard": "deny", "budget": "ask"}


def _boom(ev, cfg):
    raise KeyError("no such key")


def test_a_rule_that_raises_ends_the_hook_with_exit_1(guard, monkeypatch, capsys, tmp_path):
    """Same text as when the rule ran in the hook process: main prints `guard: error: <str(exc)>`."""
    monkeypatch.setitem(guard.RULES, "git-guard", _boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_raw("echo hi", tmp_path))))
    code = guard.main(["hook", "pre", "--wrapper", "claude"])
    captured = capsys.readouterr()
    assert code == 1 and captured.out == ""
    assert captured.err == f"guard: error: {KeyError('no such key')}\n"
    assert _decisions(tmp_path) == []


def test_a_rule_that_kills_its_process_asks(guard, monkeypatch, capsys, tmp_path):
    if not HAS_FORK:  # Windows: no fork; a rule that kills the hook process cannot be answered for
        return
    monkeypatch.setitem(guard.RULES, "delete-guard", lambda ev, cfg: ("ask", "fake ask"))
    monkeypatch.setitem(guard.RULES, "deploy-ask", _suicide)
    t0 = time.monotonic()
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert time.monotonic() - t0 < 2  # the end of the pipe answers at once, not at the budget
    verdict, reason = _reason(out)
    assert (code, verdict) == (0, "ask")
    assert reason.startswith("fake ask | ") and "stopped before they finished" in reason
    assert "deploy-ask" in reason and "host-install" in reason and "git-guard" not in reason
    assert _decisions(tmp_path)[0]["rules"] == {"delete-guard": "ask", "budget": "ask"}


def test_a_long_reason_arrives_whole(guard, monkeypatch, capsys, tmp_path):
    long = "why " * 50_000  # 200 kB: more than one pipe buffer
    monkeypatch.setitem(guard.RULES, "deploy-ask", lambda ev, cfg: ("ask", long))
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert code == 0 and _reason(out) == ("ask", long)


def test_rules_off_with_a_slow_later_rule_still_logs_the_skip(guard, monkeypatch, capsys, tmp_path):
    if not HAS_FORK:  # Windows: no fork, the rules run in the hook process without a budget (a named limit)
        return
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "guard.json").write_text(json.dumps({"boundary": "own", "rules_off": ["delete-guard"]}))
    monkeypatch.setattr(guard, "HOOK_BUDGET_S", 0.2)
    monkeypatch.setitem(guard.RULES, "delete-guard", lambda ev, cfg: ("ask", "fake ask"))
    monkeypatch.setitem(guard.RULES, "git-guard", _sleeper)
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert code == 0 and "could not be judged within" in _reason(out)[1]
    assert [(r["verdict"], r["rules"]) for r in _decisions(tmp_path)] == [
        ("ask", {"budget": "ask"}), ("skipped", {"delete-guard": "skipped"})]


def _fork_raises():
    raise OSError("fork failed")


@pytest.mark.parametrize("how", ["no-fork", "fork-raises"])
def test_without_a_fork_the_rules_run_in_process(guard, monkeypatch, capsys, tmp_path, how):
    """Windows has no os.fork, and a fork can fail: the hook runs the rules itself, without a budget."""
    if how == "no-fork":
        monkeypatch.delattr(guard.os, "fork", raising=False)
    else:
        monkeypatch.setattr(guard.os, "fork", _fork_raises)
    marker = tmp_path / "ran-here"

    def rule(ev, cfg):
        marker.write_text(str(os.getpid()))  # proves which process ran it
        return ("ask", "fake ask")

    monkeypatch.setitem(guard.RULES, "deploy-ask", rule)
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert code == 0 and _reason(out) == ("ask", "fake ask")
    assert marker.read_text() == str(os.getpid())


def test_a_fast_hook_leaves_no_child_and_prints_only_the_response(guard, monkeypatch, capsys, tmp_path):
    if not HAS_FORK:  # Windows: no fork, so no child either
        return
    pids = []
    real_fork = os.fork

    def recording_fork():
        pid = real_fork()
        if pid:
            pids.append(pid)
        return pid

    monkeypatch.setattr(guard.os, "fork", recording_fork)
    monkeypatch.setitem(guard.RULES, "deploy-ask", lambda ev, cfg: ("ask", "fake ask"))
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path))
    assert code == 0 and out.count("\n") == 1 and _reason(out) == ("ask", "fake ask")
    assert len(pids) == 1
    with pytest.raises(ChildProcessError):  # reaped: the hook waited for it, nothing is left
        os.waitpid(pids[0], os.WNOHANG)


def _no_fork():
    raise AssertionError("forked")


def test_capture_and_post_never_fork(guard, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(guard.os, "fork", _no_fork)
    code, out = _run_in_process(guard, monkeypatch, capsys, _raw("echo hi", tmp_path), target="capture")
    assert (code, out) == (0, "")
    post = dict(_raw("echo hi", tmp_path), hook_event_name="PostToolUse", tool_use_id="toolu_1")
    code, out = _run_in_process(guard, monkeypatch, capsys, post, target="post")
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


@pytest.mark.parametrize("name,prefix,unit,suffix,size", SLOW_SHAPES, ids=[s[0] for s in SLOW_SHAPES])
def test_a_slow_shape_asks_before_the_harness_cuts_the_hook(guard_path, tmp_path, name, prefix, unit, suffix, size):
    if not HAS_FORK:  # Windows: no fork, the shape still runs past the harness timeout (a named limit)
        return
    r, seconds = _hook(guard_path, _shape(prefix, unit, suffix, size), tmp_path)
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
