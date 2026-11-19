"""Write the mutation list for the fix pass of guard 0.9.0 (groups B and C): one break per code path the fix
pass added.

usage: python3 -I make_mutations_fix.py <guard.py of the fix head> <out.json>

Each entry replaces one exact text that must stand in the guard once; the script checks that and prints the
ones that do not. The list is data for orch/mutate.py, which applies each in a scratch copy and runs the tests.
"""
import json
import sys

M = []


def add(ident, what, old, new):
    M.append({"id": ident, "what": what, "old": old, "new": new})


add("f01", "F09: the word after --include and --glob is left out of the secret check again",
    '_EXCLUDE_VALUE_OPTIONS = frozenset({"--exclude", "--exclude-dir"})',
    '_EXCLUDE_VALUE_OPTIONS = frozenset({"--exclude", "--exclude-dir", "--include", "--glob", "--exclude-from"})')
add("f02", "F22: a long option in neither list takes the next word",
    '        return "flag" if name in table.flag_longs else "unknown"',
    '        return "flag" if name in table.flag_longs else "next"')
add("f03", "F22: a short letter in neither list takes the next word",
    '            return "next" if n == len(t) - 1 else "flag"\n        return "unknown"',
    '            return "next" if n == len(t) - 1 else "flag"\n        return "next" if n == len(t) - 1 else "flag"')
add("f04", "F09/F22: an unknown option is passed over like a flag",
    '        if reading == "unknown":  # F22', '        if False:  # F22')
add("f05", "F10: a search tool behind ssh gives a protected pattern",
    '                if any(tool_name(toks[j].lower()) == "ssh" for j in words if j < k):',
    '                if False:')
add("f06", "F11: a report inside a piped group or compound is quiet",
    '        if any(piped_on.get(o, True) for o in enclosing[k]):  # F11', '        if False:  # F11')
add("f07", "F12: a line the lexer cannot split falls back to the separator-less split",
    '    if cmds is None:  # F12: a line the lexer cannot split shows no pipe; no report of it is quiet\n        return ()',
    '    if cmds is None:  # F12: a line the lexer cannot split shows no pipe; no report of it is quiet\n'
    '        cmds = simple_commands(command)')
add("f08", "F13: a line with $_ keeps its quiet reports",
    '    if "<<" in command or _LAST_ARG_RE.search(command):', '    if "<<" in command:')
add("f09", "F23: the line is lexed as written, so the & of 2>&1 ends the report",
    '    cmds = _hi_lex(_hi_prepare(command)[0])', '    cmds = _hi_lex(command)')
add("f10", "F23: a process substitution behind a closer is no pipe",
    'piped_on[opener] = piped_on.get(opener, False) or nxt in ("|", "|&", "(")',
    'piped_on[opener] = piped_on.get(opener, False) or nxt in ("|", "|&")')
add("f11", "F14: any word of the dry-run family makes a preview",
    '            dry = state == "dry"', '            dry = True')
add("f12", "F14: a word of the family that cannot be placed is passed over",
    '        if state == "unplaced":\n            return False', '        if state == "unplaced":\n            continue')
add("f13", "F24: a long option outside the lists is passed over",
    '            elif name not in flag_longs or glued:\n                return False',
    '            elif False:\n                return False')
add("f14", "F24: a short letter outside the lists is passed over",
    '                if c not in flag_shorts:\n                    return False',
    '                if False:\n                    return False')
add("f15", "F15: only --worktree written out means the work tree",
    '            if len(name) >= 3 and ("--worktree".startswith(name) or "--no-staged".startswith(name)):',
    '            if name == "--worktree":')
add("f16", "F07: the search tool's name is read as written",
    '                name = tool_name(toks[k].lower())', '                name = tool_name(toks[k])')
add("f17", "F08: the hit is placed by its whole part again",
    '                at = part.find(segs[0][0]) if segs[0] else -1', '                at = -1')
add("f18", "F01: only env written plain splits a string",
    '        elif tool_name(name.lower()) == "env" and not env:  # F01', '        elif name == "env" and not env:  # F01')
add("f19", "F04: -h under gh auth is a help probe again",
    '    if _help_probe([t for t in args if t != "-h"] if head == "gh" and _leading(args, ("auth",)) else args):',
    '    if _help_probe(args):')
add("f20", "F05: a value that starts with $ or a backtick is a visible document",
    '    if value.lstrip().startswith(("@", "$", "`")):', '    if value.lstrip().startswith("@"):')
add("f21", "F05: one hidden query field no longer hides the document",
    '    if any(v is None for v in values):\n        return True, None',
    '    values = [v for v in values if v is not None]\n    if not values:\n        return True, None')
add("f22", "F05: only the bare word graphql is the GraphQL path",
    'in ("graphql", "/graphql")', 'in ("graphql",)')
add("f23", "F05: a body on httpie's standard input is not seen",
    '        if httpie and t.lstrip("0123456789").startswith("<"):', '        if False:')
add("f24", "F05: httpie's raw JSON field is not read",
    '        elif httpie and name == "query:" and eq:', '        elif False:')
add("f25", "F06: op item get asks only with --fields, --reveal or --otp",
    '(("item", "get"), None)]', '(("item", "get"), _has("--fields", "--reveal", "--otp"))]')
add("f26", "F06: security find-generic-password needs -w or -g as a word of its own",
    '(("find-generic-password",), _short_has("wg"))', '(("find-generic-password",), _has("-w", "-g"))')
add("f27", "F06: aws configure get reads only the bare key name",
    'w.lower().rsplit(".", 1)[-1] in (', 'w.lower() in (')
add("f28", "F06: aws secretsmanager batch-get-secret-value is no read of values",
    '(("secretsmanager", "get-secret-value"), None), (("secretsmanager", "batch-get-secret-value"), None),',
    '(("secretsmanager", "get-secret-value"), None),')
add("f29", "F06: a kubectl resource word is compared as written",
    'r.split("/", 1)[0].lower().split(".", 1)[0] in ("secret", "secrets")',
    'r.split("/", 1)[0] in ("secret", "secrets")')
add("f30", "F06: kubectl --template prints no data",
    '    if _has("--template")(args):\n        return True', '    if False:\n        return True')
add("f31", "F06: kubectl get --raw of a secrets path is not seen",
    '(("get", _names_secret), _kubectl_output), (("get",), _kubectl_raw_secrets),',
    '(("get", _names_secret), _kubectl_output),')
add("f32", "F06: kubectl config view --flatten is not seen",
    '_has("--raw", "--flatten")', '_has("--raw")')
add("f33", "F06: the bare doppler secrets is not seen",
    ', (("secrets",), _doppler_secrets_bare)]', ']')
add("f34", "F16: doppler run --command is no script",
    '    "doppler": ("run", frozenset({"--command"})),', '    "doppler": ("run", frozenset()),')
add("f35", "F17: curl -T is no PUT",
    '            t == "-T" or t == "--upload-file" or t.startswith("--upload-file=") or (t.startswith("-T") and len(t) > 2)',
    '            False')
add("f36", "F17: httpie's method word counts only in capitals",
    '        method = next((t.upper() for t in seg[1:] if t.upper() in _HTTP_VERBS), "")',
    '        method = next((t for t in seg[1:] if t in _HTTP_VERBS), "")')
add("f37", "F17: a doubled slash in the API path is kept",
    '    return re.sub(r"/+", "/", m.group(1)) if m else None', '    return m.group(1) if m else None')
add("f38", "F17: the dot behind the host name is not read",
    r'_GITHUB_API_RE = re.compile(r"api\.github\.com\.?(/[^\s?#]*)", re.IGNORECASE)',
    r'_GITHUB_API_RE = re.compile(r"api\.github\.com(/[^\s?#]*)", re.IGNORECASE)')
add("f39", "F03: fish and ash are no shells that read a pipe",
    '_PIPE_SHELLS = frozenset("sh bash zsh dash ksh fish ash".split())',
    '_PIPE_SHELLS = frozenset("sh bash zsh dash ksh".split())')
add("f40", "F02/F03: a pipe around a compound into a shell is silent",
    '        if (compound or len(receivers) > 1 or "(" in sep[bar:]) and any(_nc_pipe_shell(t) for t in receivers if t):\n'
    '            return True',
    '        if (compound or len(receivers) > 1 or "(" in sep[bar:]) and any(_nc_pipe_shell(t) for t in receivers if t):\n'
    '            return False')
add("f41", "F21: K11's places are worked out again at every hit (cost only; the timing test decides)",
    '        if places is None:\n            places = _pattern_places(text, ev.command)',
    '        if True:\n            places = _pattern_places(text, ev.command)')
add("f42", "F18: the refs/heads/ prefix counts only in lower case",
    '    name = ref[len("refs/heads/"):] if ref.lower().startswith("refs/heads/") else None',
    '    name = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else None')
add("f43", "F18: the branch name is compared as written",
    'p.lower() == name.lower()', 'p == name')
add("f44", "F19: builtin and command in front of eval or export hide it",
    'while len(toks) > 1 and toks[0] in ("builtin", "command") and not toks[1].startswith("-"):', 'while False:')
add("f45", "F19: a name exported before it is assigned is not followed",
    'exported.extend(t for t in toks if t.partition("=")[0] in export_names)', 'exported.extend(())')
add("f46", "F20: a verb of brew or gem counts only all in capitals",
    'return [t.lower() if t != t.lower() and not t.startswith("-") else t for t in args]',
    'return [t.lower() if t.isupper() and not t.startswith("-") else t for t in args]')
add("f47", "F25: a bare --context takes the next word again",
    '        if name in table.glued_longs:\n            return "flag" if glued else "unknown"',
    '        if name in table.glued_longs:\n            return "flag" if glued else "next"')
add("f48", "F26: git status -v is a quiet report again",
    '            if sub in _REPORT_GIT_SUBS and not (sub == "status" and _git_status_verbose(rest)):',
    '            if sub in _REPORT_GIT_SUBS:')
add("f49", "F26: only -v as a word of its own is the verbose option",
    '        elif t.startswith("-") and "v" in t[1:]:\n            return True',
    '        elif t == "-v":\n            return True')
add("f50", "F26: only --verbose written out is the verbose option",
    '            if len(name) >= 3 and "--verbose".startswith(name):', '            if name == "--verbose":')
add("f51", "F27: go clean -modcache with a value is no delete",
    '        if t in flags or (eq and flag in flags and value not in _GO_BOOL_FALSE):', '        if t in flags:')
add("f52", "F27: -modcache=false is read as given",
    '(eq and flag in flags and value not in _GO_BOOL_FALSE)', '(eq and flag in flags)')


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
