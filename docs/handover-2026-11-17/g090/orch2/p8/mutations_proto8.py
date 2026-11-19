"""Planted breaks for the design probe of the eighth fix round: one per part of the rule (a git report is quiet
only when nothing else on the line can set what git reads). Data for mutate_probe.py. `old` stands exactly once
in the probe."""

COND = ("    if (git_at and not _WORD_RUNS_RE.search(command)\n"
        "            and all(k in git_at or k in beside or _sets_nothing(toks) for k, (_sep, toks) in enumerate(cmds))):")
SET = '''_BESIDE_GIT_REPORT = frozenset({"cd", "true", "false"}) | _COMPOUND_CLOSERS'''
RUNS = '''_WORD_RUNS_RE = re.compile(r"\\$[({]|`")'''
ALONE = ("    while k < len(toks) and toks[k] in _NC_SHELL_WORDS:\n"
         "        k += 1\n"
         "    return tuple(toks[k:]) == _report_words(toks)")

MUTATIONS = [
    dict(id="h01", why="every git report that is plain is quiet, whatever stands beside it", old=COND, new="    if git_at:"),
    dict(id="h02", why="a word that runs a command is not looked for",
         old=" and not _WORD_RUNS_RE.search(command)", new=""),
    dict(id="h03", why="the other commands of the line are not looked at",
         old="\n            and all(k in git_at or k in beside or _sets_nothing(toks) for k, (_sep, toks) in enumerate(cmds))):",
         new="):"),
    dict(id="h04", why="only the first git report of a line may stand beside another",
         old="all(k in git_at or k in beside", new="all(k == min(git_at) or k in beside"),
    dict(id="h05", why="another quiet report may not stand beside a git report",
         old="all(k in git_at or k in beside or _sets_nothing(toks)", new="all(k in git_at or _sets_nothing(toks)"),
    dict(id="h06", why="every quiet report may stand beside, with a redirection or an assignment too",
         old="            if _words_alone(toks):\n                beside.add(k)", new="            beside.add(k)"),
    dict(id="h07", why="a command that sets nothing may carry a redirection or an assignment",
         old="    if not _words_alone(toks):\n        return False\n    words = _report_words(toks)\n    return not words",
         new="    words = _report_words(toks)\n    return not words"),
    dict(id="h08", why="a shell word alone is no command that sets nothing",
         old="    return not words or words[0] in _BESIDE_GIT_REPORT",
         new="    return bool(words) and words[0] in _BESIDE_GIT_REPORT"),
    dict(id="h09", why="any command sets nothing", old="    return not words or words[0] in _BESIDE_GIT_REPORT",
         new="    return True"),
    dict(id="h10", why="a closer may not stand beside", old=SET, new=SET.replace(" | _COMPOUND_CLOSERS", "")),
    dict(id="h11", why="cd may not stand beside", old=SET, new=SET.replace('"cd", ', "")),
    dict(id="h12", why="true may not stand beside", old=SET, new=SET.replace('"true", ', "")),
    dict(id="h13", why="false may not stand beside", old=SET, new=SET.replace(', "false"', "")),
    dict(id="h14", why="export may stand beside", old=SET, new=SET.replace('"cd", ', '"cd", "export", ')),
    dict(id="h15", why="git may stand beside (git config)", old=SET, new=SET.replace('"cd", ', '"cd", "git", ')),
    dict(id="h16", why="the leading shell words count as words of the command",
         old=ALONE, new="    return tuple(toks) == _report_words(toks)"),
    dict(id="h17", why="every command is its words alone", old=ALONE, new="    return True"),
    dict(id="h18", why="`${` runs nothing", old=RUNS, new=RUNS.replace("[({]", "[(]")),
    dict(id="h19", why="`$(` runs nothing", old=RUNS, new=RUNS.replace("[({]", "[{]")),
    dict(id="h20", why="a backtick runs nothing", old=RUNS, new=RUNS.replace("|`", "")),
    dict(id="h21", why="the word is looked for in the git report's own words only",
         old=" and not _WORD_RUNS_RE.search(command)",
         new=" and not any(_WORD_RUNS_RE.search(w) for ws in git_at.values() for w in ws)"),
    dict(id="h22", why="the rule holds for the first command of the line only",
         old="for k, (_sep, toks) in enumerate(cmds))):", new="for k, (_sep, toks) in enumerate(cmds[:1]))):"),
    dict(id="h23", why="only the commands in front of the first git report are looked at",
         old="for k, (_sep, toks) in enumerate(cmds))):", new="for k, (_sep, toks) in enumerate(cmds[: min(git_at)]))):"),
    dict(id="h24", why="only the commands behind the first git report are looked at",
         old="for k, (_sep, toks) in enumerate(cmds))):",
         new="for k, (_sep, toks) in enumerate(cmds) if k >= min(git_at))):"),
    dict(id="h25", why="every report of the line takes the rule, not only git's",
         old="        if head in _REPORT_HEADS:\n            out.append(words)\n            if _words_alone(toks):",
         new="        if head in _REPORT_HEADS:\n            git_at[k] = words\n            if _words_alone(toks):"),
]
