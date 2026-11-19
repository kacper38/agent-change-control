#!/bin/zsh
# The replay of the recorded tool calls of the last days through two guard files, in both boundaries: where does
# the second answer otherwise than the first? Read-only: every recorded call is a string handed to the rule
# functions, nothing runs. The logs stay in the scratchpad; only the numbers are used (--no-text).
# usage: zsh replay-pair.sh <old guard.py> <new guard.py> <label> [<days, default 45>]
PAD=<PAD>
ORCH=$PAD/orch
S=$PAD/bc/g070
OLD="$1"; NEW="$2"; LABEL="$3"; DAYS="${4:-45}"
[ -n "$LABEL" ] || { echo "usage: zsh replay-pair.sh <old guard.py> <new guard.py> <label> [<days>]"; exit 2; }
OUT=$ORCH/out/replay-$LABEL
mkdir -p $OUT
for B in own client; do
  python3 -I $S/replay.py $OLD $NEW $DAYS --boundary $B --no-text --log $OUT/$B.jsonl > $OUT/$B.log 2> $OUT/$B.err
  echo "boundary $B: exit $? | stderr lines $(grep -c '' $OUT/$B.err)"
  grep -E '^(transcripts|tool calls|weaker|stronger|crash)' $OUT/$B.log
  sed -n '/^=== weaker per rule/,/^=== /p' $OUT/$B.log | head -n 12
  sed -n '/^=== stronger per rule/,/^=== stronger, by/p' $OUT/$B.log | head -n 12
done
