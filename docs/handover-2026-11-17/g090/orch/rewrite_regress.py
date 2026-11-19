#!/usr/bin/env python3
"""Two guards, every command of the lists, every rewriting that keeps what the command does.

usage: python3 -u -I rewrite_regress.py <expect.py> <weaker_cells.py> <multiline_meta.py> <old guard.py>
       <new guard.py> <out.json> [--shard I/N] <file> [<file> ...]

For each one-line command C of the files, each rewriting T of it and three contexts (feat/x own, main own,
feat/x client), per shell rule, two questions:
  A  is the new guard weaker for T than for C as written?            new(T) < new(C)
     A-old  the old guard is weaker for T than for C too (a gap older than this build)
     A-new  only the new guard is
  B  is the new guard weaker than the old one on the text T itself?  new(T) < old(T)
     B-inherited  C as written is weaker at the new guard too (the row check answers for that cell)
     B-own        C as written is not weaker: only the rewritten form lost its verdict
The rewritings are those of multiline_meta.py (plain and wrappers) and the ones of extra() and extra_wrappers()
below. Writes every A and B cell to out.json and prints the counts per class, rewriting and rule. With --shard
I/N only the commands whose place in the list is I modulo N are judged (several processes, one file each).
Commands are strings handed to rule functions; nothing runs.
"""
import collections
import importlib.util
import json
import sys

RANK = {"silent": 0, "ask": 1, "deny": 2}
CONTEXTS = [("feat/x", "own"), ("main", "own"), ("feat/x", "client")]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extra(cmd, meta):
    """Rewritings beside those of multiline_meta.py: lists, loops, a function, a background job, comments,
    substitutions, a nested or fed script, and other ways to write the gaps between the words."""
    out = collections.OrderedDict()
    if "\n" in cmd or "<<" in cmd or not cmd.strip():
        return out
    tail = cmd.rstrip()
    out["cpre"] = "# note\n" + cmd
    if not tail.endswith(("&", "\\", ";")) and "#" not in cmd:
        out["semipre"] = "true; " + cmd
        out["semipost"] = cmd + "; true"
        out["not"] = "! " + cmd
        out["time"] = "time " + cmd
        out["for"] = "for i in 1; do " + cmd + "; done"
        out["while"] = "while true; do " + cmd + "; break; done"
        out["func"] = "f() { " + cmd + "; }; f"
        out["bg"] = cmd + " & wait"
        # a second command on the line that every rule asks for (a pipe into a shell the guard cannot read): the
        # verdict on the first must not get weaker by it
        out["seqpipe"] = cmd + "; cat run.sh | sh"
        out["pipeseq"] = "cat run.sh | sh; " + cmd
        out["andpipe"] = cmd + " && cat run.sh | sh"
        out["seqsubpipe"] = cmd + "; (cat run.sh) | bash"
        out["comment"] = cmd + " # note"
        # a space behind `$(`: a command that starts with `(` would read as arithmetic, `$((`
        out["subst"] = "x=$( " + cmd + " )"
        out["qsubst"] = 'echo "$( ' + cmd + ' )"'
        if "`" not in cmd and "\\" not in cmd:
            out["tick"] = "x=`" + cmd + "`"
        if "'" not in cmd:
            out["bashc"] = "bash -c '" + cmd + "'"
            out["eval"] = "eval '" + cmd + "'"
            out["heredoc"] = "sh <<'EOF'\n" + cmd + "\nEOF"
            if "\\" not in cmd:
                out["fed"] = "echo '" + cmd + "' | sh"
    if not any(c in cmd for c in "`#\\") and "$(" not in cmd and "<(" not in cmd and ">(" not in cmd:
        text = cmd.strip()
        gaps = meta.top_level(text, " ")
        if gaps:
            out["cont1"] = meta.replace_at(text, gaps[:1], " ", " \\\n")
            out["contN"] = meta.replace_at(text, gaps[-1:], " ", " \\\n")
            out["tabs"] = meta.replace_at(text, gaps, " ", "\t")
            out["sp2"] = meta.replace_at(text, gaps, " ", "  ")
    return out


def extra_wrappers(cmd):
    """More tools and shell words that run the command after them, for one simple command that starts with a
    command name."""
    out = collections.OrderedDict()
    head = cmd.lstrip()
    if any(c in cmd for c in ";|&(){}<>`#\\\n") or not head:
        return out
    first = head.split(" ", 1)[0]
    if "=" in first or head.startswith(("if ", "for ", "while ", "until ", "case ", "[[", "[ ", "test ", "! ")):
        return out
    out["command-p"] = "command -p " + cmd
    out["exec"] = "exec " + cmd
    out["nice-n"] = "nice -n 5 " + cmd
    out["sudo-u"] = "sudo -u build " + cmd
    out["env-i"] = "env -i " + cmd
    out["stdbuf"] = "stdbuf -oL " + cmd
    out["noglob"] = "noglob " + cmd
    out["caffeinate"] = "caffeinate -i " + cmd
    out["timeout-k"] = "timeout -k 1 5 " + cmd
    return out


def main(argv):
    shard = None
    if "--shard" in argv:
        at = argv.index("--shard")
        i, n = argv[at + 1].split("/")
        shard = (int(i), int(n))
        argv = argv[:at] + argv[at + 2 :]
    expect = load(argv[1], "expect_helper")
    readers = load(argv[2], "weaker_cells_helper")
    meta = load(argv[3], "meta_helper")
    old, new = expect.load(argv[4]), load(argv[5], "guard_new")
    out_path = argv[6]
    commands = collections.OrderedDict()
    for path in argv[7:]:
        for command, _row in readers.lines_of(path):
            commands.setdefault(command, None)
    cells = []
    counts = collections.Counter()
    judged = collections.Counter()
    crashes = 0
    done = 0
    for n, command in enumerate(commands):
        if shard and n % shard[1] != shard[0]:
            continue
        done += 1
        forms = collections.OrderedDict()
        meta.WRAPPERS = False
        forms.update(meta.rewritings(command))
        if "\n" not in command and "<<" not in command:
            for kind, text in meta.wrapper_rewritings(command).items():
                forms["w:" + kind] = text
            for kind, text in extra_wrappers(command).items():
                forms["w:" + kind] = text
        forms.update(extra(command, meta))
        if not forms:
            continue
        for branch, boundary in CONTEXTS:
            o_c = expect.answer(old, branch, boundary, "shell", command)
            n_c = expect.answer(new, branch, boundary, "shell", command)
            for kind, text in forms.items():
                o_t = expect.answer(old, branch, boundary, "shell", text)
                n_t = expect.answer(new, branch, boundary, "shell", text)
                judged[kind] += 1
                for rule in n_c:
                    nt, nc, ot, oc = n_t[rule], n_c[rule], o_t[rule], o_c[rule]
                    if nt.startswith("CRASH"):
                        crashes += 1
                        print(f"CRASH {kind} [{branch}@{boundary}] {rule}: {nt} | {json.dumps(text)[:160]}")
                        continue
                    if any(v not in RANK for v in (nc, ot, oc)):
                        continue
                    classes = []
                    if RANK[nt] < RANK[nc]:
                        classes.append("A-old" if RANK[ot] < RANK[oc] else "A-new")
                    if RANK[nt] < RANK[ot]:
                        classes.append("B-inherited" if RANK[nc] < RANK[oc] else "B-own")
                    for cls in classes:
                        counts[(cls, kind, rule)] += 1
                    if classes:
                        cells.append({"classes": classes, "kind": kind, "branch": branch, "boundary": boundary,
                                      "rule": rule, "command": command, "text": text,
                                      "old_written": oc, "new_written": nc, "old_rewritten": ot, "new_rewritten": nt})
        if done % 200 == 0:
            print(f"... {done} commands, cells so far {len(cells)}")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(cells, fh, indent=0)
    print(f"old {old.VERSION} | new {new.VERSION} | commands {done} of {len(commands)} | texts judged "
          f"{sum(judged.values())} | cells {len(cells)} | crashes {crashes}")
    per = collections.Counter()
    for (cls, _kind, _rule), count in counts.items():
        per[cls] += count
    print("classes: " + ", ".join(f"{k} {v}" for k, v in sorted(per.items())))
    for (cls, kind, rule), count in sorted(counts.items()):
        if cls in ("A-new", "B-own"):
            print(f"  {cls:6} {kind:12} {rule:17} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
