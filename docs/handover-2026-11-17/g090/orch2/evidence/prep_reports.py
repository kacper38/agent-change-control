"""Write an agent's hand-back text out as a report file, without the harness's frame around it.

usage: python3 -I prep_reports.py <out folder> <source>=<name> [<source>=<name> ...]

A hand-back file starts with one frame line of the harness (`[Subagent hand-back] ...`), in some cases followed by
a second one (`  [harness: ...`), and the agent's text stands below, indented by two blanks. This writes the text
alone: the frame lines dropped, the two blanks taken off each line, blank lines at both ends dropped, one line
break at the end. Nothing else changes. Prints one line per file.
"""
import os
import sys


def main(argv):
    out = argv[0]
    os.makedirs(out, exist_ok=True)
    for pair in argv[1:]:
        source, _, name = pair.partition("=")
        with open(source, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        if not lines[0].startswith("[Subagent hand-back]"):
            sys.exit(f"{source}: no frame line")
        lines = lines[1:]
        frames = 1
        if lines and lines[0].lstrip().startswith("[harness:"):
            lines = lines[1:]
            frames += 1
        body = [ln[2:] if ln.startswith("  ") else ln for ln in lines]
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        with open(os.path.join(out, name), "w", encoding="utf-8") as fh:
            fh.write("\n".join(body) + "\n")
        print(f"{name}: {len(body)} lines, {frames} frame line(s) dropped")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
