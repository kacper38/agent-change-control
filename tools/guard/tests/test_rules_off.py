"""rules_off: the owner's uncommitted override switches named rules off (guard.local.json or KZ_RULES_OFF),
in the own boundary only."""
import json
import os


def _repo(tmp_path, local=None):
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "guard.json").write_text(json.dumps({"boundary": "own"}))
    if local is not None:
        (tmp_path / ".claude" / "guard.local.json").write_text(json.dumps(local))
    return str(tmp_path)


def test_local_file_sets_rules_off_and_nothing_else(guard, tmp_path, monkeypatch):
    monkeypatch.delenv("KZ_RULES_OFF", raising=False)
    assert guard.load_config(_repo(tmp_path))["rules_off"] == []
    local = {"rules_off": ["delete-guard"], "boundary": "client", "protected_branches": [], "scratch_md_mode": "off"}
    cfg = guard.load_config(_repo(tmp_path / "b", local))
    assert cfg["rules_off"] == ["delete-guard"]
    assert (cfg["boundary"], cfg["protected_branches"], cfg["scratch_md_mode"]) == ("own", ["main"], "ask")


def test_malformed_or_unknown_rules_off_is_reported(guard, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KZ_RULES_OFF", raising=False)
    assert guard.load_config(_repo(tmp_path, {"rules_off": "delete-guard"}))["rules_off"] == []
    assert "ignoring rules_off" in capsys.readouterr().err
    assert guard.load_config(_repo(tmp_path / "b", {"rules_off": ["delete-gaurd"]}))["rules_off"] == ["delete-gaurd"]
    assert "no rule 'delete-gaurd'" in capsys.readouterr().err
    guard.load_config(_repo(tmp_path / "c", {"rules_off": ["delete-guard"]}))
    assert capsys.readouterr().err == ""


def test_env_overrides_the_file(guard, tmp_path, monkeypatch):
    cwd = _repo(tmp_path, {"rules_off": ["delete-guard"]})
    monkeypatch.setenv("KZ_RULES_OFF", "guard-config, scratch-md")
    assert guard.load_config(cwd)["rules_off"] == ["guard-config", "scratch-md"]
    monkeypatch.setenv("KZ_RULES_OFF", "")
    assert guard.load_config(cwd)["rules_off"] == []


def test_local_file_is_hook_configuration(guard, tmp_path):
    assert guard.guard_config_class(os.path.join(str(tmp_path), ".claude", "guard.local.json")) is not None


def test_run_hook_skips_a_rule_that_is_off(guard, tmp_path, monkeypatch):
    monkeypatch.setenv("KZ_TELEMETRY_DIR", str(tmp_path / "t"))
    monkeypatch.delenv("KZ_RULES_OFF", raising=False)
    raw = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": _repo(tmp_path),
           "tool_input": {"command": "rm -rf /tmp/kit-target"}}
    seen = []
    monkeypatch.setattr(guard, "_read_event", lambda: dict(raw))
    monkeypatch.setattr(guard, "respond", lambda final, event: seen.append(final) or 0)
    guard.run_hook("pre", None)
    assert seen[-1] is not None and seen[-1][0] == "ask"
    (tmp_path / ".claude" / "guard.local.json").write_text(json.dumps({"rules_off": ["delete-guard"]}))
    guard.run_hook("pre", None)
    assert seen[-1] is None


def test_client_boundary_keeps_every_rule(guard, tmp_path, monkeypatch):
    monkeypatch.setenv("KZ_TELEMETRY_DIR", str(tmp_path / "t"))
    monkeypatch.delenv("KZ_RULES_OFF", raising=False)
    monkeypatch.delenv("KZ_BOUNDARY", raising=False)
    cwd = _repo(tmp_path, {"rules_off": ["delete-guard"]})
    raw = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd,
           "tool_input": {"command": "rm -rf /tmp/kit-target"}}
    seen = []
    monkeypatch.setattr(guard, "_read_event", lambda: dict(raw))
    monkeypatch.setattr(guard, "respond", lambda final, event: seen.append(final) or 0)
    guard.run_hook("pre", None)
    assert seen[-1] is None, "own boundary: the rule is off"
    (tmp_path / ".claude" / "guard.json").write_text(json.dumps({"boundary": "client"}))
    guard.run_hook("pre", None)
    assert seen[-1] is not None and seen[-1][0] == "ask", "committed client boundary: the override is ignored"
    (tmp_path / ".claude" / "guard.json").write_text(json.dumps({"boundary": "own"}))
    monkeypatch.setenv("KZ_BOUNDARY", "client")
    guard.run_hook("pre", None)
    assert seen[-1] is not None and seen[-1][0] == "ask", "KZ_BOUNDARY=client: the override is ignored"
