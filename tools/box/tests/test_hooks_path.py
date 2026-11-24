"""Item #85: prepare sets core.hooksPath on the box's work clone, inside a container, when it has the hook."""
import subprocess

import pytest


def fake_prepare(box, monkeypatch, tmp_path, code=0):
    """Every step of prepare faked but the hooksPath step; returns the argv lists given to subprocess.run."""
    (tmp_path / "boxes" / "b1" / "clone" / ".git").mkdir(parents=True)
    judge = tmp_path / "judge"
    judge.mkdir()
    for name, value in (("read_pins", lambda: {}), ("probe_gate", lambda pins: None),
                        ("box_root", lambda: str(tmp_path)), ("git", lambda *a, **k: "https://github.com/o/r.git"),
                        ("token_env", lambda slug: {}), ("clean_image", lambda: "agent-box:abc"),
                        ("take_judge", lambda root: ("d" * 40, str(judge))), ("managed_settings", lambda j: {}),
                        ("check_mounts", lambda m: None), ("clone_facts", lambda i, c: {"boundary": "own"})):
        monkeypatch.setattr(box, name, value)
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, code, "", "")

    monkeypatch.setattr(box.subprocess, "run", fake_run)
    return seen


def test_prepare_sets_hooks_path_inside_the_container(box, monkeypatch, tmp_path):
    seen = fake_prepare(box, monkeypatch, tmp_path)
    box.prepare("b1", "b1")
    (argv,) = seen
    assert argv[:2] == ["docker", "run"] and "agent-box:abc" in argv
    assert f"type=bind,src={tmp_path}/boxes/b1/clone,dst=/work" in argv
    script = argv[-1]
    assert "[ -f /work/.githooks/commit-msg ]" in script and "git -C /work config core.hooksPath .githooks" in script


def test_prepare_names_the_box_when_the_step_fails(box, monkeypatch, tmp_path):
    fake_prepare(box, monkeypatch, tmp_path, code=3)
    with pytest.raises(box.BoxError, match="box b1.*exit 3"):
        box.prepare("b1", "b1")


@pytest.mark.parametrize("hook, expected", [(True, ".githooks\n"), (False, "")])
def test_the_step_sets_hooks_path_only_when_the_clone_has_the_hook(box, monkeypatch, tmp_path, hook, expected):
    seen = fake_prepare(box, monkeypatch, tmp_path / "root")
    box.prepare("b1", "b1")
    monkeypatch.undo()
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    if hook:
        (clone / ".githooks").mkdir()
        (clone / ".githooks" / "commit-msg").write_text("#!/bin/sh\n", encoding="utf-8")
    subprocess.run(["sh", "-c", seen[0][-1].replace("/work", str(clone))], check=True)
    got = subprocess.run(["git", "-C", str(clone), "config", "--get", "core.hooksPath"], capture_output=True,
                         text=True)
    assert got.stdout == expected
