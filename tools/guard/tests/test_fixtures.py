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


def test_every_rule_has_a_corpus(guard):
    for name in guard.RULES:
        for harness in ("claude", "copilot"):
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
