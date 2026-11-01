"""install.sh in user scope (`CLAUDE_DIR`): the manifest paths around the 2026-11-01 rename.

A pre-rename install left `claude-platform-setup.manifest`; the installer now writes
`agent-change-control.manifest`. These tests run the real script against a temporary
`CLAUDE_DIR` so neither `~/.claude` nor the repo is touched.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

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
