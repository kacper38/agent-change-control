import datetime as dt
import io
import json
import os
import subprocess

import pytest

ALPHA = "-Users-t-Developer-alpha"
BETA = "-Users-t-Developer-beta"
GOOD = None
tracked = None


@pytest.fixture(autouse=True)
def _bind(helpers):
    global GOOD, tracked
    GOOD, tracked = helpers.GOOD, helpers.tracked


def run(memstore, argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    code = memstore.main(argv, out=out, err=err, stdin=io.StringIO(stdin))
    return code, out.getvalue(), err.getvalue()


def store_paths(home):
    return str(home / ".claude" / "memory-store.git"), str(home / ".claude" / "projects")


# ---- init / commit / exclude -------------------------------------------------------------------


def test_init_imports_only_memory_files(memstore, home):
    code, out, _ = run(memstore, ["init"])
    assert code == 0 and "created" in out
    store, wt = store_paths(home)
    files = tracked(store, wt)
    assert files == sorted([
        f"{ALPHA}/memory/MEMORY.md", f"{ALPHA}/memory/a-one.md", f"{ALPHA}/memory/a-two.md",
        f"{BETA}/memory/MEMORY.md", f"{BETA}/memory/b-one.md",
    ])
    assert not any("session.jsonl" in f or "tool-results" in f for f in files)


def test_init_is_idempotent(memstore, home):
    run(memstore, ["init"])
    code, out, _ = run(memstore, ["init"])
    assert code == 0 and "nothing new to import" in out


def test_commit_one_file_and_delete(memstore, home):
    run(memstore, ["init"])
    store, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "a-three.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(GOOD.format(name="a-three", desc="d", typ="user"))
    code, out, _ = run(memstore, ["commit", path])
    assert code == 0 and "add a-three" in out
    os.remove(path)
    code, out, _ = run(memstore, ["commit", path])
    assert code == 0 and "delete a-three" in out
    assert f"{ALPHA}/memory/a-three.md" not in tracked(store, wt)
    code, out, _ = run(memstore, ["log", "-n", "3"])
    assert "memory(-Users-t-Developer-alpha): delete a-three" in out


def test_commit_ignores_non_memory_paths(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    for p in (os.path.join(wt, ALPHA, "session.jsonl"), "/etc/hosts", os.path.join(wt, ALPHA, "notes.md")):
        code, out, _ = run(memstore, ["commit", p])
        assert code == 0 and out == ""


def test_commit_without_store_is_a_noop_with_hint(memstore, home):
    _, wt = store_paths(home)
    code, out, _ = run(memstore, ["commit", os.path.join(wt, ALPHA, "memory", "a-one.md")])
    assert code == 0 and "run `memstore.py init`" in out


# ---- hook --------------------------------------------------------------------------------------


def test_hook_commits_and_validates(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "a-one.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(GOOD.format(name="a-one", desc="changed", typ="project"))
    payload = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": path}})
    code, _, err = run(memstore, ["hook"], stdin=payload)
    assert code == 0 and "update a-one" in err


def test_hook_exit_2_with_schema_feedback(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "bad.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\nname: bad\ndescription: x\nmetadata:\n  type: project\n---\nno stale_after\n")
    payload = json.dumps({"tool_input": {"file_path": path}})
    code, _, err = run(memstore, ["hook"], stdin=payload)
    assert code == 2
    assert "memory schema: bad.md" in err and "stale_after" in err
    assert "add bad" in err  # committed anyway: the hook records, the warning asks for a fix


def test_hook_commits_the_index_without_validating_it(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "MEMORY.md")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("- [a-one](a-one.md) — hook\n")
    code, out, err = run(memstore, ["hook"], stdin=json.dumps({"tool_input": {"file_path": path}}))
    assert code == 0 and "update MEMORY" in err and "memory schema" not in err


def test_hook_ignores_copilot_payloads(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "bad.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("no frontmatter\n")
    payload = json.dumps({"timestamp": "2026-10-29T10:00:00Z", "tool_input": {"file_path": path}})
    assert run(memstore, ["hook"], stdin=payload) == (0, "", "")


def test_hook_validates_even_when_the_commit_loses_a_lock(memstore, home, monkeypatch):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "bad.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("no frontmatter\n")
    calls = {"n": 0}
    real = memstore.Store.git

    def locked(self, args, check=True):
        if args[0] == "commit":
            calls["n"] += 1
            return subprocess.CompletedProcess(args, 128, "", "fatal: Unable to create 'index.lock': File exists.")
        return real(self, args, check)

    monkeypatch.setattr(memstore.Store, "git", locked)
    monkeypatch.setattr(memstore.time, "sleep", lambda s: None)
    code, _, err = run(memstore, ["hook"], stdin=json.dumps({"tool_input": {"file_path": path}}))
    assert calls["n"] == 3 and "commit skipped" in err
    assert code == 2 and "memory schema: bad.md: no frontmatter" in err


def test_non_utf8_memory_file_is_a_warning_not_a_crash(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "bytes.md")
    with open(path, "wb") as fh:
        fh.write(b"---\nname: bytes\ndescription: d\xff\xfe\nmetadata:\n  type: user\n---\n\xff\n")
    assert memstore.validate_file(path) == []
    assert "bytes" in memstore.build_index(wt, ALPHA)
    assert memstore.digest(memstore.Store(), "/Users/t/Developer/alpha")[0] == "Memory: 3 files for this project"
    code, _, err = run(memstore, ["hook"], stdin=json.dumps({"tool_input": {"file_path": path}}))
    assert code == 0 and "add bytes" in err


@pytest.mark.parametrize("stdin", ["", "not json", json.dumps({"tool_input": {"file_path": "/tmp/x.py"}}),
                                   json.dumps({"tool_input": "weird"})])
def test_hook_silent_on_irrelevant_input(memstore, home, stdin):
    run(memstore, ["init"])
    code, out, err = run(memstore, ["hook"], stdin=stdin)
    assert (code, out, err) == (0, "", "")


# ---- push policy -------------------------------------------------------------------------------


def _add_remote(home):
    store, wt = store_paths(home)
    remote = home / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    env = {**os.environ, "GIT_DIR": store, "GIT_WORK_TREE": wt}
    subprocess.run(["git", "remote", "add", "origin", str(remote)], env=env, check=True, cwd=wt)
    return remote


def test_push_off_without_remote_and_without_env(memstore, home, monkeypatch):
    run(memstore, ["init"])
    code, out, _ = run(memstore, ["push"])
    assert code == 0 and "no remote" in out
    _add_remote(home)
    code, out, _ = run(memstore, ["push"])
    assert code == 0 and "push off" in out


def test_push_refuses_projects_outside_allowlist(memstore, home, monkeypatch):
    run(memstore, ["init"])
    remote = _add_remote(home)
    monkeypatch.setenv("KZ_MEMORY_PUSH", ALPHA)
    code, out, _ = run(memstore, ["push"])
    assert code == 3 and BETA in out  # the import commit touched beta too
    monkeypatch.setenv("KZ_MEMORY_PUSH", "*")
    code, out, _ = run(memstore, ["push"])
    assert code == 0 and "pushed" in out
    heads = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "main"], capture_output=True, text=True)
    assert heads.returncode == 0


def test_push_refuses_when_the_touched_set_is_unknown(memstore, home, monkeypatch):
    run(memstore, ["init"])
    _add_remote(home)
    monkeypatch.setenv("KZ_MEMORY_PUSH", ALPHA)
    store = memstore.Store()
    real = store.git

    def broken(args, check=True):
        if args[0] == "log":
            return subprocess.CompletedProcess(args, 128, "", "fatal: bad object")
        return real(args, check)

    store.git = broken
    out = io.StringIO()
    assert store.push(out) == 3 and "cannot list unpushed commits" in out.getvalue()


def test_push_allows_when_only_allowlisted_projects_changed(memstore, home, monkeypatch):
    run(memstore, ["init"])
    _add_remote(home)
    monkeypatch.setenv("KZ_MEMORY_PUSH", "*")
    assert run(memstore, ["push"])[0] == 0
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "a-one.md")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("more\n")
    run(memstore, ["commit", path])
    monkeypatch.setenv("KZ_MEMORY_PUSH", ALPHA)
    code, out, _ = run(memstore, ["push"])
    assert code == 0 and "pushed" in out


# ---- schema ------------------------------------------------------------------------------------


def test_validate_good(memstore):
    assert memstore.validate_text(GOOD.format(name="n", desc="d", typ="project")) == []
    assert memstore.validate_text("---\nname: n\ndescription: d\nmetadata:\n  type: user\n---\nx\n") == []


@pytest.mark.parametrize("text,needle", [
    ("no frontmatter at all\n", "no frontmatter"),
    ("---\ndescription: d\nmetadata:\n  type: user\n---\n", "missing `name`"),
    ("---\nname: n\nmetadata:\n  type: user\n---\n", "missing `description`"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: note\n---\n", "metadata.type must be one of"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: project\n---\n", "stale_after"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: reference\n---\n", "stale_after"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: project\n  stale_after: soon\n---\n", "not a date"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: project\n  stale_after: 2026-02-30\n---\n", "not a date"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: user\n  verified: true\n  verified_on: 2026-13-01\n---\n",
     "verified_on"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: project\n  stale_after: 2020-01-01\n---\n", "stale since"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: user\n  status: gone\n---\n", "metadata.status"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: user\n  status: superseded\n---\n", "superseded_by"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: user\n  superseded_by: x\n---\n", "status is active"),
    ("---\nname: n\ndescription: d\nmetadata:\n  type: user\n  verified: true\n---\n", "verified_on"),
])
def test_validate_warnings(memstore, text, needle):
    warnings = memstore.validate_text(text, today=dt.date(2026, 10, 29))
    assert any(needle in w for w in warnings), warnings


def test_deprecated_memory_may_be_stale_without_warning(memstore):
    text = ("---\nname: n\ndescription: d\nmetadata:\n  type: project\n  status: deprecated\n"
            "  stale_after: 2020-01-01\n---\n")
    assert memstore.validate_text(text, today=dt.date(2026, 10, 29)) == []


def test_existing_memory_format_parses(memstore):
    text = ('---\nname: claude-setup-landscape-2026-10\ndescription: "Where things live (mapped 2026-10-27)"\n'
            "metadata:\n  node_type: memory\n  type: project\n  originSessionId: 6b99\n"
            "  modified: 2026-10-27T15:32:21.749Z\n---\n\nbody\n")
    fm = memstore.parse_frontmatter(text)
    assert fm["name"] == "claude-setup-landscape-2026-10"
    assert fm["description"].startswith("Where things live")
    assert fm["metadata"]["type"] == "project"
    assert memstore.validate_text(text) == ["metadata.stale_after: YYYY-MM-DD is required for type project "
                                            "(facts about work and links age)"]


def test_validate_cli_exit_codes(memstore, home, tmp_path):
    good = tmp_path / "g.md"
    good.write_text(GOOD.format(name="g", desc="d", typ="user"), encoding="utf-8")
    bad = tmp_path / "b.md"
    bad.write_text("nothing\n", encoding="utf-8")
    assert run(memstore, ["validate", str(good)])[0] == 0
    code, _, err = run(memstore, ["validate", str(good), str(bad)])
    assert code == 2 and "b.md: no frontmatter" in err


# ---- index / triage / deprecate / digest -------------------------------------------------------


def test_index_lists_active_only_and_writes(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    cwd = "/Users/t/Developer/alpha"
    assert memstore.cwd_slug(cwd) == ALPHA
    code, out, _ = run(memstore, ["index", "--cwd", cwd])
    assert code == 0
    assert out.startswith("# Memory index\n\n- [a-one](a-one.md) — about a-one\n- [a-two](a-two.md) — about a-two\n")
    run(memstore, ["deprecate", os.path.join(wt, ALPHA, "memory", "a-two.md")])
    code, out, _ = run(memstore, ["index", "--cwd", cwd, "--write"])
    assert code == 0 and "wrote" in out
    index = open(os.path.join(wt, ALPHA, "memory", "MEMORY.md"), encoding="utf-8").read()
    assert "a-one" in index and "a-two" not in index
    code, out, _ = run(memstore, ["log", "-n", "2"])
    assert "update MEMORY" in out and "update a-two" in out


def test_index_respects_size_cap(memstore, home):
    _, wt = store_paths(home)
    d = os.path.join(wt, ALPHA, "memory")
    for i in range(400):
        with open(os.path.join(d, f"m-{i:03}.md"), "w", encoding="utf-8") as fh:
            fh.write(GOOD.format(name=f"m-{i:03}", desc="x" * 80, typ="user"))
    text = memstore.build_index(wt, ALPHA)
    assert len(text.encode()) <= memstore.INDEX_MAX_BYTES
    assert "more not indexed" in text


def test_deprecate_superseded_by(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "a-one.md")
    code, out, _ = run(memstore, ["deprecate", path, "--by", "a-two"])
    assert code == 0
    text = open(path, encoding="utf-8").read()
    assert "  status: superseded\n  superseded_by: a-two\n" in text
    assert text.endswith("Body of a-one.\n")
    assert memstore.validate_text(text) == []


def test_deprecate_refuses_unterminated_frontmatter(memstore, home, tmp_path):
    bad = tmp_path / "x.md"
    bad.write_text("---\nname: x\nbody without a closing fence\n", encoding="utf-8")
    code, _, err = run(memstore, ["deprecate", str(bad)])
    assert code == 1 and "no frontmatter" in err
    assert bad.read_text(encoding="utf-8") == "---\nname: x\nbody without a closing fence\n"


def test_cwd_slug_matches_claude_code_naming(memstore):
    assert memstore.cwd_slug("/Users/t/Developer/my_app v2.0") == "-Users-t-Developer-my-app-v2-0"
    assert memstore.cwd_slug("/Users/kacperz/Developer/agent-change-control") == ALPHA.replace(
        "-Users-t-Developer-alpha", "-Users-kacperz-Developer-agent-change-control")


def test_hook_survives_an_impossible_date(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    path = os.path.join(wt, ALPHA, "memory", "odd.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\nname: odd\ndescription: d\nmetadata:\n  type: project\n  stale_after: 2026-02-30\n---\n")
    code, _, err = run(memstore, ["hook"], stdin=json.dumps({"tool_input": {"file_path": path}}))
    assert code == 2 and "not a date" in err
    assert memstore.digest(memstore.Store(), "/Users/t/Developer/alpha")[0].startswith("Memory: 3 files")


def test_triage_and_digest(memstore, home):
    run(memstore, ["init"])
    _, wt = store_paths(home)
    with open(os.path.join(wt, ALPHA, "memory", "old.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: old\ndescription: d\nmetadata:\n  type: project\n  stale_after: 2020-01-01\n---\n")
    code, out, _ = run(memstore, ["triage", "--cwd", "/Users/t/Developer/alpha"])
    assert code == 0 and "3 files, 1 with warnings" in out and "stale since 2020-01-01" in out
    lines = memstore.digest(memstore.Store(), "/Users/t/Developer/alpha")
    assert lines[0] == "Memory: 3 files for this project"
    assert any(ln.startswith("Recent memory commits:") for ln in lines)
    assert any(ln.startswith("Stale (re-verify or deprecate): old.md") for ln in lines)
    assert len(lines) <= memstore.DIGEST_MAX_LINES and sum(len(ln) + 1 for ln in lines) <= memstore.DIGEST_MAX_BYTES
    assert memstore.digest(memstore.Store(), "/Users/t/Developer/nothing-here") == []
