#!/usr/bin/env python3
"""Print the `tracker.py new` call for a tracker item that was drafted as a markdown file (item-b.md).

usage: python3 -I item_cmd.py <item.md> [--draft]

Reads the sections "Title", "Acceptance criteria" (a numbered list, one criterion per number), "Scope" (its
first paragraph, and the paragraph that starts with "Scope limit:") and "Source", and prints one shell command
with every argument quoted. It runs nothing and files nothing: the tracker is the only writer of issues, and
the call is made on a machine where the tracker works.

Without --draft it refuses a file that is still a draft: the word DRAFT in its first heading, an open mark
such as **[Q5]** anywhere, or a "[to be added" place. The item is filed after the owner's answers, not before.
"""
import re
import shlex
import sys

MARK = re.compile(r"\*\*\[[^\]]+\]\*\*|\[to be added")


def sections(text):
    """The lines under each `## ` heading, by heading."""
    out, name = {}, None
    for line in text.split("\n"):
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = []
        elif name is not None:
            out[name].append(line)
    return out


def paragraphs(lines):
    """Paragraphs of a section, each joined to one line."""
    out, current = [], []
    for line in lines + [""]:
        if line.strip():
            current.append(line.strip())
        elif current:
            out.append(" ".join(current))
            current = []
    return out


def criteria(lines):
    """The items of a numbered list, each joined to one line, without its number."""
    out = []
    for line in lines:
        start = re.match(r"^(\d+)\. (.*)$", line)
        if start:
            out.append(start.group(2).strip())
        elif line.strip() and out and line.startswith(" "):
            out[-1] += " " + line.strip()
    return out


def main(argv):
    draft = "--draft" in argv
    args = [a for a in argv if a != "--draft"]
    if len(args) != 1:
        sys.exit(__doc__.strip().split("\n\n")[1])
    with open(args[0], encoding="utf-8") as handle:
        text = handle.read()
    first = text.split("\n", 1)[0]
    open_places = sorted(set(MARK.findall(text)))
    if not draft and ("DRAFT" in first.upper() or open_places):
        print("this file is still a draft; it is filed after the owner's answers", file=sys.stderr)
        for place in open_places:
            print("  open:", place, file=sys.stderr)
        return 1
    parts = sections(text)
    missing = [name for name in ("Title", "Acceptance criteria", "Scope", "Source") if name not in parts]
    if missing:
        sys.exit(f"missing section: {', '.join(missing)}")
    title = " ".join(paragraphs(parts["Title"]))
    acs = criteria(parts["Acceptance criteria"])
    scope_paragraphs = paragraphs(parts["Scope"])
    limits = [p[len("Scope limit:"):].strip() for p in scope_paragraphs if p.startswith("Scope limit:")]
    scope = [p for p in scope_paragraphs if not p.startswith("Scope limit:")]
    source = " ".join(paragraphs(parts["Source"]))
    if not (title and acs and scope and len(limits) == 1 and source):
        sys.exit("the title, at least one criterion, the scope, one scope limit and the source are needed")
    argv_out = ["python3", "tools/tracker/tracker.py", "new", "--title", title]
    for criterion in acs:
        argv_out += ["--ac", criterion]
    argv_out += ["--scope", scope[0], "--scope-limit", limits[0], "--source", source]
    print(shlex.join(argv_out))
    print(f"# {len(acs)} criteria, title {len(title)} characters" + (" | DRAFT: do not file" if draft else ""),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
