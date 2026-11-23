#!/usr/bin/env bash
# The captures of item #69's evidence folder at the code head, one after the other (captures.json is written by each).
# usage: bash captures.sh <worktree>
set -u
cd "$1" || exit 2
tag=2026-11-22-review-panel-0.12.1
cap() { python3 tools/tracker/evidence_export.py capture --tag "$tag" --name "$@"; echo "$1: exit $?"; }
cap git-head -- git rev-parse HEAD
cap ruff -- uv run --offline --no-project --python 3.13 --with ruff ruff check tools
cap pytest-py313 -- uv run --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= tools
cap pytest-py39 -- uv run --offline --no-project --with pytest --python 3.9 python -m pytest -q -p no:cacheprovider -o addopts= tools
cap commit-msg -- python3 tools/commit_msg.py --range 1cacf7e..HEAD
cap git-status -- git status --short
