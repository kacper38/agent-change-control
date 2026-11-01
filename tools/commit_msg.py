#!/usr/bin/env python3
"""commit-msg gate: conventional subject, imperative mood, no closing keywords (plan step 3.1).

Used three ways, same rules each time:
  tools/commit_msg.py <file>                 git commit-msg hook (via .githooks/commit-msg)
  tools/commit_msg.py --range A..B           CI: every commit in the range
  tools/commit_msg.py --message "<text>"     tests, ad hoc
Rules: `type(scope)?: subject` with type in TYPES, subject <= 72 chars, lower-case start,
imperative (a short blocklist of past/gerund forms), no `Fixes #N`-style closing keywords
(also `Fixes AB#N`, the Azure Boards form) anywhere in the message (closing is the tracker
owner's protocol), trailers well-formed.
Merge, Revert, fixup! and squash! commits pass. Exit 0 ok, 1 rejected, 2 usage.
"""
import re
import subprocess
import sys

TYPES = ("feat", "fix", "docs", "chore", "refactor", "test", "ci", "build", "perf", "style", "revert")
SUBJECT_MAX = 72
_SUBJECT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^()\s]+)\))?(?P<bang>!)?: (?P<subject>\S.*)$")
# `AB#N` is the Azure Boards form a GitHub repo uses to close a work item; a bare `AB#N` only links
_CLOSING_RE = re.compile(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+(?:[\w.-]+/[\w.-]+|AB)?#\d+",
                         re.IGNORECASE)
_TRAILER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*: \S")
_SKIP_RE = re.compile(
    r"^(Merge (branch|pull request|remote-tracking branch|tag|commit) |Revert \"|fixup! |squash! |amend! )"
)
NOT_IMPERATIVE = {
    "added", "adding", "adds", "fixed", "fixing", "fixes", "updated", "updating", "updates", "changed", "changing",
    "changes", "removed", "removing", "removes", "refactored", "refactoring", "implemented", "implementing",
    "implements", "created", "creating", "creates", "deleted", "deleting", "moved", "moving", "renamed", "renaming",
    "improved", "improving", "merged", "merging", "bumped", "bumping", "cleaned", "cleaning", "reworked", "reworking",
}


_SCISSORS_RE = re.compile(r"^# -{8,} >8 -{8,}\s*$", re.MULTILINE)


def problems(message: str, allow_fixups: bool = True) -> list:
    """Problems with a commit message; accepts the raw COMMIT_EDITMSG (comments and the `git commit -v` diff cut)."""
    message = message.replace("\r\n", "\n")
    cut = _SCISSORS_RE.search(message)
    if cut:
        message = message[: cut.start()]
    lines = [ln for ln in message.split("\n") if not ln.startswith("#")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ["empty commit message"]
    subject_line = lines[0].rstrip()
    out = []
    if subject_line.startswith(("fixup! ", "squash! ", "amend! ")) and not allow_fixups:
        out.append("fixup!/squash! commits must be squashed before the PR gate")
    elif _SKIP_RE.match(subject_line):
        pass
    else:
        m = _SUBJECT_RE.match(subject_line)
        if not m:
            out.append(f"subject must be `type(scope): imperative summary`, got: {subject_line!r}")
        else:
            if m.group("type") not in TYPES:
                out.append(f"type `{m.group('type')}` not in {', '.join(TYPES)}")
            subject = m.group("subject")
            first = subject.split()[0].lower().strip(".,;:")
            if subject[0].isupper() and not subject.split()[0].isupper():
                out.append("subject starts lower-case (it is not a sentence)")
            if first in NOT_IMPERATIVE:
                out.append(f"subject reads as `{first}`; write the imperative (add, fix, remove ...)")
            if subject.endswith("."):
                out.append("no trailing period in the subject")
        if len(subject_line) > SUBJECT_MAX:
            out.append(f"subject is {len(subject_line)} chars, max {SUBJECT_MAX}")
    if len(lines) > 1 and lines[1].strip():
        out.append("one blank line between subject and body")
    kw = _CLOSING_RE.search("\n".join(lines))  # comment lines are gone, as git would strip them
    if kw:
        out.append(f"closing keyword `{kw.group(0)}` closes an issue behind the tracker; write `Refs #N`")
    body = [ln for ln in lines[1:] if ln.strip()]
    if body:
        last_block = []
        for ln in reversed(lines):
            if not ln.strip():
                if last_block:
                    break
                continue
            last_block.insert(0, ln)
        if any(ln.startswith("Co-Authored-By:") or ln.startswith("Signed-off-by:") for ln in last_block):
            for ln in last_block:
                if not _TRAILER_RE.match(ln) and not ln.startswith(" "):
                    out.append(f"trailer block mixes prose and trailers: {ln.strip()!r}")
                    break
    return out


def check_range(rng: str) -> int:
    try:
        shas = subprocess.run(["git", "rev-list", "--no-merges", rng], capture_output=True, text=True,
                              check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"commit-msg: cannot list {rng}: {exc}", file=sys.stderr)
        return 2
    bad = 0
    for sha in shas:
        r = subprocess.run(["git", "log", "-1", "--format=%B", sha], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"commit-msg: cannot read {sha[:10]}: {r.stderr.strip()}", file=sys.stderr)
            return 2
        probs = problems(r.stdout, allow_fixups=False)
        if probs:
            bad += 1
            print(f"{sha[:10]}: " + "; ".join(probs), file=sys.stderr)
    print(f"commit-msg: {len(shas)} commit(s) checked, {bad} rejected", file=sys.stderr)
    return 1 if bad else 0


def main(argv: list) -> int:
    if len(argv) == 2 and argv[0] == "--range":
        return check_range(argv[1])
    if len(argv) == 2 and argv[0] == "--message":
        message = argv[1]
    elif len(argv) == 1 and not argv[0].startswith("-"):
        try:
            with open(argv[0], encoding="utf-8") as fh:
                message = fh.read()
        except OSError as exc:
            print(f"commit-msg: {exc}", file=sys.stderr)
            return 2
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    probs = problems(message)
    for p in probs:
        print(f"commit-msg: {p}", file=sys.stderr)
    if probs:
        print("commit-msg: rejected (rules in tools/commit_msg.py; `git commit --no-verify` is denied by the guard)",
              file=sys.stderr)
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
