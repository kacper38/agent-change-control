"""Print, for every line number section 4 of a brief names, the name in front of it and that line of guard.py.

usage: python3 -I brief_lines.py <brief.md> <guard.py>
A name counts as found when it stands in the guard's line as a definition or an assignment.
"""
import re
import sys


def main(argv):
    with open(argv[0], encoding="utf-8") as handle:
        text = handle.read()
    section = text.split("## 4. Decided design", 1)[1].split("## 5. Steps", 1)[0]
    with open(argv[1], encoding="utf-8") as handle:
        guard = handle.read().split("\n")
    flat = " ".join(section.split())
    missing = 0
    seen = set()
    # a run of backticked names, then the numbers that belong to them: `a` and `b` (340, 349) | `c` (263) | `d` 2385
    for match in re.finditer(r"((?:`[A-Za-z_][A-Za-z0-9_]*`(?:,? and |, | )?)+)\(?(\d{3,4}(?:[,;] \d{3,4})*)\)?", flat):
        names = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", match.group(1))
        numbers = [int(n) for n in re.findall(r"\d{3,4}", match.group(2))]
        # the numbers belong to the last names of the run, in order
        for name, number in zip(names[-len(numbers):], numbers):
            if (name, number) in seen:
                continue
            seen.add((name, number))
            line = guard[number - 1] if number <= len(guard) else ""
            found = bool(re.match(rf"^(def |class )?{re.escape(name)}\b", line))
            missing += not found
            print(f"{'ok  ' if found else 'LOOK'} {name:<24} {number:>5}  {line[:90]}")
    print(f"{len(seen)} pairs, {missing} to look at")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
