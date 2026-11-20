import importlib.util
import pathlib

import pytest

BOX = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"box_{name}", BOX / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def box_dir():
    return BOX


@pytest.fixture(scope="session")
def firewall():
    return _load("firewall")


@pytest.fixture(scope="session")
def marker():
    return _load("marker")


@pytest.fixture(scope="session")
def box():
    return _load("box")


@pytest.fixture(scope="session")
def probe():
    return _load("box_probe")
