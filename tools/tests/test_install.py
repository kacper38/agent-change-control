"""install.sh in user scope (`CLAUDE_DIR`): the manifest paths around the 2026-11-01 rename;
and in repo scope (`--into`): the forge column of kit.manifest (plan step A5).

A pre-rename install left `claude-platform-setup.manifest`; the installer now writes
`agent-change-control.manifest`. These tests run the real script against a temporary
`CLAUDE_DIR` or target repo so neither `~/.claude` nor the repo is touched.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install.sh"
NEW = "agent-change-control.manifest"
LEGACY = "claude-platform-setup.manifest"


def run(dest: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "HOME": str(dest.parent), "CLAUDE_DIR": str(dest)}
    return subprocess.run(["bash", str(INSTALL), *args], cwd=ROOT, env=env, text=True, capture_output=True)


def listed(manifest: pathlib.Path) -> list[str]:
    return [ln for ln in manifest.read_text().splitlines() if ln and not ln.startswith("#")]


def legacy_install(dest: pathlib.Path, files: list[str]) -> None:
    """What a pre-rename `install.sh` left behind: the files and a legacy manifest naming them."""
    for rel in files:
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("old\n")
    (dest / LEGACY).write_text("# claude-platform-setup — installed earlier @ abc1234\n" + "\n".join(files) + "\n")


def test_uninstall_reads_a_legacy_manifest(tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "claude"
    dest.mkdir()
    legacy_install(dest, ["agents/old-agent.md", "skills/old/SKILL.md"])

    r = run(dest, "--uninstall")

    assert r.returncode == 0, r.stderr
    assert not (dest / "agents/old-agent.md").exists()
    assert not (dest / "skills/old/SKILL.md").exists()
    assert not (dest / LEGACY).exists()


def test_reinstall_over_a_legacy_install_keeps_one_manifest_with_the_legacy_entries(tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "claude"
    dest.mkdir()
    legacy_install(dest, ["agents/old-agent.md"])

    r = run(dest)

    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in dest.glob("*.manifest")) == [NEW]
    entries = listed(dest / NEW)
    assert "agents/infra-reviewer.md" in entries and (dest / "agents/infra-reviewer.md").exists()
    assert "agents/old-agent.md" in entries and (dest / "agents/old-agent.md").exists()
    assert len(entries) == len(set(entries)), "manifest entries are unique"

    r = run(dest, "--uninstall")

    assert r.returncode == 0, r.stderr
    assert not (dest / "agents/old-agent.md").exists(), "the legacy-only file is still tracked after a reinstall"
    assert not (dest / "agents/infra-reviewer.md").exists()
    assert not list(dest.glob("*.manifest"))


def test_uninstall_with_both_manifests_removes_the_union(tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "claude"
    dest.mkdir()
    legacy_install(dest, ["agents/legacy-only.md"])
    (dest / "agents/new-only.md").write_text("new\n")
    (dest / NEW).write_text("# agent-change-control — installed later @ def5678\nagents/new-only.md\n")

    r = run(dest, "--uninstall")

    assert r.returncode == 0, r.stderr
    assert not (dest / "agents/legacy-only.md").exists()
    assert not (dest / "agents/new-only.md").exists()
    assert not list(dest.glob("*.manifest"))


def test_uninstall_without_any_manifest_refuses(tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "claude"
    dest.mkdir()

    r = run(dest, "--uninstall")

    assert r.returncode == 1
    assert "nothing to uninstall" in r.stderr
    assert not list(dest.iterdir())


def test_manifest_entries_outside_claude_dir_are_skipped(tmp_path: pathlib.Path) -> None:
    dest = tmp_path / "claude"
    dest.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n")
    (dest / "agents").mkdir()
    (dest / "agents/ok.md").write_text("old\n")
    (dest / LEGACY).write_text(f"# legacy\n{outside}\n../outside.txt\nagents/ok.md\n")

    r = run(dest)  # a reinstall merges the legacy manifest

    assert r.returncode == 0, r.stderr
    entries = listed(dest / NEW)
    assert "agents/ok.md" in entries
    assert not any(e.startswith("/") or ".." in e for e in entries)

    (dest / NEW).write_text(f"# new\n{outside}\n../outside.txt\nagents/ok.md\n")
    r = run(dest, "--uninstall")

    assert r.returncode == 0, r.stderr
    assert outside.read_text() == "keep\n"
    assert "unsafe manifest entry" in r.stderr
    assert not (dest / "agents/ok.md").exists()


# --- repo scope: the forge column ----------------------------------------------

ADO_ORIGIN = "https://org@dev.azure.com/org/project/_git/repo"
GITHUB_ORIGIN = "https://github.com/owner/repo.git"
GITHUB_ONLY = [".github/workflows/label-lint.yml", ".github/ISSUE_TEMPLATE/task.yml",
               ".github/ISSUE_TEMPLATE/bug.yml", ".github/ISSUE_TEMPLATE/config.yml"]
ADO_ONLY = {"azure-pipelines.yml": "ci/azure-pipelines.yml",
            "azure-pipelines-label-lint.yml": "ci/azure-pipelines-label-lint.yml"}


def target_repo(tmp_path: pathlib.Path, origin: str | None) -> pathlib.Path:
    t = tmp_path / "target"
    t.mkdir()
    subprocess.run(["git", "init", "-q", str(t)], check=True, capture_output=True)
    if origin:
        subprocess.run(["git", "-C", str(t), "remote", "add", "origin", origin], check=True)
    return t


def into(target: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "HOME": str(target.parent)}
    return subprocess.run(["bash", str(INSTALL), "--into", str(target), *args], cwd=ROOT, env=env, text=True,
                          capture_output=True)


def forge_of(target: pathlib.Path) -> list[str]:
    return [ln for ln in (target / ".claude/kit-version").read_text().splitlines() if ln.startswith("forge:")]


def assert_ado_files(t: pathlib.Path) -> None:
    for dst, src in ADO_ONLY.items():
        assert (t / dst).read_bytes() == (ROOT / src).read_bytes(), dst
    assert (t / "tools/testguard/ado_pr_context.py").exists(), "the guards job calls it"
    assert not (t / ".github/workflows").exists() and not (t / ".github/ISSUE_TEMPLATE").exists()
    assert (t / ".github/hooks/guard.json").exists(), "Copilot reads .github/hooks on any forge"
    assert forge_of(t) == ["forge: ado"]


def assert_github_files(t: pathlib.Path) -> None:
    for rel in GITHUB_ONLY:
        assert (t / rel).exists(), rel
    assert not any((t / dst).exists() for dst in ADO_ONLY)
    assert "azure-pipelines" not in (t / ".claude/kit-manifest.sha256").read_text()
    assert forge_of(t) == ["forge: github"]


def test_ado_target_gets_the_pipelines_not_the_workflows_and_a_second_run_changes_nothing(tmp_path):
    t = target_repo(tmp_path, ADO_ORIGIN)

    r = into(t)

    assert r.returncode == 0, r.stderr
    assert_ado_files(t)
    assert "forge: ado (detected: Azure DevOps origin); entries for the other forge skipped: 4" in r.stdout
    r = into(t)
    assert r.returncode == 0, r.stderr
    assert "changes: 0 " in r.stdout, r.stdout
    (t / "azure-pipelines.yml").write_text("# owned by the project now\n")
    r = into(t)
    assert "changes: 0 " in r.stdout and (t / "azure-pipelines.yml").read_text() == "# owned by the project now\n"


@pytest.mark.parametrize("origin,forge", [
    ("git@ssh.dev.azure.com:v3/org/project/repo", "ado"),
    ("https://org.visualstudio.com/DefaultCollection/project/_git/repo", "ado"),
    ("org@vs-ssh.visualstudio.com:v3/org/project/repo", "ado"),
    ("https://DEV.AZURE.COM/org/project/_git/repo", "ado"),
    (GITHUB_ORIGIN, "github"),
    ("git@github.com:owner/dev.azure.com.git", "github"),
    (None, "github"),
])
def test_origin_detection(tmp_path, origin, forge):
    t = target_repo(tmp_path, origin)
    assert into(t).returncode == 0
    assert forge_of(t) == [f"forge: {forge}"]


def test_github_target_is_unchanged(tmp_path):
    t = target_repo(tmp_path, GITHUB_ORIGIN)

    r = into(t)

    assert r.returncode == 0, r.stderr
    assert_github_files(t)
    assert "changes: 0 " in into(t).stdout


def test_explicit_forge_overrides_detection_and_leaves_other_forge_files_in_place(tmp_path):
    t = target_repo(tmp_path, ADO_ORIGIN)
    assert into(t, "--forge", "github").returncode == 0
    assert_github_files(t)

    r = into(t, "--forge", "ado", "--force")

    assert r.returncode == 0, r.stderr
    for dst, src in ADO_ONLY.items():
        assert (t / dst).read_bytes() == (ROOT / src).read_bytes(), dst
    assert (t / ".github/workflows/label-lint.yml").exists(), "never deletes"
    assert "note: .github/workflows/label-lint.yml is for github targets; left in place" in r.stdout
    assert forge_of(t) == ["forge: ado"]


@pytest.mark.parametrize("args,message", [
    (["--forge", "gitlab"], "--forge takes github or ado"),
    (["--forge"], "--forge takes github or ado"),
    (["--frobnicate"], "unknown argument: --frobnicate"),
    (["--boundary", "x"], "--boundary takes own or client"),
    (["--boundary"], "--boundary takes own or client"),
])
def test_bad_arguments_are_refused_before_any_copy(tmp_path, args, message):
    t = target_repo(tmp_path, None)
    r = into(t, *args)
    assert r.returncode == 1 and message in r.stderr
    assert not (t / ".claude").exists()


# --- repo scope: the boundary of a new target (plan step 1.8) ------------------

def boundary_of(target: pathlib.Path) -> str:
    return json.loads((target / ".claude/guard.json").read_text())["boundary"]


def test_a_new_target_gets_boundary_client_and_a_second_run_changes_nothing(tmp_path):
    t = target_repo(tmp_path, None)

    r = into(t)

    assert r.returncode == 0, r.stderr
    assert boundary_of(t) == "client"
    assert "  boundary: client (new file)" in r.stdout
    kit = (ROOT / ".claude/guard.json").read_text().splitlines()
    got = (t / ".claude/guard.json").read_text().splitlines()
    changed = [(a, b) for a, b in zip(kit, got) if a != b]
    assert [a for a, _ in changed][0] == '  "boundary": "own",' and len(kit) == len(got)
    # item #69: the kit's workflows bind the kit's reviewed files; a new target lists none of its own yet
    assert [b for _, b in changed] == ['  "boundary": "client",', '  "workflows": []']
    assert json.loads((ROOT / ".claude/guard.json").read_text())["workflows"]
    assert json.loads((t / ".claude/guard.json").read_text())["workflows"] == []
    r = into(t)
    assert "changes: 0 " in r.stdout and "  boundary: left as is (existing file)" in r.stdout
    assert "note: .claude/guard.json exists; boundary left as it is (check it: client is the default for new " \
           "targets)" in r.stdout


@pytest.mark.parametrize("workflows", [
    '  "workflows": [\n    {"name": "a", "sha256": "' + "0" * 64 + '"}\n  ],\n',
    "",
    '  "workflows": [],\n  "workflows": [],\n',
    # one key on one line and another over two: the one-line count is 1, the count of keys is not
    '  "workflows": [],\n  "workflows": [\n  ],\n',
], ids=["three-lines", "missing", "twice", "one-line-and-another"])
def test_init_stops_before_any_copy_unless_workflows_is_on_one_line(tmp_path, workflows):
    # review round 2 of item #69: the check before any copy, on a kit whose guard.json holds the list otherwise
    kit = tmp_path / "kit"
    (kit / ".claude").mkdir(parents=True)
    (kit / "install.sh").write_bytes(INSTALL.read_bytes())
    (kit / ".claude/guard.json").write_text('{\n  "boundary": "own",\n' + workflows + '  "telemetry_dir": "x"\n}\n')
    t = target_repo(tmp_path, None)
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(kit / "install.sh"), "--into", str(t)], cwd=kit, env=env, text=True,
                       capture_output=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert 'expected "workflows": [...] on exactly one line' in r.stderr
    assert sorted(p.name for p in t.iterdir()) == [".git"]


def test_boundary_own_is_written_when_asked(tmp_path):
    t = target_repo(tmp_path, None)
    r = into(t, "--boundary", "own")
    assert r.returncode == 0, r.stderr
    assert boundary_of(t) == "own" and "  boundary: own (new file)" in r.stdout


@pytest.mark.parametrize("args", [["--boundary", "own"], ["--force"], ["--boundary", "client", "--force"]])
def test_an_existing_guard_json_is_never_touched(tmp_path, args):
    t = target_repo(tmp_path, None)
    (t / ".claude").mkdir()
    mine = b'{\n  "boundary": "client",\n  "protected_branches": ["trunk"]\n}\n'
    (t / ".claude/guard.json").write_bytes(mine)

    r = into(t, *args)

    assert r.returncode == 0, r.stderr
    assert (t / ".claude/guard.json").read_bytes() == mine
    assert "boundary: left as is (existing file)" in r.stdout


def test_the_skill_and_the_orchestration_tools_land_in_the_target(tmp_path):
    t = target_repo(tmp_path, None)
    assert into(t).returncode == 0
    for name in ("SKILL.md", "brief-template.md", "brief-example.md"):
        got = (t / ".claude/skills/orchestrate" / name).read_bytes()
        assert got == (ROOT / "skills/orchestrate" / name).read_bytes(), name
    for name in ("assert_run.py", "brief_lint.py"):
        assert (t / "tools/orchestration" / name).read_bytes() == (ROOT / "tools/orchestration" / name).read_bytes()
