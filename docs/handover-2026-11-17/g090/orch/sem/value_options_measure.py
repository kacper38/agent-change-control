"""Measure, with the real search tools of this machine, every option the guard reads as "takes the next word".

usage: python3 -I value_options_measure.py <guard.py> <new scratch dir>

For each tool of the guard's _SEARCH_OPTIONS that is installed here (grep = the system's grep, ggrep, rg,
git grep; ag and ack when present) and each of its value options (short letters and long names), the script
runs `<tool> <option> MARKTOKEN f.txt` in a scratch folder where f.txt holds the line "MARKTOKEN here" and no
file is named MARKTOKEN. Standard input is empty. If the tool prints the line of f.txt, the option took no
word: the tool read MARKTOKEN as the pattern and searched f.txt, and the guard's reading (MARKTOKEN is the
value, f.txt the pattern) is wrong for that tool. The scratch folder is a git repository so that git grep
has a tracked file. Nothing outside the scratch folder is read or written.
"""
import importlib.util
import os
import shutil
import subprocess
import sys


def load(path):
    spec = importlib.util.spec_from_file_location("guard_measured", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(argv, cwd, env):
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=10)
    except subprocess.TimeoutExpired:
        return None, "", "timeout"
    return proc.returncode, proc.stdout, proc.stderr


def main(argv):
    guard_path, scratch = argv[0], argv[1]
    if os.path.exists(scratch):
        print(f"exists already: {scratch}")
        return 2
    guard = load(guard_path)
    os.makedirs(scratch)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": scratch, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_SYSTEM": os.devnull, "GIT_PAGER": "cat", "PAGER": "cat", "LC_ALL": "C"}
    with open(os.path.join(scratch, "f.txt"), "w", encoding="utf-8") as handle:
        handle.write("MARKTOKEN here\n")
    subprocess.run(["git", "init", "--quiet"], cwd=scratch, env=env, check=True)
    subprocess.run(["git", "add", "f.txt"], cwd=scratch, env=env, check=True)
    tools = {"grep": ["/usr/bin/grep"], "ggrep": ["ggrep"], "rg": ["rg"], "git": ["git", "grep"], "ag": ["ag"],
             "ack": ["ack"]}
    # the guard's table name for each tool here
    table_of = {"grep": "grep", "ggrep": "grep", "rg": "rg", "git": "git", "ag": "ag", "ack": "ack"}
    wrong = 0
    for tool, base in tools.items():
        table = guard._SEARCH_OPTIONS.get(table_of[tool])
        if table is None:
            print(f"== {tool}: no table in the guard")
            continue
        if shutil.which(base[0]) is None and not os.path.exists(base[0]):
            print(f"== {tool}: not installed here, not measured")
            continue
        code, out, err = run(base + ["--version"], scratch, env)
        version = (out or err).strip().splitlines()[0] if (out or err).strip() else "?"
        options = ["-" + c for c in table.value_shorts] + sorted(table.value_longs)
        flagged = []
        for opt in options:
            code, out, err = run(base + [opt, "MARKTOKEN", "f.txt"], scratch, env)
            took_no_word = "MARKTOKEN here" in out
            if took_no_word:
                flagged.append(opt)
        wrong += len(flagged)
        print(f"== {tool} ({version[:60]}): value options in the guard's table {len(options)} | "
              f"the tool takes no word after: {len(flagged)}")
        for opt in flagged:
            print(f"   {opt}")
    print(f"options the guard reads as taking the next word although the tool does not: {wrong}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
