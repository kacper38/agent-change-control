"""Fill the review brief for groups B and C: item number, paths, the build facts and what is checked already.

usage: python3 -I fill_review.py <template brief-b-review.md> <insert.md> <scratch g080 dir> <repo> <out.md>

Strikes the three head lines the template says to strike, replaces the two path lines and the FILL line, and
puts the insert in front of the section "How to test a candidate". Fails when a line it expects is missing.
"""
import sys
from pathlib import Path


def main(argv):
    template, insert, s8, repo, out = (Path(a) for a in argv[:5])
    text = template.read_text(encoding="utf-8")
    head = ("Written with `brief-b.md`; the owner's answers of 2026-11-18 are worked in. Before it is handed to a reviewer\n"
            "the orchestrating session fills the item number, the paths and the part marked FILL AFTER THE BUILD, and\n"
            "strikes these three lines.\n\n")
    swaps = [
        ("(tracker item #NN)", "(tracker item #57)"),
        (head, ""),
        ("`<S8>` = <SCRATCH>/g080", f"`<S8>` = {s8}"),
        ("`<WT>` = <REPO>/.claude/worktrees/g090-bc", f"`<WT>` = {repo}/.claude/worktrees/g090-bc"),
        ("FILL AFTER THE BUILD: the commit list, the diff files under `<S8>/review/`, the checks already run.\n",
         "The commit list, the diff and what is checked already: the three sections in front of \"How to test a\n"
         "candidate\".\n"),
    ]
    for old, new in swaps:
        if text.count(old) != 1:
            sys.exit(f"expected once, found {text.count(old)} times: {old[:60]!r}")
        text = text.replace(old, new)
    mark = "## How to test a candidate\n"
    if text.count(mark) != 1:
        sys.exit("the section 'How to test a candidate' is not there once")
    text = text.replace(mark, insert.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + mark)
    for left in ("#NN", "<SCRATCH>", "<REPO>", "FILL AFTER"):
        if left in text:
            sys.exit(f"still in the text: {left}")
    out.write_text(text, encoding="utf-8")
    print(f"written: {out} | lines {len(text.splitlines())} | words {len(text.split())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
