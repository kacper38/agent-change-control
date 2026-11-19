"""Write the mutation list for the build of guard 0.9.0 (groups B and C): one break per new code path.

usage: python3 -I make_mutations.py <guard.py of the build> <out.json>

Each entry replaces one exact text that must stand in the guard once; the script checks that and prints the
ones that do not. The list is data for orch/mutate.py, which applies each in a scratch copy and runs the tests.
"""
import json
import sys

M = []


def add(ident, what, old, new):
    M.append({"id": ident, "what": what, "old": old, "new": new})


# ---- group B
add("b01", "R1: aws ssm send-command no longer asks",
    '"ssm": _verbs("send-command start-session")}', '"ssm": _verbs("start-session")}')
add("b02", "Z: an az call whose verb is no known read is silent",
    "    return f\"`az {' '.join(lead)}` changes resources\"\n", "    return None\n")
add("b03", "Z: az rest with a writing method is silent",
    "        return None if method in _AZ_REST_READS else f\"`az rest --method {method}` changes resources\"",
    "        return None")
add("b04", "R2: uv remove is no delete",
    '"uv": (frozenset({"remove"}), {"pip": frozenset({"uninstall"}), "tool": frozenset({"uninstall"}),',
    '"uv": (frozenset(), {"pip": frozenset({"uninstall"}), "tool": frozenset({"uninstall"}),')
add("b05", "R2: the cache verbs of uv are no delete",
    '"cache": frozenset({"clean", "prune"}), "python": frozenset({"uninstall"})}),',
    '"python": frozenset({"uninstall"})}),')
add("b06", "R2: go clean asks without -modcache as well",
    '_DELETE_ONLY_WITH = {"go": frozenset({"-modcache", "--modcache"})}', "_DELETE_ONLY_WITH = {}")
add("b07", "U1: unshare is no wrapper",
    '**dict.fromkeys("unshare nsenter runuser ltrace', '**dict.fromkeys("nsenter runuser ltrace')
add("b08", "U1: lockf and its kin take no word before the command",
    '**dict.fromkeys("lockf faketime gosu chrt taskset".split(), 1),',
    '**dict.fromkeys("lockf faketime gosu chrt taskset".split(), 0),')
add("b09", "U1: op run is not looked through", '    "op": {("run",): 0},\n', '    "op": {},\n')
add("b10", "U1: hyperfine's quoted word is no command line",
    '_NC_SCRIPT_WORDS = frozenset("ssh watch parallel trap tmux hyperfine watchexec entr".split())',
    '_NC_SCRIPT_WORDS = frozenset("ssh watch parallel trap tmux watchexec entr".split())')
add("b11", "U1: gdb --args is not looked through",
    '_NC_AFTER_OPTION: dict = {"gdb": frozenset({"--args"}), "lldb": frozenset({"--"})}',
    '_NC_AFTER_OPTION: dict = {"gdb": frozenset({"--never"}), "lldb": frozenset({"--"})}')
add("b12", "U3: a Homebrew g name is not the GNU tool",
    "    return name[1:] if name in _GNU_G_NAMES else name", "    return name")
add("b13", "U4: the net does not speak",
    "            for i, j in net_starts(toks) if net else ():", "            for i, j in ():")
add("b14", "U4: a text tool in front of git is no text tool",
    "        if _known_name(name) or name in _NET_TEXT:", "        if _known_name(name):")
add("b15", "L: a mutation on an issue or a label is not denied",
    '_GRAPHQL_TRACKER_RE = re.compile(r"Issue|Label")', '_GRAPHQL_TRACKER_RE = re.compile(r"NeverAName")')
add("b16", "L: another mutation does not ask",
    '    return "ask", GRAPHQL_ASK_MSG.format(what=f"`{via}` sends the GraphQL mutation{named}")', "    return None")
add("b17", "L3: a query the line does not hold does not ask",
    '    if query is None:\n        return "ask", GRAPHQL_ASK_MSG.format(what=f"`{via}` sends a GraphQL document the guard cannot read")',
    "    if query is None:\n        return None")
add("b18", "L: a query read from a variable counts as a document",
    '    if value.startswith("@") or re.fullmatch(r"\\$\\{?\\w+\\}?", value.strip()):\n        return None',
    '    if value.startswith("@"):\n        return None')
add("b19", "P: update-ref of refs/heads/<protected> is not denied",
    '    name = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else None', "    name = None")
add("b20", "P: update-ref HEAD on a protected branch is not denied",
    '    if name is None and ref == "HEAD":\n        name = current_branch(where)',
    '    if name is None and ref == "HEAD":\n        name = None')
add("b21", "P: update-ref --stdin does not ask",
    '    if "--stdin" in rest:\n        return "ask", UPDATE_REF_STDIN_MSG', '    if "--stdin" in rest:\n        return None')
add("b22", "I1: a shell fed by an unread pipe does not ask",
    "    if _nc_pipe_shell(piped):\n        raise CommandNotRead(_PIPE_NOT_READ)",
    "    if False:\n        raise CommandNotRead(_PIPE_NOT_READ)")
add("b23", "V: the secret store table does not speak",
    "        if _leading(args, words) and (cond is None or cond(args)):",
    "        if False and _leading(args, words) and (cond is None or cond(args)):")
add("b24", "V: az calls that print a secret do not ask",
    "        if not _help_probe(args) and any(lead[-len(tail) :] == tail for tail in _AZ_SECRET_TAILS):",
    "        if False:")
add("b25", "V: git credential fill does not ask",
    '        if (sub == "credential" and "fill" in rest) or (sub and sub.startswith("credential-") and "get" in rest):',
    "        if False:")
add("b26", "V: sops -d does not ask",
    '    if head == "sops" and ("-d" in args or "--decrypt" in args):', "    if False:")
add("b27", "V (the engineer's addition): a bare pass NAME does not ask",
    "        if first is not None and first not in _PASS_SUBS:", "        if False:")
add("b28", "V (the engineer's additions): aws ecr get-login-password and sts get-session-token do not ask",
    '            (("ecr", "get-login-password"), None), (("sts", "get-session-token"), None)],', "            ],")
add("b29", "V (the engineer's addition): gcloud application-default token does not ask",
    '               (("auth", "application-default", "print-access-token"), None)],', "               ],")
add("b30", "V: kubectl get secret asks whatever the output format",
    "        return value.split(\"=\", 1)[0] not in _KUBECTL_QUIET_OUTPUT\n    return False",
    "        return True\n    return True")
add("b31", "V: a help probe of a secret store asks",
    "    if _help_probe(args):\n        return None\n    for words, cond in _SECRET_STORES.get(head, ()):",
    "    for words, cond in _SECRET_STORES.get(head, ()):")
add("b32", "W1: a guard path in capitals is no guard path",
    "    return (_guard_config_as_written(path, home_claude)\n            or _guard_config_as_written(path.lower(), home_claude.lower()))",
    "    return _guard_config_as_written(path, home_claude)")
add("b33", "W: the GitHub API host in capitals is another host",
    '        url = next((t for t in seg[1:] if ("api.github.com/repos/" in t.lower() and _ISSUE_API_RE.search(t))',
    '        url = next((t for t in seg[1:] if ("api.github.com/repos/" in t and _ISSUE_API_RE.search(t))')
add("b34", "W2: a verb of brew or gem in capitals is no verb",
    '_CAPS_VERB_TOOLS = frozenset({"brew", "gem"})', "_CAPS_VERB_TOOLS = frozenset()")
add("b35", "M: gh pr merge does not ask",
    '        return "ask", MERGE_ASK_MSG.format(what="`gh pr merge`")', "        return None")
add("b36", "M: gh pr merge --admin is not denied",
    '        if any(t == "--admin" or (t.startswith("--admin=") and t[8:].lower() != "false") for t in seg):',
    "        if False:")
add("b37", "M: a merge through gh api does not ask",
    '        if method == "PUT" and _MERGE_API_RE.search(path):', "        if False:")
add("b38", "M: a merge through curl does not ask",
    '        if merge and _http_method(seg) == "PUT":', "        if False:")
add("b39", "X: an export inside eval does not reach the git call behind it",
    '            if toks[0] == "eval" and len(toks) > 1:', "            if False:")
add("b40", "X: LEFTHOOK=false is no switch",
    '"LEFTHOOK": frozenset({"0", "false"})}', '"LEFTHOOK": frozenset({"0"})}')
add("b41", "X: an ssh option behind the host is taken for the command",
    "    j = _ssh_options(args, k + 1)\n    return None if j is None else list(args[j:])",
    "    return list(args[k + 1 :])")
add("b42", "X: a here-document on a group is not handed to the shell inside",
    '        if not fed and toks in ([], ["}"]):\n            fed, runner = _nc_group_fed(rows, seps, k, bodies)',
    '        if False:\n            fed, runner = _nc_group_fed(rows, seps, k, bodies)')
add("b43", "X5: a `)` of a case pattern closes the substitution again",
    '            if c == ")" and cases and depth == 1:\n                j += 1\n                continue',
    '            if False:\n                j += 1\n                continue')
add("b44", "the first pass of tracker-guard returns its ask before a later deny",
    '        if d and d[0] == "deny":\n            return d\n        if d:\n            asks.append(d)\n    # the reader takes the bodies out (0.8.0); the net reads a gh or az behind an unknown word (0.9.0)',
    '        if d:\n            return d\n    # the reader takes the bodies out (0.8.0); the net reads a gh or az behind an unknown word (0.9.0)')

# ---- group C: each silence, and each condition that keeps a neighbour asking
add("c01", "K1: host-install judges find's operands again",
    "        start = next((k + 1 for k in range(1, len(toks)) if toks[k] in _NC_FIND_EXEC), len(toks))",
    "        start = 1")
add("c02", "K2: git restore --staged asks again",
    '            return (("--staged" in rest or "S" in shorts) and "--worktree" not in rest and "W" not in shorts)',
    "            return False")
add("c03", "K2 keep: git restore --staged --worktree is silent",
    '            return (("--staged" in rest or "S" in shorts) and "--worktree" not in rest and "W" not in shorts)',
    '            return "--staged" in rest or "S" in shorts')
add("c04", "K4: git clean -n asks again",
    '        if sub == "clean":\n            return _git_clean_dry(rest)', '        if sub == "clean":\n            return False')
add("c05", "K4 keep: the word after -e counts as a flag of git clean",
    '        elif t in ("-e", "--exclude"):\n            skip = True', '        elif t in ("-e", "--exclude"):\n            skip = False')
add("c06", "K4 keep: a `--` no longer ends the options of git clean",
    '        elif t == "--":\n            return False\n        elif t == "--dry-run":',
    '        elif t == "--never":\n            return False\n        elif t == "--dry-run":')
add("c07", "K4: kubectl delete --dry-run=client asks again",
    '    if name == "kubectl":\n        return _dry_run("kubectl", toks[1:])\n    return False', "    return False")
add("c08", "K5: a help probe asks again",
    '    if toks[-1] in _DELETE_HELP and not any(t.startswith("-") for t in toks[1:-1]):', "    if False:")
add("c09", "K5 keep: a help word behind another option is a probe too",
    '    if toks[-1] in _DELETE_HELP and not any(t.startswith("-") for t in toks[1:-1]):',
    "    if toks[-1] in _DELETE_HELP:")
add("c10", "K5 keep: rm with an operand and --help is a probe",
    "        if name in _RM_CLASS:\n            return len(toks) == 2", "        if name in _RM_CLASS:\n            return True")
add("c11", "K4/K5 keep: a preview beside another command silences the line",
    "    return len(cmds) == 1 and _delete_preview(cmds[0])", "    return any(_delete_preview(c) for c in cmds)")
add("c12", "K5: deploy-ask asks for kubectl delete --help again",
    "        if _single_preview(ev.command):  # 0.9.0 (K5): `kubectl delete --help` as the whole line changes nothing\n            return None",
    "        if False:\n            return None")
add("c13", "K3: the first pass of secret-shell reads a search pattern as a path again",
    "        # 0.9.0 (K3): the first pass leaves a search tool's pattern out as the reader pass does\n        _secret_reader_seg(seg, ev.cwd, writes, reads)",
    "        _secret_seg(seg, ev.cwd, writes, reads)")
add("c14", "K8: the word after an exclude option is a path again",
    "        if seg[k - 1] in _PATTERN_VALUE_OPTIONS:  # 0.9.0 (K8): `tar --exclude .env`, the value in the next word\n            continue",
    "        if False:\n            continue")
add("c15", "K6/K7/K9: a report command on a secret path asks again",
    "    if quiet.get(words, 0) > 0:\n        quiet[words] -= 1\n        return True\n    return False", "    return False")
add("c16", "K6/K7/K9 keep: a report command whose output is piped onward is silent",
    '        if sep.strip(" ") not in _QUIET_SEPS or nxt in ("|", "|&", "("):\n            continue',
    "        if False:\n            continue")
add("c17", "K6/K7/K9 keep: a line with a here-document is read for quiet reports",
    '    if "<<" in command:\n        return ()', "    if False:\n        return ()")
add("c18", "K6/K7/K9 keep: a quiet report is not counted off, so its nested twin is silent too",
    "    if quiet.get(words, 0) > 0:\n        quiet[words] -= 1\n        return True", "    if quiet.get(words, 0) > 0:\n        return True")
add("c19", "K7: git status on a secret path asks again",
    '_REPORT_GIT_SUBS = frozenset({"check-ignore", "ls-files", "status"})', '_REPORT_GIT_SUBS = frozenset({"check-ignore", "ls-files"})')
add("c20", "K7 keep: git diff counts as a command that reports names",
    '_REPORT_GIT_SUBS = frozenset({"check-ignore", "ls-files", "status"})',
    '_REPORT_GIT_SUBS = frozenset({"check-ignore", "ls-files", "status", "diff"})')
add("c21", "K6 keep: cat counts as a report command",
    '_REPORT_HEADS = frozenset({"echo", "printf", "ls", "stat", "test", "[", "[["})',
    '_REPORT_HEADS = frozenset({"echo", "printf", "ls", "stat", "test", "[", "[[", "cat"})')
add("c22", "K10: command -v of an LLM tool asks again",
    '            if toks[i] == "command" and toks[i + 1 : i + 2] in (["-v"], ["-V"]):',
    "            if False:")
add("c23", "K11: a vendor's name in a quoted search pattern asks again",
    "        if d and not _only_in_search_patterns(text, ev.command, seg):", "        if d:")
add("c24", "K11 keep: a hit outside the pattern is dropped as well",
    "            if not any(a <= pos and end <= b for a, b in spans):\n                return False",
    "            if False:\n                return False")
add("c25", "K11 keep: a pattern without a bar counts too, so any quoted word of a search tool hides a hit",
    "        if not _SEP_RE.search(p):\n            continue", "        if False:\n            continue")


def main(argv):
    guard, out = argv[0], argv[1]
    with open(guard, encoding="utf-8") as handle:
        text = handle.read()
    bad = 0
    for m in M:
        count = text.count(m["old"])
        if count != 1:
            bad += 1
            print(f"old text stands {count} times: {m['id']} {m['what']}")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(M, handle, indent=1)
    print(f"mutations {len(M)} | not applicable {bad} | written {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
