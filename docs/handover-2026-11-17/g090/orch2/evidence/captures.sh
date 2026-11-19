#!/bin/zsh
# Capture lint and the suite on both Pythons into the evidence folder of guard 0.9.0, at the work tree's head.
# usage: zsh captures.sh <work tree> <capture.py> <tag>
# Each capture runs with the work tree as its working directory (capture.py does that); this shell stays put.
wt=$1
cap=$2
tag=$3
print "head $(git -C $wt rev-parse --short HEAD) | status: $(git -C $wt status --short | wc -l | tr -d ' ') lines"
python3 -I $cap $wt $tag ruff -- ruff check tools
print "ruff exit $?"
python3 -I $cap $wt $tag pytest-py313 -- uv run --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= tools
print "py313 exit $?"
python3 -I $cap $wt $tag pytest-py39 -- uv run --offline --no-project --with pytest --python 3.9 python -m pytest -q -p no:cacheprovider -o addopts= tools
print "py39 exit $?"
git -C $wt status --short
