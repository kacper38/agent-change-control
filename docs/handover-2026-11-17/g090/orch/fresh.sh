#!/bin/zsh
# Run the repository's own bin/fresh-review tool for one range of the branch, without `cd`: the tool's main()
# takes the working tree as an argument. usage: zsh fresh.sh <work tree> <base> [--dry-run] [<log file>]
# The tool sends `git diff <base>...HEAD` of that work tree through the egress screen to `claude -p --model opus`
# and writes a receipt under the work tree's git dir (fresh-review/<head sha>.json). Nothing else is touched.
TREE="$1"; BASE="$2"; shift 2
EXTRA=()
LOG=""
for a in "$@"; do
  case "$a" in
    --dry-run) EXTRA+=(--dry-run) ;;
    *) LOG="$a" ;;
  esac
done
run() {
  python3 -u -c "import sys; sys.path.insert(0, sys.argv[1] + '/tools/review'); import fresh_review; sys.exit(fresh_review.main(sys.argv[3:], cwd=sys.argv[2]))" "$TREE" "$TREE" --base "$BASE" "${EXTRA[@]}"
}
if [ -n "$LOG" ]; then
  run > "$LOG" 2>&1
  code=$?
  print -r -- "exit $code" >> "$LOG"
  exit $code
fi
run
