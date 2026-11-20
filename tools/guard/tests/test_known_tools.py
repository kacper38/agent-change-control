"""KNOWN_CLAUDE_TOOLS (item #65, D11): every built-in tool of a session is named with how the guard treats it, and
the guard's PreToolUse matcher names every tool a rule judges. The probe's tool-list canary fails when the
session's list differs from these names."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
TREATMENTS = {"judged", "harmless", "cloud-launch"}


def _pre_matcher() -> list:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    (matcher,) = [m["matcher"] for m in settings["hooks"]["PreToolUse"]
                  if any("guard.py hook pre" in h["command"] for h in m["hooks"])]
    return matcher.split("|")


def test_every_known_tool_has_a_treatment(guard):
    assert guard.KNOWN_CLAUDE_TOOLS and set(guard.KNOWN_CLAUDE_TOOLS.values()) <= TREATMENTS


def test_every_judged_tool_is_in_the_pre_matcher(guard):
    names = _pre_matcher()
    missing = [t for t, how in guard.KNOWN_CLAUDE_TOOLS.items() if how != "harmless" and t not in names]
    assert missing == [], f"the PreToolUse matcher of the guard does not name {missing}"


def test_every_judged_tool_has_a_kind(guard):
    missing = [t for t, how in guard.KNOWN_CLAUDE_TOOLS.items() if how != "harmless" and t not in guard.CLAUDE_TOOLS]
    assert missing == [], f"no kind in CLAUDE_TOOLS for {missing}"


def test_the_fan_out_tool_is_matched_by_both_its_names():
    # the init message lists the fan-out tool as Task, while the hook rows of the probe name it Agent
    assert {"Agent", "Task"} <= set(_pre_matcher())
