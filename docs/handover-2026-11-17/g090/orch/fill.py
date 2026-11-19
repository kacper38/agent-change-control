"""Fill the engineer brief and the after-build script of groups B and C for this machine.

usage: python3 -I fill.py <passed> <skipped>

Reads the package from the handover worktree (never changed) and writes the filled copies outside the
repository: the brief into the engineer's scratch folder, the after-build script into the orchestrating
session's folder. The two figures are the baseline of the suite measured in the fresh worktree. Exit 1 when a
text that was to be replaced is missing or a placeholder is left.
"""
import os
import sys

MAIN = "<MAIN>"
HK = MAIN + "/.claude/worktrees/handover-1117/docs/handover-2026-11-17"
PAD = "<PAD>"
SP = PAD + "/bc"
ORCH = PAD + "/orch"
WT = MAIN + "/.claude/worktrees/g090-bc"
BASE = "769b9d2"
ITEM = "#57"


def swap(text, old, new, count=None):
    """Replace old by new; the text must hold it (count times when given)."""
    found = text.count(old)
    if not found or (count is not None and found != count):
        sys.exit(f"expected {count or 'at least one'} of {old[:70]!r}, found {found}")
    return text.replace(old, new)


def brief(passed, skipped):
    with open(HK + "/g080/brief-b.md", encoding="utf-8") as handle:
        text = handle.read()
    text = swap(
        text,
        "**Not to be handed to an engineer before two things are done.** The tracker item exists and the owner has run\n"
        "`owner ready`; and the orchestrating session has filled the item number (`#NN`), the paths (`<REPO>`,\n"
        "`<SCRATCH>`) and the commit the worktree starts from (`<BASE>`), and has struck this box.",
        "Filled in by the orchestrating session on 2026-11-18: the tracker item is " + ITEM + " (the owner's `owner ready` of\n"
        "17:19 UTC; claimed for the branch `feat/guard-0.9.0`), the paths stand below as they are on this machine, and\n"
        "the worktree starts from `" + BASE + "`.", 1)
    text = swap(
        text,
        "- Baseline, measured on the owner's machine on 2026-11-18 at `ec23d5d` (guard 0.8.0): `5271 passed, 9 skipped`\n"
        "  on Python 3.13 and on Python 3.9; `ruff` clean. The session measures again when `<BASE>` is a later commit.",
        "- Baseline, measured in this worktree on 2026-11-18 at `" + BASE + "` (guard 0.8.0; `tools/` is the same as at\n"
        "  `ec23d5d`): `" + passed + " passed, " + skipped + " skipped` on Python 3.13 and on Python 3.9; `ruff` clean.", 1)
    text = swap(text, "#NN", ITEM)
    text = swap(text, "<WT>", WT)
    text = swap(text, "<REPO>", MAIN)
    text = swap(text, "<SCRATCH>", SP)
    text = swap(text, "<BASE>", BASE)
    for left in ("#NN", "<REPO>", "<SCRATCH>", "<BASE>", "<WT>"):
        if left in text:
            sys.exit(f"left in the brief: {left}")
    with open(SP + "/g080/brief-b.md", "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"brief written: {SP}/g080/brief-b.md ({len(text.splitlines())} lines)")


def after_build():
    with open(HK + "/g080-heldout/b_after_build.sh", encoding="utf-8") as handle:
        text = handle.read()
    text = swap(text, "SP=<SCRATCH>\n", "SP=" + SP + "\nORCH=" + ORCH + "\n", 1)
    text = swap(text, "H=$SP/g080-heldout\n", "H=" + HK + "/g080-heldout   # read from the handover worktree, never copied\n", 1)
    text = swap(text, "MAIN=<REPO>\n", "MAIN=" + MAIN + "\n", 1)
    text = swap(text, "BASE=<BASE> ", "BASE=" + BASE + " ", 1)
    text = swap(text, "OLD=$H/guard-0.8.0.py ", "OLD=$ORCH/ref/guard-0.8.0.py ", 1)
    text = swap(text, "OUT=$H/after-b\n", "OUT=$ORCH/after-b\n", 1)
    for left in ("<REPO>", "<SCRATCH>", "<BASE>"):
        if left in text:
            sys.exit(f"left in the script: {left}")
    path = ORCH + "/b_after_build.sh"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"script written: {path}")


def main(argv):
    if len(argv) != 2 or not all(a.isdigit() for a in argv):
        sys.exit(__doc__)
    os.makedirs(SP + "/g080/eng", exist_ok=True)
    brief(argv[0], argv[1])
    after_build()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
