"""install.sh in user scope (`CLAUDE_DIR`): the manifest paths around the 2026-11-01 rename;
and in repo scope (`--into`): the forge column of kit.manifest (plan step A5).

A pre-rename install left `claude-platform-setup.manifest`; the installer now writes
`agent-change-control.manifest`. These tests run the real script against a temporary
`CLAUDE_DIR` or target repo so neither `~/.claude` nor the repo is touched.
"""

from __future__ import annotations

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
])
def test_bad_arguments_are_refused_before_any_copy(tmp_path, args, message):
    t = target_repo(tmp_path, None)
    r = into(t, *args)
    assert r.returncode == 1 and message in r.stderr
    assert not (t / ".claude").exists()
