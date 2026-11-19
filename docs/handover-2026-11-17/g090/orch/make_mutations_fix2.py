"""Write the mutation list for the second fix round and its addendum of guard 0.9.0 (groups B and C): one break
per code path these two rounds added, plus new forms of the breaks of the earlier lists whose text has moved.

usage: python3 -I make_mutations_fix2.py <guard.py of the head> <out.json>

Each entry replaces one exact text that must stand in the guard once; the script checks that and prints the
ones that do not. The list is data for orch/mutate.py, which applies each in a scratch copy and runs the tests.
"""
import json
import sys

M = []


def add(ident, what, old, new):
    M.append({"id": ident, "what": what, "old": old, "new": new})


# --- second round: the quiet-report check reads a separator by its characters and fails closed
add("g01", "F28: a pipe counts as a plain separator, so a report piped on is quiet",
    '_PLAIN_SEPS = frozenset({"", ";", "&&", "||", "&"})',
    '_PLAIN_SEPS = frozenset({"", ";", "&&", "||", "&", "|"})')
add("g02", "F28: a separator is compared whole, so a pipe with a line break behind it hands nothing on",
    '    return sep.replace(" ", "").replace("\\n", "") in _PLAIN_SEPS',
    '    return sep.strip(" ") not in ("|", "|&")')
add("g03", "F28: a separator with a line break in it is no plain separator",
    '    return sep.replace(" ", "").replace("\\n", "") in _PLAIN_SEPS',
    '    return sep.strip(" ") in _PLAIN_SEPS')
add("g04", "F33: a closer that is not the word of the construct it would close is taken as its closer",
    '            if not stack or stack[-1][1] != toks[0]:\n                return None',
    '            if not stack:\n                return None')
add("g05", "F11: of the constructs one command opens, the last closer decides alone",
    '            handed_on[opener] = handed_on.get(opener, False) or not _plain_sep(',
    '            handed_on[opener] = not _plain_sep(')
add("g06", "F32: a bracket in a separator no longer ends the quiet reading",
    '        if any(c in sep for c in "()`"):', '        if any(c in sep for c in "`"):')
add("g07", "F32: a backtick in a separator no longer ends the quiet reading",
    '        if any(c in sep for c in "()`"):', '        if any(c in sep for c in "()"):')
add("g08", "F32: a line with `function` or `coproc` keeps its quiet reports",
    '        if _report_words(toks)[:1] in (("function",), ("coproc",)):', '        if False:')
add("g09", "F32: a line with `function` keeps its quiet reports",
    '        if _report_words(toks)[:1] in (("function",), ("coproc",)):',
    '        if _report_words(toks)[:1] in (("coproc",),):')
add("g10", "F32: a line with `coproc` keeps its quiet reports",
    '        if _report_words(toks)[:1] in (("function",), ("coproc",)):',
    '        if _report_words(toks)[:1] in (("function",),):')
add("g11", "F33: a line whose closers do not match keeps its quiet reports",
    '    if outputs is None:\n        return ()\n    enclosing, handed_on = outputs',
    '    if outputs is None:\n        outputs = ([[] for _ in cmds], {})\n    enclosing, handed_on = outputs')
add("g12", "F28: only the separator behind a report is looked at",
    '        if not _plain_sep(sep) or not _plain_sep(cmds[k + 1][0] if k + 1 < len(cmds) else ""):',
    '        if not _plain_sep(cmds[k + 1][0] if k + 1 < len(cmds) else ""):')
add("g13", "F28: only the separator in front of a report is looked at, so a report piped on is quiet",
    '        if not _plain_sep(sep) or not _plain_sep(cmds[k + 1][0] if k + 1 < len(cmds) else ""):',
    '        if not _plain_sep(sep):')
add("g14", "F11: a construct that never closes counts as not handed on",
    '        if any(handed_on.get(o, True) for o in enclosing[k]):  # F11',
    '        if any(handed_on.get(o, False) for o in enclosing[k]):  # F11')
add("g15", "F11: a report inside a piped group or compound is quiet (f06 of the fix list, moved)",
    '        if any(handed_on.get(o, True) for o in enclosing[k]):  # F11', '        if False:  # F11')

# --- second round: the hook switch behind a shell word, time, command -p
add("g16", "F30: an export behind a shell word (`{`, `then`, `do`, `!`) is not read",
    '                if toks[0] in _NC_SHELL_WORDS:\n                    toks = toks[1:]\n                elif toks[0] == "time":',
    '                if False:\n                    toks = toks[1:]\n                elif toks[0] == "time":')
add("g17", "F30: an export behind `time` is not read",
    '                elif toks[0] == "time":\n                    toks = toks[2:] if toks[1:2] == ["-p"] else toks[1:]',
    '                elif False:\n                    toks = toks[2:] if toks[1:2] == ["-p"] else toks[1:]')
add("g18", "F30: the -p of `time -p` is taken as the command",
    '                    toks = toks[2:] if toks[1:2] == ["-p"] else toks[1:]', '                    toks = toks[1:]')
add("g19", "F30: `command -p export`, `command -- export`, `builtin -- eval` are not read",
    '                    while k < len(toks) and toks[k] in (("-p", "--") if toks[0] == "command" else ("--",)):',
    '                    while False:')
add("g20", "F30: `command -p export` is not read",
    '                    while k < len(toks) and toks[k] in (("-p", "--") if toks[0] == "command" else ("--",)):',
    '                    while k < len(toks) and toks[k] in ("--",):')
add("g21", "F19: builtin and command in front of eval or export hide it (f44 of the fix list, moved)",
    '                elif toks[0] in ("builtin", "command"):\n                    k = 1',
    '                elif False:\n                    k = 1')

# --- second round: the GitHub API host with a port, doubled slashes, a trailing dot
add("g22", "F31: a port behind the API host hides the path",
    '_GITHUB_API_RE = re.compile(r"api\\.github\\.com\\.?(?::\\d+)?(/[^\\s?#]*)", re.IGNORECASE)',
    '_GITHUB_API_RE = re.compile(r"api\\.github\\.com\\.?(/[^\\s?#]*)", re.IGNORECASE)')
add("g23", "F31: a port behind the API host hides the GraphQL URL",
    '_GRAPHQL_URL_RE = re.compile(r"api\\.github\\.com\\.?(?::\\d+)?/+graphql(?![\\w.-])", re.IGNORECASE)',
    '_GRAPHQL_URL_RE = re.compile(r"api\\.github\\.com\\.?/+graphql(?![\\w.-])", re.IGNORECASE)')
add("g24", "F31: a doubled slash in front of graphql hides the GraphQL URL",
    '_GRAPHQL_URL_RE = re.compile(r"api\\.github\\.com\\.?(?::\\d+)?/+graphql(?![\\w.-])", re.IGNORECASE)',
    '_GRAPHQL_URL_RE = re.compile(r"api\\.github\\.com\\.?(?::\\d+)?/graphql(?![\\w.-])", re.IGNORECASE)')
add("g25", "F17: the dot behind the host name hides the GraphQL URL (f38 of the fix list, moved)",
    '_GRAPHQL_URL_RE = re.compile(r"api\\.github\\.com\\.?(?::\\d+)?/+graphql(?![\\w.-])", re.IGNORECASE)',
    '_GRAPHQL_URL_RE = re.compile(r"api\\.github\\.com(?::\\d+)?/+graphql(?![\\w.-])", re.IGNORECASE)')
add("g26", "F17: the dot behind the host name hides the API path",
    '_GITHUB_API_RE = re.compile(r"api\\.github\\.com\\.?(?::\\d+)?(/[^\\s?#]*)", re.IGNORECASE)',
    '_GITHUB_API_RE = re.compile(r"api\\.github\\.com(?::\\d+)?(/[^\\s?#]*)", re.IGNORECASE)')
add("g27", "F31: `gh api //graphql` is no GraphQL call",
    '    flat = re.sub(r"/+", "/", path)', '    flat = path')
add("g28", "F31: a doubled slash in the merge path of `gh api` hides the merge",
    '        if method == "PUT" and _MERGE_API_RE.search(re.sub(r"/+", "/", path)):',
    '        if method == "PUT" and _MERGE_API_RE.search(path):')
add("g29", "M: a merge through gh api does not ask (b37 of the build list, moved)",
    '        if method == "PUT" and _MERGE_API_RE.search(re.sub(r"/+", "/", path)):',
    '        if False and method == "PUT" and _MERGE_API_RE.search(re.sub(r"/+", "/", path)):')

# --- second round: the pipe with a subshell, group or compound on one side
add("g30", "F28: the separators of the compound-pipe check are compared with their ends cut only (`|⏎(`)",
    '    compact = [s.replace(" ", "").replace("\\n", "") for s in seps]',
    '    compact = [s.strip(" \\n") for s in seps]')
add("g31", "F29: a row of redirections behind a closing bracket does not stand for the subshell",
    '                    or (not left and ")" in compact[r - 1]))', '                    or False)')
add("g32", "F36: only the shells of _PIPE_SHELLS read a pipe ($SHELL, ${SHELL} do not)",
    '        shell = name in _PIPE_SHELLS or os.path.basename(toks[i]) in _NC_STDIN_SHELLS',
    '        shell = name in _PIPE_SHELLS')
add("g33", "F36: `sudo -s`, `sudo -i` and `su` behind a pipe are no shells",
    '        if shell and _hi_shell_reads_stdin(args):\n            return True\n        if (name == "sudo" and '
    '_sudo_runs_shell(args)) or (name == "su" and _su_runs_shell(args)):',
    '        if shell and _hi_shell_reads_stdin(args):\n            return True\n        if False:')
add("g34", "F36: `sudo -s` behind a pipe is no shell",
    '        if shell and _hi_shell_reads_stdin(args):\n            return True\n        if (name == "sudo" and '
    '_sudo_runs_shell(args)) or (name == "su" and _su_runs_shell(args)):',
    '        if shell and _hi_shell_reads_stdin(args):\n            return True\n        if name == "su" and '
    '_su_runs_shell(args):')
add("g35", "F36: `su` behind a pipe is no shell",
    '        if shell and _hi_shell_reads_stdin(args):\n            return True\n        if (name == "sudo" and '
    '_sudo_runs_shell(args)) or (name == "su" and _su_runs_shell(args)):',
    '        if shell and _hi_shell_reads_stdin(args):\n            return True\n        if name == "sudo" and '
    '_sudo_runs_shell(args):')
add("g36", "I1: a shell behind a pipe is no reader of the pipe (b22 of the build list, moved)",
    '        if shell and _hi_shell_reads_stdin(args):\n            return True\n        if (name == "sudo"',
    '        if False:\n            return True\n        if (name == "sudo"')
add("g37", "ad: a shell behind a container or remote tool counts as a shell of this machine",
    '        if name in _NC_ELSEWHERE:\n            return False\n        shell = name in _PIPE_SHELLS',
    '        if False:\n            return False\n        shell = name in _PIPE_SHELLS')

# --- addendum: an unread pipe is a finding of the read, not its end (F40); a fed bar is no unread pipe (F37)
add("g38", "F40: delete-guard does not ask for an unread pipe",
    '        what = _delete_judge(ev)\n        pipe = _PIPE_NOT_READ if _unread_pipe(ev.command) else None',
    '        what = _delete_judge(ev)\n        pipe = None')
add("g39", "F40: deploy-ask does not ask for an unread pipe",
    '        what = _deploy_text(text) or deploy_what(ev.command)\n        pipe = _PIPE_NOT_READ if '
    '_unread_pipe(ev.command) else None',
    '        what = _deploy_text(text) or deploy_what(ev.command)\n        pipe = None')
add("g40", "F40: the reader pass does not ask for an unread pipe",
    '        if nested_unread_pipe(text, local):  # read past it', '        if False:  # read past it')
add("g41", "F40: a shell behind a plain pipe whose script is not on the line gets no mark",
    '    if unread is not None and _nc_pipe_shell(piped):\n        unread.append(True)',
    '    if False:\n        unread.append(True)')
add("g42", "F40: a pipe with a subshell, group or compound on one side gets no mark",
    '    if cmds is not None and unread is not None and _nc_compound_pipe(rows, seps, fed_bars):\n'
    '        unread.append(True)',
    '    if False:\n        unread.append(True)')
add("g43", "F37: a bar through which a script was read counts as an unread pipe",
    '        if r in fed_bars:\n            continue', '        if False:\n            continue')
add("g44", "F37: every bar in front of a command counts as read, whether a script came through or not",
    '        if piped is not None and runner is piped:\n            fed_bars.add(k + 1)',
    '        if piped is not None:\n            fed_bars.add(k + 1)')
add("g45", "F40: an unread pipe inside a nested script gets no mark",
    '            _nc_read(script, depth + 1, out, seen, local, inputs, bodies, envs, script_env, unread)',
    '            _nc_read(script, depth + 1, out, seen, local, inputs, bodies, envs, script_env)')
add("g46", "F40: an unread pipe stops secret-shell from reading the input redirections",
    '    if failed is None or failed == _pipe_ask("secret-shell"):', '    if failed is None:')
add("g47", "F40: the read never reports an unread pipe",
    '    return tuple(out), tuple(inputs), tuple(envs), bool(unread)',
    '    return tuple(out), tuple(inputs), tuple(envs), False')

# --- addendum: the body of an http call (F38) and a redirect target behind a continuation (F39)
add("g48", "F38: httpie's --raw is no body",
    '                or (httpie and name == "--raw")):', '                or False):')
add("g49", "F38: --raw is a body for curl and wget too",
    '                or (httpie and name == "--raw")):', '                or name == "--raw"):')
add("g50", "F38: wget's --body-data is no body",
    '        if (name in _CURL_MUTATING_FLAGS or name == "--body-data" or t.startswith("--data")',
    '        if (name in _CURL_MUTATING_FLAGS or t.startswith("--data")')
add("g51", "F38: wget's --body-file is no body from a file",
    '        if name in ("-T", "--upload-file", "--post-file", "--body-file"):',
    '        if name in ("-T", "--upload-file", "--post-file"):')
add("g52", "F38: an httpie call that shows no document is found as no call",
    '    return httpie, None  # httpie sends', '    return False, None  # httpie sends')
add("g53", "F38: a curl or wget call that shows no body is found as a call without a document",
    '    return httpie, None  # httpie sends', '    return True, None  # httpie sends')
add("g54", "F39: the redirect targets are read on the line as written, so one behind a continuation is missed",
    '    for target in _REDIRECT_RE.findall(command.replace("\\\\\\n", "")):',
    '    for target in _REDIRECT_RE.findall(command):')


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
        if m["old"] == m["new"]:
            bad += 1
            print(f"old and new are the same text: {m['id']}")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(M, handle, indent=1)
    print(f"mutations {len(M)} | not applicable {bad} | written {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
