"""The fixture corpus: every rule, both harnesses, allow/ask/deny; the corpus must equal the generator."""
import importlib.util
import json
import os
import pathlib

import pytest

FIX = pathlib.Path(__file__).parent / "fixtures"
RULE_DIRS = sorted(d for d in FIX.iterdir() if d.is_dir() and not d.name.startswith("_"))


def _cases():
    for rule_dir in RULE_DIRS:
        for harness in ("claude", "copilot"):
            for decision in ("allow", "ask", "deny"):
                for f in sorted((rule_dir / harness / decision).glob("*.json")):
                    yield rule_dir.name, harness, decision, f


@pytest.mark.parametrize("rule,harness,decision,path", list(_cases()), ids=lambda x: getattr(x, "name", str(x)))
def test_fixture(guard, monkeypatch, rule, harness, decision, path):
    raw = json.loads(path.read_text())
    if rule == "scratch-md":  # the recorded cwd is the repository root, on any machine (in a box /work is a clone)
        root = os.path.normpath(raw["cwd"])
        monkeypatch.setattr(guard, "git_root", lambda d: root if (d + os.sep).startswith(root + os.sep) else None)
    ev = guard.Event(raw)
    assert ev.harness == harness, path
    if rule == "workflow-launch":  # 0.12.1: the files are looked up from the call's folder up; in a box the
        ev.cwd = os.getcwd()  # recorded /work/repo is below the clone, whose own workflow files are no fixture's
        for rel, text in raw["_fixture"].get("files", {}).items():
            full = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]) / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(text, encoding="utf-8")
    cfg = {**guard.load_config(os.getcwd()), **raw.get("_fixture", {}).get("config", {})}  # env -> tmp telemetry
    got = guard.RULES[rule](ev, cfg)
    if decision == "allow":
        assert got is None, f"{rule}/{harness}/{path.name}: unexpected {got}"
    else:
        assert got is not None, f"{rule}/{harness}/{path.name}: expected {decision}, got None"
        assert got[0] == decision, f"{rule}/{harness}/{path.name}: expected {decision}, got {got}"
        assert got[1], "a reason is mandatory"


# blocking cases need a real tree or prior state: see test_<rule>.py
FILESYSTEM_RULES = {"scratch-md", "protected-branch", "fan-out"}


# rules a harness has no tool for: Copilot has no Workflow tool (0.12.0, A4 of item #67)
NO_CORPUS = {("workflow-launch", "copilot")}


def test_every_rule_has_a_corpus(guard):
    for name in guard.RULES:
        for harness in ("claude", "copilot"):
            if (name, harness) in NO_CORPUS:
                assert not (FIX / name / harness).exists(), f"{name}/{harness}: listed as having no corpus"
                continue
            d = FIX / name / harness
            assert (d / "allow").exists(), f"{name}/{harness}: no allow cases"
            if name not in FILESYSTEM_RULES:
                assert (d / "ask").exists() or (d / "deny").exists(), f"{name}/{harness}: no blocking cases"


def test_corpus_matches_generator(tmp_path):
    gen = pathlib.Path(__file__).parent / "make_fixtures.py"
    spec = importlib.util.spec_from_file_location("make_fixtures", gen)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    expected = mod.generate(tmp_path)
    on_disk = {p.relative_to(FIX): p.read_text() for d in RULE_DIRS for p in d.rglob("*.json")}
    assert set(on_disk) == set(expected), "run tools/guard/tests/make_fixtures.py and commit"
    for rel, text in expected.items():
        assert on_disk[rel] == text, f"stale fixture {rel}: regenerate"
