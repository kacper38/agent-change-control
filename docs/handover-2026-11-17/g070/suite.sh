#!/bin/sh
# Run the lint and the test suites of one checkout on both CI Pythons, offline. usage: sh suite.sh <checkout> [paths…]
WT="$1"; shift
[ -d "$WT/tools/guard" ] || { echo "not a checkout: $WT"; exit 1; }
PATHS="${*:-tools}"  # the whole tree, as CI runs it (pyproject testpaths)
echo "== $(git -C "$WT" rev-parse --short HEAD) $(git -C "$WT" branch --show-current) | guard $(python3 "$WT/tools/guard/guard.py" version)"
echo "== ruff"; ruff check "$WT/tools"; echo "ruff exit $?"
for PY in 3.13 3.9; do
  echo "== pytest on Python $PY"
  START=$(date +%s)
  # shellcheck disable=SC2086
  uv run --directory "$WT" --offline --no-project --with pytest --python "$PY" python -m pytest -q -p no:cacheprovider -o addopts= $PATHS 2>&1 | tail -6
  echo "pytest $PY done in $(( $(date +%s) - START )) s"
done
