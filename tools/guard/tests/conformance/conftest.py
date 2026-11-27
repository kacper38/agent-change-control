"""Fixtures of the conformance tests (tracker item #116). A full run takes about a minute, so the run of the
unpatched copy is made once per session and serves both files: the control of the planted breaks, and the second
case root of test_conformance.py."""
import pathlib
import shlex
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import conformance_runner as cr  # noqa: E402 (the folder is no package)

GUARD = HERE.parent.parent / "guard.py"


def _copy(folder: pathlib.Path, old: str = "", new: str = "") -> str:
    """The command line of a copy of guard.py at <folder>/tools/guard/guard.py, the depth of the real one, with
    `old` (which must stand exactly once) replaced by `new`."""
    text = GUARD.read_text(encoding="utf-8")
    if old:
        assert text.count(old) == 1, f"must stand exactly once: {old!r}"
        text = text.replace(old, new)
    target = folder / "tools" / "guard" / "guard.py"
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")
    return shlex.join([sys.executable, str(target)])


@pytest.fixture(scope="session")
def guard_copy():
    return _copy


@pytest.fixture(scope="session")
def golden():
    return cr.load_golden()


@pytest.fixture(scope="session")
def control(tmp_path_factory):
    """The answers of the unpatched copy at <tmp>/tools/guard/guard.py, from a case root of another name and depth."""
    argv = shlex.split(_copy(tmp_path_factory.mktemp("copy")))
    root = tmp_path_factory.mktemp("Second-Root") / "deeper" / "x"
    return cr.run_cases(cr.select(None), argv, root, cr.DEFAULT_JOBS)
