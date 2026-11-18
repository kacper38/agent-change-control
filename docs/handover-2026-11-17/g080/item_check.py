"""Check the item text of groups B and C (item-b.md) against the row files it names, on a given guard.

usage: python3 -I item_check.py <kit folder (docs/handover-2026-11-17)> <guard.py>

For every file in the item's table: the row count, the first 16 characters of the sha256 and (for the row
files) the red and hold counts measured now with expect.py or expect_files.py are compared with the table,
and with the figures criterion 14 names. Then the texts of the package are searched for open marks, as
item_cmd.py defines them. Commands are data handed to rule functions; nothing runs. Exit 1 when something
differs. Before the build the guard is 0.8.0, the one the item's figures were measured on.
"""
import hashlib
import os
import re
import subprocess
import sys


def measured(kit, guard, rel):
    """(rows, hold, red) from the checker's last line for one row file."""
    tool = "expect_files.py" if rel.endswith("-files.txt") else "expect.py"
    out = subprocess.run([sys.executable, "-I", os.path.join(kit, "g080", tool), guard, os.path.join(kit, rel)],
                         capture_output=True, text=True, check=False).stdout
    last = [ln for ln in out.splitlines() if ln.startswith("total rows")][-1]
    rows, hold, red = (int(n) for n in re.findall(r"\d+", last))
    return rows, hold, red


def main(argv):
    kit, guard = argv[0], argv[1]
    with open(os.path.join(kit, "g080", "item-b.md"), encoding="utf-8") as handle:
        item = handle.read()
    bad = 0
    shell_rows = file_rows = red_sum = hold_sum = 0
    criterion = re.search(r"^14\. .*?(?=^15\. )", item, re.S | re.M).group(0)
    for line in item.splitlines():
        cell = [c.strip() for c in line.split("|")]
        if len(cell) < 7 or not cell[1].startswith("`g080"):
            continue
        rel = cell[1].strip("`")
        path = os.path.join(kit, rel)
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()[:16]
        with open(path, encoding="utf-8") as handle:
            rows = sum(1 for ln in handle if re.match(r"^[A-Za-z0-9]+ \| ", ln))
        notes = []
        if str(rows) != cell[2]:
            notes.append(f"rows {rows} != table {cell[2]}")
        if digest != cell[5].strip("`"):
            notes.append(f"sha {digest} != table {cell[5]}")
        if cell[3]:  # a row file: red and hold are named
            m_rows, m_hold, m_red = measured(kit, guard, rel)
            if (str(m_rows), str(m_red), str(m_hold)) != (cell[2], cell[3], cell[4]):
                notes.append(f"measured rows {m_rows} red {m_red} hold {m_hold} != table {' '.join(cell[2:5])}")
            name = os.path.basename(rel)
            if f"`{name}` {rows} `{digest}`" not in " ".join(criterion.split()):
                notes.append("criterion 14 names another count or hash")
            if rel.endswith("-files.txt"):
                file_rows += m_rows
            else:
                shell_rows += m_rows
            red_sum += m_red
            hold_sum += m_hold
        bad += bool(notes)
        print(f"{'DIFF' if notes else 'ok  '} {rel:<34} rows {rows:>4} sha {digest} {'; '.join(notes)}")
    flat = " ".join(item.split())
    total = f"{shell_rows} shell rows and {file_rows} file rows, {red_sum} of them red at 0.8.0"
    for want in (f"{total} and {hold_sum} that held", f"Together: {total}"):
        found = want in flat
        bad += not found
        print(f"{'ok  ' if found else 'DIFF'} the item says: {want}")
    marks = re.compile(r"\*\*\[[^\]]+\]\*\*|\[to be added|DRAFT")
    for rel in ("g080/item-b.md", "g080/brief-b.md", "g080/brief-b-review.md", "g080/rows-b.txt",
                "g080/rows-b4.txt", "g080/rows-b4-az.txt", "g080/rows-b5.txt", "g080/rows-b5-files.txt",
                "g080/rows-c.txt", "g080-heldout/heldout-b.txt", "g080-heldout/heldout-b4.txt",
                "g080-heldout/heldout-b5.txt", "g080-heldout/heldout-c.txt", "g080-heldout/b_after_build.sh"):
        with open(os.path.join(kit, rel), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if marks.search(line):
                    bad += 1
                    print(f"MARK {rel}:{number}: {line.strip()[:150]}")
    print("all consistent" if not bad else f"{bad} place(s) to look at")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
