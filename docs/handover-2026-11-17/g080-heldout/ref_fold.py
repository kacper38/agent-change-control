#!/usr/bin/env python3
"""Reference of the decided design for names in capitals, laid over a guard file without changing it:
`fold_names` plus "judge the command twice", and the host expression made case-insensitive. Used to check
that the rows can be reached by that design, and later as a second opinion on the engineer's build.
Commands are strings handed to rule functions; nothing runs.

usage: python3 -I ref_fold.py <guard.py> <rows file> [<rows file> ...] [--red] [--plain]
  --plain   judge with the guard as it is (no overlay): for a side-by-side
"""
import copy
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECT = os.path.join(os.path.dirname(HERE), "g080", "expect.py")

TABLES = """_WRAPPERS _RM_CLASS _DELETE_TOOLS _WRITERS_LAST _WRITERS_ALL _SEARCH_TOOLS _DEPLOY_TABLE _OTHER_LLM_CLIS
_HI_TABLE _HI_PAIRS _HI_SELF_FETCH _HI_PAIRS_ONLY _HI_BARE _HI_SHELLS _HI_DOWNLOADERS _HI_WRAPPERS _HI_REMOTE _NC_SHELLS _NC_WRAPPERS
_NC_SUB_WRAPPERS _NC_OPTION_RUNNERS _NC_SCRIPT_OPTIONS _NC_FD _NC_SCRIPT_WORDS _NC_ELSEWHERE""".split()
LITERAL = """git gh sed az aws ansible-playbook eval node ruby perl python python3 source find command coproc curl
wget http https xh tracker tracker.py rm rmdir unlink trash shred truncate sudo env exec time nohup doas xargs
parallel mise npm pnpm yarn brew pip pip3 cargo docker kubectl helm dropdb prisma rclone rsync bun deno bash sh
zsh tsx ts-node php psql mysql mariadb cqlsh snowsql duckdb cockroach hbase clickhouse cat echo printf""".split()
SHELL_RULES = ["delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
               "tracker-guard", "host-install"]
RUN_RE = re.compile(r"[^\s;|&()<>`]+")
LOOK_THROUGH = str.maketrans("", "", "'\"\\")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def known_names(g):
    names = set(LITERAL)
    for t in TABLES:
        names.update(k for k in getattr(g, t, ()) if isinstance(k, str))
    return frozenset(n for n in names if n == n.lower())


def make_fold(g, known):
    def is_name(low):
        return low in known or bool(g._PIP_RE.match(low)) or bool(g._PYTHON_RE.match(low))

    def one(m):
        run = m.group(0)
        head, slash, last = run.rpartition("/")
        bare = last.translate(LOOK_THROUGH)
        low = bare.lower()
        if bare != low and not is_name(bare) and is_name(low):
            return head + slash + last.lower()
        return run

    return lambda text: RUN_RE.sub(one, text)


def overlay(g):
    """Lay the design over the loaded module: hosts whatever the case, each shell rule judged twice."""
    g._LLM_HOSTS_RE = re.compile(g._LLM_HOSTS_RE.pattern, re.IGNORECASE)
    as_written = g.secret_class

    def secret_class(path):
        """The class of the path as written, or else of the path in lower case."""
        cls = as_written(path)
        if cls is None and path and path != path.lower():
            cls = as_written(path.lower())
        return cls

    g.secret_class = secret_class
    fold = make_fold(g, known_names(g))

    def twice(rule):
        def wrapped(ev, cfg):
            first = rule(ev, cfg)
            if (first and first[0] == "deny") or not ev.command:
                return first
            folded = fold(ev.command)
            if folded == ev.command:
                return first
            ev2 = copy.copy(ev)
            ev2.command = folded
            return g.combine([d for d in (first, rule(ev2, cfg)) if d])
        return wrapped

    for r in SHELL_RULES:
        g.RULES[r] = twice(g.RULES[r])
    return fold


def is_file_rows(path):
    """True when the rows of the file name a file tool in their second field (the format of expect_files.py)."""
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip() and not ln.startswith("#"):
                return ln.split(" | ")[1].strip() in ("Read", "Write", "Edit")
    return False


def main(argv):
    only_red = "--red" in argv
    plain = "--plain" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    expect = load(EXPECT, "expect_helper")
    g = expect.load(args[0])
    if not plain:
        overlay(g)
    files = load(os.path.join(os.path.dirname(EXPECT), "expect_files.py"), "expect_files_helper")
    per = {}
    red = total = 0
    for path in args[1:]:
        if is_file_rows(path):
            for rid, tool, rule, expected, target in files.rows_of(path):
                got = files.answer(g, tool, rule, target)
                c = per.setdefault(rid, [0, 0])
                c[0] += 1
                c[1] += got == expected
                total += 1
                if got != expected:
                    red += 1
                    print(f"RED {rid} {tool} {rule} expected {expected}, got {got} | {target}")
            continue
        for rid, branch, boundary, rule, expected, command in expect.rows_of(path):
            got = expect.answer(g, branch, boundary, rule, command)
            ok = all(v == expected for v in got.values())
            c = per.setdefault(rid, [0, 0])
            c[0] += 1
            c[1] += ok
            total += 1
            if not ok:
                red += 1
                shown = ", ".join(f"{k}={v}" for k, v in got.items() if v != expected)
                print(f"RED {rid} [{branch}@{boundary}] {rule} expected {expected}, got {shown} | {command!r}"[:230])
    if not only_red:
        for rid, (n, ok) in sorted(per.items()):
            print(f"{rid}: rows {n} | hold {ok} | red {n - ok}")
    print(f"guard {g.VERSION} {'as it is' if plain else 'with the reference overlay'}")
    print(f"total rows {total} | hold {total - red} | red {red}")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
