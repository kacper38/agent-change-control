import importlib.util
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
TOOLS = HERE.parent
ADO_ENV = ("KZ_TRACKER_REPO", "KZ_TRACKER_AREA", "KZ_TRACKER_ADO_TYPE", "KZ_TRACKER_ADO_MODE", "KZ_TRACKER_BOTS",
           "SYSTEM_COLLECTIONURI", "SYSTEM_TEAMPROJECT", "BUILD_REPOSITORY_NAME", "SYSTEM_ACCESSTOKEN")


def _load(name, where=TOOLS):
    sys.path.insert(0, str(TOOLS))
    if name in sys.modules:  # one copy per module: `import tracker` in ado.py must see the fixture's classes
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, where / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def tracker():
    return _load("tracker")


@pytest.fixture(scope="session")
def label_lint():
    return _load("label_lint")


@pytest.fixture(scope="session")
def session_start():
    return _load("session_start")


@pytest.fixture(scope="session")
def ado(tracker):
    return _load("ado")


@pytest.fixture(scope="session")
def fake_ado():
    return _load("fake_ado", HERE)


@pytest.fixture
def ado_fake(ado, fake_ado, monkeypatch):
    """make(mode) -> (AdoBackend, FakeAdo): a backend on a fresh in-memory Azure DevOps, env cleared."""
    for var in ADO_ENV:
        monkeypatch.delenv(var, raising=False)

    def make(mode="tags", **fake_args):
        fake = fake_ado.FakeAdo(process=mode == "process", **fake_args)
        monkeypatch.setenv("SYSTEM_ACCESSTOKEN", fake.token)
        return ado.AdoBackend(f"{fake.org}/{fake.project}/{fake.repo}", transport=fake, mode=mode), fake

    return make
