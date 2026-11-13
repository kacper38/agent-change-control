import importlib.util
import pathlib

import pytest


@pytest.fixture(scope="session")
def probe():
    src = pathlib.Path(__file__).resolve().parents[1] / "probe.py"
    spec = importlib.util.spec_from_file_location("orchestration_probe", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
