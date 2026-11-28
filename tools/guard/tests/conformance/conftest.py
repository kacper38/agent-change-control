"""Fixtures of the conformance tests (tracker item #116). A full run takes about a minute, so the run of the
unpatched copy is made once per session and serves both files: the control of the planted breaks, and the run
test_conformance.py compares the golden file with. The file is recorded through `python3 tools/guard/guard.py` in
place from another root; the copies start through a launcher that imports them with cached bytecode. So the one
equality covers the case root, the guard's place and the way the guard is started."""
import pathlib
import py_compile
import shlex
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import conformance_runner as cr  # noqa: E402 (the folder is no package)

GUARD = HERE.parent.parent / "guard.py"


def _copy(folder: pathlib.Path, old: str = "", new: str = "") -> str:
    """The command line of a launcher beside a copy of guard.py at <folder>/tools/guard/guard.py, the depth of the
    real one, with `old` (which must stand exactly once) replaced by `new`. A main script is compiled from source on
    every start, more than half of a call: the launcher imports the copy, compiled here once."""
    text = GUARD.read_text(encoding="utf-8")
    if old:
        assert text.count(old) == 1, f"must stand exactly once: {old!r}"
        text = text.replace(old, new)
    target = folder / "tools" / "guard" / "guard.py"
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")
    # beside the source, where the import looks without a bytecode prefix; py_compile writes under
    # PYTHONDONTWRITEBYTECODE too. Apple's 3.9 takes its prefix from HOME (the case's own), so it reads none of it
    tag = sys.implementation.cache_tag
    py_compile.compile(str(target), cfile=str(target.parent / "__pycache__" / f"guard.{tag}.pyc"), doraise=True)
    launcher = target.parent / "launch_guard.py"  # guard.py's own __main__ block, repeated (test_conformance.py)
    launcher.write_text("import sys\nimport guard\nsys.exit(guard.main(sys.argv[1:]))\n", encoding="utf-8")
    return shlex.join([sys.executable, str(launcher)])


@pytest.fixture(scope="session")
def guard_copy():
    return _copy


@pytest.fixture(scope="session")
def golden():
    return cr.load_golden()


@pytest.fixture(scope="session")
def control(tmp_path_factory):
    """The answers of the unpatched copy at <tmp>/tools/guard/guard.py, started through the launcher, from a case
    root of another name and depth."""
    argv = shlex.split(_copy(tmp_path_factory.mktemp("copy")))
    root = tmp_path_factory.mktemp("Second-Root") / "deeper" / "x"
    return cr.run_cases(cr.select(None), argv, root, cr.DEFAULT_JOBS)
