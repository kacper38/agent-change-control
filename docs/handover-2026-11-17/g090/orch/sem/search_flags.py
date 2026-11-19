"""List every option of the search tools installed here, split into flags and options that take a value, and
write two probe lists for the guard: a flag in front of a pattern and a secret file, and a secret file name as
the value of an option.

usage: python3 -I search_flags.py <out folder>

Runs only the tools' own help (`rg --help`, `ggrep --help`, `git grep -h`, `man grep`); nothing else. Writes
  flags-probe.txt   <tool> <flag> TOKEN .env          the tool reads .env: the guard must ask
  values-probe.txt  <tool> <option> .env TOKEN src    the value is a path or unknown: the guard must ask
  options.tsv       tool, option, kind (flag | value | optional value), the help line it was read from
"""
import os
import re
import subprocess
import sys


def run(argv):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as err:
        return f"(could not run: {err})"
    return done.stdout + "\n" + done.stderr


def options_of(text, style):
    """(option, kind, line) per option named in a help text."""
    out = []
    for line in text.splitlines():
        head = line.strip()
        if not head.startswith("-"):
            continue
        if style == "rg":
            if not re.match(r"^ {4}-", line):
                continue
            spec = head
        else:
            # GNU grep and git: the options stand before two or more blanks and the description
            spec = re.split(r"\s{2,}", head, maxsplit=1)[0]
        for part in spec.split(","):
            part = part.strip()
            if not part.startswith("-"):
                continue
            m = re.match(r"^(--?(?:\[no-\])?[A-Za-z0-9][A-Za-z0-9-]*)(.*)$", part)
            if not m:
                continue
            name, rest = m.group(1), m.group(2)
            if rest.startswith("[="):
                kind = "optional value"
            elif rest.startswith("=") or rest.strip().startswith("<") or re.match(r"^ +[A-Z<]", rest):
                kind = "value"
            elif rest.strip() == "":
                kind = "flag"
            else:
                kind = "value" if rest.strip() else "flag"
            names = [name.replace("[no-]", ""), name.replace("[no-]", "no-")] if "[no-]" in name else [name]
            for one in names:
                out.append((one, kind, head[:110]))
    return out


def main(argv):
    folder = argv[0]
    os.makedirs(folder, exist_ok=True)
    sources = (("rg", ["rg", "--help"], "rg"),
               ("ggrep", ["ggrep", "--help"], "gnu"),
               ("git grep", ["git", "grep", "-h"], "gnu"))
    rows = []
    for tool, call, style in sources:
        seen = {}
        for name, kind, line in options_of(run(call), style):
            # one option may stand twice (short and long on one line share the kind of the long one)
            if name not in seen:
                seen[name] = (kind, line)
        # a short option listed beside a long one that takes a value takes that value too
        for name, (kind, line) in list(seen.items()):
            if not name.startswith("--"):
                partner = [k for k, (kk, ll) in seen.items() if ll == line and k.startswith("--")]
                if partner and seen[partner[0]][0] != kind:
                    seen[name] = (seen[partner[0]][0], line)
        for name, (kind, line) in seen.items():
            rows.append((tool, name, kind, line))
    flags, values = [], []
    for tool, name, kind, _line in rows:
        if kind == "flag":
            flags.append(f"{tool} {name} TOKEN .env")
        else:
            values.append(f"{tool} {name} .env TOKEN src")
            if kind == "optional value":
                flags.append(f"{tool} {name} TOKEN .env")
    with open(os.path.join(folder, "flags-probe.txt"), "w", encoding="utf-8") as handle:
        handle.write("# a flag of the tool's own help in front of a pattern and a secret file: the file is read\n")
        handle.write("\n".join(flags) + "\n")
    with open(os.path.join(folder, "values-probe.txt"), "w", encoding="utf-8") as handle:
        handle.write("# a secret file name as the value of an option of the tool's own help\n")
        handle.write("\n".join(values) + "\n")
    with open(os.path.join(folder, "options.tsv"), "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write("\t".join(row) + "\n")
    per = {}
    for tool, _name, kind, _line in rows:
        per.setdefault(tool, {}).setdefault(kind, 0)
        per[tool][kind] += 1
    for tool, kinds in per.items():
        print(tool, kinds)
    print(f"flag probes {len(flags)} | value probes {len(values)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
