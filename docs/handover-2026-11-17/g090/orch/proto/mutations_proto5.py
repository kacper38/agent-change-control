"""Planted breaks for the design probe of the sixth fix round: one per rule (a quiet report is a command the
check is certain about). Data for mutate_probe.py. `old` stands exactly once in the probe; raw strings, so no
escape is doubled."""

DIRS = r'''frozenset({"/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"})'''
PLAIN = r'''"[A-Za-z0-9%_./:,+@=\\\\\U000f0000-\U000ffffd-]*"'''


def allow(chars):
    return PLAIN.replace("%_", chars + "%_")


MUTATIONS = [
    dict(id="n01", why="no screen for a carriage return", old=r'''"\\$\\[|\r|[\U000f0000''',
         new=r'''"\\$\\[|[\U000f0000'''),
    dict(id="n02", why="a name with a path is a report anywhere",
         old='''if "/" in words[0] and os.path.dirname(words[0]) not in _REPORT_DIRS:''', new="if False:"),
    dict(id="n03", why="any absolute path is a system folder",
         old='''os.path.dirname(words[0]) not in _REPORT_DIRS:''', new='''not words[0].startswith("/"):'''),
    dict(id="n04", why="the folder at hand is a system folder", old=DIRS,
         new=DIRS.replace('"/bin", ', '"/bin", ".", ')),
    dict(id="n05a", why="/bin is no system folder", old=DIRS, new=DIRS.replace('"/bin", ', "")),
    dict(id="n05b", why="/usr/bin is no system folder", old=DIRS, new=DIRS.replace('"/usr/bin", ', "")),
    dict(id="n05c", why="/usr/local/bin is no system folder", old=DIRS, new=DIRS.replace('"/usr/local/bin", ', "")),
    dict(id="n05d", why="/opt/homebrew/bin is no system folder", old=DIRS,
         new=DIRS.replace(', "/opt/homebrew/bin"', "")),
    dict(id="n06", why="no look for `$_` in the words as the shell reads them",
         old='''if any(_LAST_ARG_RE.search(_quiet_unmask(t)) for t in toks):''', new="if False:"),
    dict(id="n07", why="`$_` looked for in the masked words",
         old='''_LAST_ARG_RE.search(_quiet_unmask(t)) for t in toks''', new='''_LAST_ARG_RE.search(t) for t in toks'''),
    dict(id="n08", why="every printf is a report",
         old='''if head == "printf" and len(words) > 1 and not _printf_format(masked_words[1]):''', new="if False:"),
    dict(id="n09", why="a first argument that starts with a dash is a format",
         old='''return (not plain.startswith("-") and "$" not in plain''', new='''return ("$" not in plain'''),
    dict(id="n10", why="a dollar sign in the first argument is no expansion",
         old='''not plain.startswith("-") and "$" not in plain and''', new='''not plain.startswith("-") and'''),
    dict(id="n11", why="a backtick in the first argument is no substitution", old='''and "`" not in plain''', new=""),
    dict(id="n12", why="the unquoted part of the first argument may hold anything",
         old='''\n            and _PRINTF_PLAIN_RE.fullmatch(first) is not None)''', new=")"),
    dict(id="n13a", why="braces allowed outside quotes", old=PLAIN, new=allow("{},")),
    dict(id="n13b", why="a star allowed outside quotes", old=PLAIN, new=allow("*")),
    dict(id="n13c", why="a question mark allowed outside quotes", old=PLAIN, new=allow("?")),
    dict(id="n13d", why="square brackets allowed outside quotes", old=PLAIN, new=allow(r"\\[\\]")),
    dict(id="n13e", why="a hash sign allowed outside quotes", old=PLAIN, new=allow("#")),
    dict(id="n13f", why="a caret allowed outside quotes", old=PLAIN, new=allow("^")),
    dict(id="n13g", why="a tilde allowed outside quotes", old=PLAIN, new=allow("~")),
    dict(id="n14", why="`--` in front is taken for an option",
         old='''    if plain == "--":\n        return True\n''', new=""),
    dict(id="n15", why="a printf without words is read for its first argument",
         old='''if head == "printf" and len(words) > 1 and not''', new='''if head == "printf" and not'''),
    dict(id="n16", why="the last word is taken for the first argument",
         old='''_printf_format(masked_words[1])''', new='''_printf_format(masked_words[-1])'''),
    dict(id="n17", why="a quoted character is judged like a bare one",
         old='''_PRINTF_PLAIN_RE.fullmatch(first) is not None''', new='''_PRINTF_PLAIN_RE.fullmatch(plain) is not None'''),
    dict(id="n18", why="a backslash inside double quotes is no format character", old=PLAIN,
         new=PLAIN.replace(r"\\\\", "")),
    dict(id="n19", why="`case` is looked for between blanks only", old='''or _CASE_WORD_RE.search(body):''',
         new='''or "case" in body.split():'''),
    dict(id="n20", why="`case` inside a longer word counts",
         old=r'''re.compile(r"(?<![A-Za-z0-9_])case(?![A-Za-z0-9_])")''', new=r'''re.compile(r"case")'''),
    dict(id="n21", why="no look for `case` at all", old='''or _CASE_WORD_RE.search(body):''', new=''':'''),
]
