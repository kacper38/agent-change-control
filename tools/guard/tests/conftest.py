import importlib.util
import os
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
GUARD = HERE.parent / "guard.py"
FIXTURES = HERE / "fixtures"


def _load():
    spec = importlib.util.spec_from_file_location("guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def guard():
    return _load()


@pytest.fixture(scope="session")
def guard_path():
    return str(GUARD)


@pytest.fixture(scope="session")
def fixtures():
    return FIXTURES


@pytest.fixture(autouse=True)
def _isolated_telemetry(tmp_path, monkeypatch):
    monkeypatch.setenv("KZ_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    # 0.10.0: CI's answer in a box (KZ_RULES_OFF) and in a cloud session alike; a test that needs one sets it
    for name in ("KZ_RULES_OFF", "KZ_BOUNDARY", "CLAUDE_CODE_REMOTE"):
        monkeypatch.delenv(name, raising=False)
    os.chdir(tmp_path)
