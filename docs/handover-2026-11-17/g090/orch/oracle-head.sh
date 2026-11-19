#!/bin/zsh
# The enumerating check of the quiet-report reading (sem/quiet_enum.py) over its whole product of lines, for one
# guard file, in several processes side by side. Every line is judged by rule_secret_shell as a string; only the
# lines the guard is silent on are run, in zsh and bash, against a stand-in file in a scratch folder per process.
# usage: zsh oracle-head.sh <guard.py> <label> [<processes, default 12>]
#        writes sem/oracle-<label>/s<i>.log and s<i>.json, then prints the sums
PAD=<PAD>
ORCH=$PAD/orch
GUARD="$1"; LABEL="$2"; N="${3:-12}"
[ -n "$LABEL" ] || { echo "usage: zsh oracle-head.sh <guard.py> <label> [<processes>]"; exit 2; }
OUT=$ORCH/sem/oracle-$LABEL
mkdir -p $OUT
i=0
while [ $i -lt $N ]; do
  python3 -u -I $ORCH/sem/quiet_enum.py $OUT/run$i "$GUARD" --shard $i/$N --max-run 1000000 --show 10 \
    --out $OUT/s$i.json > $OUT/s$i.log 2>&1 &
  i=$((i + 1))
done
wait
python3 -I $ORCH/sem/oracle_sum.py $OUT $N
