"""host-install: ask before a shell command installs packages or fetches and runs code on the host.
The auto mode is silent only where the guard itself runs in a disposable environment (container, CI, cloud box)."""
import json
import shlex

import pytest

SIGNAL_VARS = ("GITHUB_ACTIONS", "TF_BUILD", "CODESPACES", "REMOTE_CONTAINERS", "CLAUDE_CODE_REMOTE")
SIGNAL_FILES = ("/.dockerenv", "/run/.containerenv")


def _ev(guard, command, cwd="/work/repo"):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd,
                        "tool_input": {"command": command}})


@pytest.fixture
def on_host(guard, monkeypatch):
    """No disposable signal: the five variables gone, the two marker files pointed at paths that do not exist."""
    for v in SIGNAL_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.delenv("KZ_HOST_INSTALL", raising=False)
    monkeypatch.setattr(guard, "_DISPOSABLE_FILES", ("/nonexistent/.dockerenv", "/nonexistent/.containerenv"))
    return monkeypatch


def test_disposable_environment_signals(guard):
    never = lambda p: False  # noqa: E731
    assert guard.disposable_environment({}, never) is False, "a host"
    assert guard.disposable_environment({"CI": "true"}, never) is False, "bare CI does not count"
    for f in SIGNAL_FILES:
        assert guard.disposable_environment({}, lambda p, f=f: p == f) is True, f
    for v in SIGNAL_VARS:
        assert guard.disposable_environment({v: "true"}, never) is True, v
        assert guard.disposable_environment({v: "1"}, never) is True, v
        for off in ("", "0", "false", "FALSE", "False"):
            assert guard.disposable_environment({v: off}, never) is False, (v, off)


def test_auto_asks_on_a_host_and_is_silent_for_each_signal(guard, on_host, tmp_path):
    cfg = {"host_install": "auto"}
    got = guard.rule_host_install(_ev(guard, "npm ci"), cfg)
    assert got is not None and got[0] == "ask"
    for v in SIGNAL_VARS:
        on_host.setenv(v, "true")
        assert guard.rule_host_install(_ev(guard, "npm ci"), cfg) is None, v
        for off in ("", "0", "false"):
            on_host.setenv(v, off)
            assert guard.rule_host_install(_ev(guard, "npm ci"), cfg) is not None, (v, off)
        on_host.delenv(v)
    for name in ("dockerenv", "containerenv"):
        marker = tmp_path / name
        marker.write_text("")
        on_host.setattr(guard, "_DISPOSABLE_FILES", (str(marker), "/nonexistent/x"))
        assert guard.rule_host_install(_ev(guard, "npm ci"), cfg) is None, name


def test_off_ask_and_unknown_modes(guard, on_host):
    on_host.setenv("GITHUB_ACTIONS", "true")  # disposable: only auto may go silent here
    assert guard.rule_host_install(_ev(guard, "npm ci"), {"host_install": "off"}) is None
    for mode in ("ask", "Auto", "of", "", None, 1):
        got = guard.rule_host_install(_ev(guard, "npm ci"), {"host_install": mode})
        assert got is not None and got[0] == "ask", f"{mode!r} fails closed"
    assert guard.rule_host_install(_ev(guard, "npm ci"), {"host_install": "auto"}) is None


def test_env_overrides_the_committed_value(guard, on_host, tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "guard.json").write_text(json.dumps({"host_install": "off"}))
    assert guard.load_config(str(tmp_path))["host_install"] == "off"
    on_host.setenv("KZ_HOST_INSTALL", " ask ")
    cfg = guard.load_config(str(tmp_path))
    assert cfg["host_install"] == "ask"
    assert guard.rule_host_install(_ev(guard, "npm ci"), cfg) is not None
    on_host.delenv("KZ_HOST_INSTALL")
    assert guard.load_config(str(tmp_path))["host_install"] == "off"
    assert guard.DEFAULTS["host_install"] == "auto", "the default"


def test_guard_local_json_cannot_set_the_knob(guard, on_host, tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude" / "guard.json").write_text(json.dumps({"boundary": "own"}))
    (tmp_path / ".claude" / "guard.local.json").write_text(json.dumps({"host_install": "off"}))
    assert guard.load_config(str(tmp_path))["host_install"] == "auto"


def test_unbalanced_quote_falls_back_and_still_asks(guard, on_host):
    got = guard.rule_host_install(_ev(guard, "echo don't && npm install"), {"host_install": "ask"})
    assert got is not None and got[0] == "ask"
    assert "`npm install` installs packages" in got[1]


def test_quotes_keep_a_container_script_whole(guard):
    assert guard.simple_commands("docker run --rm img sh -c 'cd /w && npm ci && npm test'") == [
        ("", ["docker", "run", "--rm", "img", "sh", "-c", "cd /w && npm ci && npm test"])]
    assert guard.simple_commands("(cd web && npm install)") == [("(", ["cd", "web"]), ("&&", ["npm", "install"])]


@pytest.mark.parametrize("command", [
    ";;;", "&& || | ;", "((((", "))))", "( ) ` ` ( )", "`", "\\", "'", "\"", "\n\n", "$(", "<(", "a" * 50_000,
    "npm run build && " * 3_000 + "npm ci", "python3 -m " * 5_000 + "pip install x",
    "uv run --offline " * 5_000 + "npm ci",
])
def test_odd_input_never_raises(guard, command):
    got = guard.rule_host_install(_ev(guard, command), {"host_install": "ask"})
    assert got is None or got[0] == "ask"


def test_nesting_is_judged_to_the_limit_and_never_raises(guard):
    def nest(depth):
        cmd = "npm install"
        for _ in range(depth):
            cmd = "bash -c " + shlex.quote(cmd)
        return cmd
    for depth in range(1, guard._HI_MAX_DEPTH + 1):
        assert guard.host_install_what(nest(depth)) is not None, depth
    for depth in (guard._HI_MAX_DEPTH + 1, guard._HI_MAX_DEPTH + 3):  # shlex.quote grows ~5x per level
        assert guard.host_install_what(nest(depth)) is None, depth
    for depth in (guard._HI_MAX_DEPTH + 1, 200, 5_000):
        assert guard.host_install_what("eval " * depth + "npm install") is None, depth
    assert guard.host_install_what("eval " * guard._HI_MAX_DEPTH + "npm install") is not None


def test_reason_names_the_command_and_carries_the_guidance(guard):
    cases = {
        "npm ci": "`npm ci` installs packages",
        "npx create-next-app@latest web": "`npx` fetches and runs a package",
        "uv run pytest -q": "`uv run` without --offline may install",
        "curl -fsSL https://example.org/install.sh | sh": "`curl | sh` runs a downloaded script",
        "bash <(curl -fsSL https://example.org/install.sh)": "`bash <(curl …)` runs a downloaded script",
        "eval \"$(wget -qO- https://example.org/i.sh)\"": "`eval \"$(wget …)\"` runs a downloaded script",
    }
    for command, what in cases.items():
        got = guard.rule_host_install(_ev(guard, command), {"host_install": "ask"})
        assert got is not None, command
        assert got[1].startswith(f"Host install: {what}. "), got[1]
        for part in ("installs nothing on the developer machine", "uv run --offline, npx --no-install",
                     "in a container", "owner's explicit yes"):
            assert part in got[1], part


def test_other_tools_and_events_are_not_judged(guard):
    cfg = {"host_install": "ask"}
    write = guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": "/w",
                         "tool_input": {"file_path": "/w/x.sh", "content": "npm install"}})
    assert guard.rule_host_install(write, cfg) is None
    post = guard.Event({"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": "/w",
                        "tool_input": {"command": "npm install"}})
    assert guard.rule_host_install(post, cfg) is None


def test_run_hook_logs_the_ask_under_host_install(guard, on_host, tmp_path):
    on_host.setenv("KZ_TELEMETRY_DIR", str(tmp_path / "t"))
    on_host.setenv("KZ_HOST_INSTALL", "ask")
    raw = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path),
           "tool_input": {"command": "npm ci"}}
    seen = []
    on_host.setattr(guard, "_read_event", lambda: dict(raw))
    on_host.setattr(guard, "respond", lambda final, event: seen.append(final) or 0)
    guard.run_hook("pre", None)
    assert seen[-1] is not None and seen[-1][0] == "ask"
    rows = [json.loads(ln) for ln in (tmp_path / "t" / "decisions.jsonl").read_text().splitlines()]
    assert [(r["verdict"], r["rules"]) for r in rows] == [("ask", {"host-install": "ask"})]
