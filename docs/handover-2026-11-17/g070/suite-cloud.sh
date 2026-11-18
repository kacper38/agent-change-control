#!/bin/sh
# Lint, a static Python 3.9 check and the test suite of one checkout, offline, for a cloud container that has
# Python 3.13 only. The 3.9 run of g070/suite.sh needs a machine with a 3.9 interpreter.
# usage: sh suite-cloud.sh <checkout> [paths…]
WT="$1"; shift
[ -d "$WT/tools/guard" ] || { echo "not a checkout: $WT"; exit 1; }
PATHS="${*:-tools}"  # the whole tree, as CI runs it (pyproject testpaths)
HERE="$(dirname "$0")"
echo "== $(git -C "$WT" rev-parse --short HEAD) $(git -C "$WT" branch --show-current) | guard $(python3 "$WT/tools/guard/guard.py" version)"
echo "== ruff"; ruff check "$WT/tools"; echo "ruff exit $?"
echo "== Python 3.9, static (grammar and a list of later names; not a run)"
python3 -I "$HERE/py39_check.py" "$WT/tools"; echo "py39 check exit $?"
echo "== pytest on Python 3.13"
START=$(date +%s)
# shellcheck disable=SC2086
uv run --directory "$WT" --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= $PATHS 2>&1 | grep -v UV_NATIVE_TLS | tail -6
echo "pytest 3.13 done in $(( $(date +%s) - START )) s"
echo "== pytest on Python 3.9: NOT RUN (no 3.9 interpreter on this machine)"
