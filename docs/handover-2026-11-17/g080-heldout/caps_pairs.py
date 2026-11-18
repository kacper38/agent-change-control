#!/usr/bin/env python3
"""Unseen check for names in capitals: take every command of the given rows files, write its tool names in
capitals by rule, and require that no shell rule answers the capitals form more weakly than the plain form.
No expected verdicts are needed: the plain form under the same guard is the yardstick.
Commands are strings handed to rule functions; nothing runs.

usage: python3 -I caps_pairs.py <guard.py> <rows file> [<rows file> ...] [--show N] [--names-from <guard.py>]

Variants of a command (each only when it differs from the plain form):
  first   the first command word in capitals (assignments in front are skipped)
  title   the same word with only its first letter in capitals
  all     every word that is a known tool name, in capitals (names from the reference list, built on the guard
          given with --names-from, default the guard under test)
A word is a run of characters other than white space ; | & ( ) < > and the backtick; only the part after its
last slash changes. Words with `$`, `=`, a leading `-` or no letter are left alone.
Prints the pairs where the capitals form is weaker, grouped by the plain word, and counts.
Exit 1 when a pair is weaker.
"""
import collections
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RANK = {"silent": 0, "ask": 1, "deny": 2}
RUN_RE = re.compile(r"[^\s;|&()<>`]+")
LOOK_THROUGH = str.maketrans("", "", "'\"\\")
# shell builtins and reserved words: in capitals they are not found, so a weaker verdict is correct there
NOT_ON_PATH = frozenset("""export eval exec source builtin trap coproc noglob nocorrect set unset alias declare
typeset local readonly cd if then else elif fi for while until do done case esac function select in""".split())


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def changeable(run):
    """The bare last path component of a run when the variant rules may change it, else None."""
    last = run.rpartition("/")[2]
    bare = last.translate(LOOK_THROUGH)
    if not bare or bare.startswith("-") or "$" in run or "=" in run or not any(c.isalpha() for c in bare):
        return None
    return bare


def recase(run, how):
    head, slash, last = run.rpartition("/")
    if how == "upper":
        return head + slash + last.upper()
    for i, c in enumerate(last):  # title: the first letter only
        if c.isalpha():
            return head + slash + last[:i] + c.upper() + last[i + 1 :]
    return run


def variants(command, known):
    out = []
    first = None
    for m in RUN_RE.finditer(command):
        if changeable(m.group(0)) is not None and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", m.group(0)):
            first = m
            break
    if first is not None:
        word = changeable(first.group(0)).lower()
        for label, how in (("first", "upper"), ("title", "title")):
            v = command[: first.start()] + recase(first.group(0), how) + command[first.end() :]
            if v != command:
                out.append((label, word, v))

    def every(m):
        bare = changeable(m.group(0))
        return recase(m.group(0), "upper") if bare is not None and bare.lower() in known and bare == bare.lower() else m.group(0)

    v = RUN_RE.sub(every, command)
    if v != command and all(v != o[2] for o in out):
        out.append(("all", "(every known name)", v))
    return out


def main(argv):
    show, names_from, args = 60, None, []
    it = iter(argv[1:])
    for a in it:
        if a == "--show":
            show = int(next(it))
        elif a == "--names-from":
            names_from = next(it)
        else:
            args.append(a)
    expect = load(os.path.join(os.path.dirname(HERE), "g080", "expect.py"), "expect_helper")
    ref = load(os.path.join(HERE, "ref_fold.py"), "ref_fold_helper")
    g = expect.load(args[0])
    known = ref.known_names(load(names_from, "names_guard") if names_from else g)
    seen = set()
    pairs = weaker = stronger = 0
    by_word = collections.defaultdict(list)
    excused = collections.Counter()
    for path in args[1:]:
        for _rid, branch, boundary, _rule, _expected, command in expect.rows_of(path):
            key = (branch, boundary, command)
            if key in seen:
                continue
            seen.add(key)
            plain = expect.answer(g, branch, boundary, "shell", command)
            for label, word, v in variants(command, known):
                caps = expect.answer(g, branch, boundary, "shell", v)
                pairs += 1
                less = [r for r in plain if RANK.get(caps[r], 3) < RANK.get(plain[r], 3)]
                more = [r for r in plain if RANK.get(caps[r], 3) > RANK.get(plain[r], 3)]
                stronger += bool(more)
                if not less:
                    continue
                if label != "all" and word in NOT_ON_PATH:
                    excused[word] += 1
                    continue
                weaker += 1
                shown = ", ".join(f"{r}: {plain[r]} -> {caps[r]}" for r in less)
                by_word[word].append(f"  [{label}] {shown} | {v!r}"[:220])
    for word, lines in sorted(by_word.items(), key=lambda kv: -len(kv[1])):
        print(f"{word}: {len(lines)} weaker")
        for ln in lines[: max(1, show // max(1, len(by_word)))]:
            print(ln)
    print(f"guard {g.VERSION} {args[0]}")
    print(f"commands {len(seen)} | pairs {pairs} | capitals weaker {weaker} | capitals stronger {stronger} | "
          f"excused (shell words, not on PATH) {sum(excused.values())}: {dict(excused)}")
    return 1 if weaker else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
