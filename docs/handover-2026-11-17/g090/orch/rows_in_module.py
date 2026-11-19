"""Compare the row tables inside the test module with the frozen row files, and the frozen files with the
hashes of criterion 14.

usage: python3 -I rows_in_module.py <test_table_forms.py> <dir with the rows-*.txt files>

Read-only. The module is parsed with ast (nothing is imported or run). A row line is a line that is not blank
and does not start with `#`. Exit 1 when a table differs from its file or a file's hash is not the frozen one.
"""
import ast
import hashlib
import sys
from pathlib import Path

PAIRS = (("ROWS_B", "rows-b.txt", 298, "2838db90cdeb3391"),
         ("ROWS_B4", "rows-b4.txt", 255, "79070141a5c27b03"),
         ("ROWS_B4_AZ", "rows-b4-az.txt", 123, "0954f87caef58d0f"),
         ("ROWS_B5", "rows-b5.txt", 119, "060edafbc1898915"),
         ("ROWS_C", "rows-c.txt", 173, "2ddadbf963c73eb3"),
         ("FILE_ROWS", "rows-b5-files.txt", 36, "ebc9fff2cb9de6d3"),
         # the rows of the fix pass of 2026-11-18 (not part of criterion 14; frozen by the orchestrating session)
         ("ROWS_FIX", "rows-b-fix.txt", 267, "a2e1363d65484888"),
         # addendum 1 of the fix pass (the option an unknown flag was taken for)
         ("ROWS_FIX_ADD", "rows-b-fix-add.txt", 28, "407c998b30ca2663"),
         # addendum 2 (a report handed on behind a descriptor duplication)
         ("ROWS_FIX_ADD2", "rows-b-fix-add2.txt", 31, "41b69782e81720b2"),
         ("ROWS_FIX_ADD3", "rows-b-fix-add3.txt", 14, "720eb45b5d729579"),
         ("ROWS_FIX_ADD4", "rows-b-fix-add4.txt", 22, "7005cb3f69eb06c8"),
         ("ROWS_FIX_ADD5", "rows-b-fix-add5.txt", 9, "34eb33a2c043aa4e"),
         # the rows of the second fix round (the quiet-report check fails closed, the pipe into a shell, the hook
         # switch, the API host with a port, httpie's standard input)
         ("ROWS_FIX2", "rows-b-fix2.txt", 188, "37603ad98d9ca4ec"),
         # the addendum of the second round (the ask for a pipe the guard cannot read no longer ends the read, a
         # GraphQL body through httpie and wget, a redirect target behind a continuation)
         ("ROWS_FIX2_ADD", "rows-b-fix2-add.txt", 146, "afdd2104d0fa454b"),
         # the rows of the review fixes (planted breaks in the code of the second round that no test caught)
         ("ROWS_FIX3", "rows-b-fix3.txt", 40, "94cda24ce6136349"),
         # the rows of the fourth fix round (a group zsh closes at a `}` that is no first word)
         ("ROWS_FIX4", "rows-b-fix4.txt", 48, "1417d05a6bd5b4c2"),
         # the rows of the fifth fix round (the quiet check reads a line strictly)
         ("ROWS_FIX5", "rows-b-fix5.txt", 151, "fd787495c91c7c21"),
         # the rows of the sixth fix round (a quiet report is a command the check is certain about)
         ("ROWS_FIX6", "rows-b-fix6.txt", 97, "794da92a26eda33e"),
         # the rows of the seventh fix round (a git report hands its output to no pager for certain)
         ("ROWS_FIX7", "rows-b-fix7.txt", 59, "730fff493e5464ac"),
         # the rows of the eighth fix round (a git report is quiet only when nothing else on the line can set
         # what git reads)
         ("ROWS_FIX8", "rows-b-fix8.txt", 89, "30da652dfb66cc98"),
         # the rows added to the eighth round after its review (the bracket forms beside a git report: pins)
         ("ROWS_FIX8_ADD", "rows-b-fix8-add.txt", 25, "d1e1e17ffb255f5d"),
         # two lines of the seventh round whose rows the eighth round holds by itself (planted breaks at 8f0a893)
         ("ROWS_FIX7_ADD", "rows-b-fix7-add.txt", 8, "4e8c4433a41fa370"))


def row_lines(text):
    return [line.rstrip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def main(argv):
    module, folder = Path(argv[0]), Path(argv[1])
    tables = {}
    for node in ast.parse(module.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                tables[node.targets[0].id] = node.value.value
    bad = 0
    for name, file_name, count, digest in PAIRS:
        raw = (folder / file_name).read_bytes()
        got_digest = hashlib.sha256(raw).hexdigest()[:16]
        frozen = row_lines(raw.decode("utf-8"))
        inside = row_lines(tables.get(name, ""))
        same = frozen == inside
        same_set = sorted(frozen) == sorted(inside)
        hash_ok = got_digest == digest
        count_ok = len(frozen) == count
        if not (same and hash_ok and count_ok):
            bad += 1
        print(f"{file_name:20} sha256 {got_digest} {'frozen' if hash_ok else 'NOT THE FROZEN HASH ' + digest} | "
              f"rows in file {len(frozen)} ({'as frozen' if count_ok else 'frozen count is ' + str(count)}) | "
              f"rows in {name} {len(inside)} | {'same lines, same order' if same else ('same lines, other order' if same_set else 'DIFFERENT')}")
        if not same_set:
            only_file = [line for line in frozen if line not in set(inside)]
            only_module = [line for line in inside if line not in set(frozen)]
            for line in only_file[:8]:
                print("   only in the file:   " + line[:200])
            for line in only_module[:8]:
                print("   only in the module: " + line[:200])
    extra = sorted(set(tables) - {pair[0] for pair in PAIRS})
    print("other string tables in the module: " + (", ".join(extra) if extra else "none"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
