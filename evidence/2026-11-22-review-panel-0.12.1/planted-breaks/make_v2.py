"""Write the planted-break lists of review round 1 (item #69): the lists of d719af0d brought to the new code, plus
breaks of what round 1 added. usage: python3 -I make_v2.py <mut folder>. Writes panel_mutants_v2.json and
pin_mutants_v2.json beside the old lists."""
import json
import pathlib
import sys

mut = pathlib.Path(sys.argv[1])
old_panel = json.loads((mut / "panel_mutants.json").read_text())
old_pins = json.loads((mut / "pin_mutants.json").read_text())

# The old breaks whose text the round changed, rewritten for the new lines.
panel_moved = {
    "null-lens-dropped": ["    lenses.push({ key: lens.key, agent_type: lens.agentType, status: 'null', findings: 0, summary: '', head_seen: '',\n      head_ok: false })\n", ""],
    "inference-verified": ["const toCheck = findings.filter(f => f.check === null)", "const toCheck = findings.slice()"],
    "args-unchecked": ["typeof args.diff !== 'string' || !args.diff.startsWith('/') || ", ""],
    "relative-allowed": [" || !args.diff.startsWith('/') ||", " ||"],
}
panel = [[n, *panel_moved.get(n, [o, new])] for n, o, new in old_panel]
panel += [
    # the head
    ["head-unchecked", "|| typeof args.head !== 'string'\n    || !SHA.test(args.head)) {", ") {"],
    ["head-unanchored", "new RegExp('^[0-9a-f]{40}$')", "new RegExp('[0-9a-f]{40}')"],
    ["head-anycase", "new RegExp('^[0-9a-f]{40}$')", "new RegExp('^[0-9a-fA-F]{40}$')"],
    ["head-not-in-lens-prompt", "at commit ${HEAD}: first run", "at the head: first run"],
    ["head-not-in-verify-prompt", "at commit ${HEAD}, the head of the change", "at the head of the change"],
    ["head-not-returned", "return { schema: 'review-panel/1', head: HEAD,", "return { schema: 'review-panel/1',"],
    ["lens-head-unchecked", "head_seen: seen, head_ok: seen === HEAD })", "head_seen: seen, head_ok: true })"],
    ["lens-head-untrimmed", "answer.head.trim() : ''", "answer.head : ''"],
    ["lens-head-not-logged", "if (seen !== HEAD) log(`review-panel: the lens", "if (false) log(`review-panel: the lens"],
    ["verifier-head-unchecked", "note: '', head_seen: seen, head_ok: seen === HEAD }", "note: '', head_seen: seen, head_ok: true }"],
    ["verifier-head-not-logged", "if (ok && seen !== HEAD) log(", "if (false) log("],
    ["wrong-head-uncounted", "lenses_wrong_head: lenses.filter(l => l.status === 'ok' && !l.head_ok).length,", "lenses_wrong_head: 0,"],
    # the read-only list
    ["command-not-filtered", "const why = notRerunnable(f.evidence.command)", "const why = null"],
    ["dq-dollar", "['$', '`', '\\\\', '!']", "['`', '\\\\', '!']"],
    ["dq-backtick", "['$', '`', '\\\\', '!']", "['$', '\\\\', '!']"],
    ["dq-backslash", "['$', '`', '\\\\', '!']", "['$', '`', '!']"],
    ["dq-bang", "['$', '`', '\\\\', '!']", "['$', '`', '\\\\']"],
    ["unclosed-quote-ok", "if (j < 0) return null", "if (j < 0) return out"],
    ["tilde-anywhere", "((c === '~' || c === '^') && cur && ALNUM.includes(cur[cur.length - 1]))", "(c === '~' || c === '^')"],
    ["tilde-after-any", "&& cur && ALNUM.includes(cur[cur.length - 1]))", "&& cur)"],
    ["plain-glob", "const PLAIN = ALNUM + '_.,:=@%+/-'", "const PLAIN = ALNUM + '_.,:=@%+/-*?['"],
    ["plain-operators", "const PLAIN = ALNUM + '_.,:=@%+/-'", "const PLAIN = ALNUM + '_.,:=@%+/-;|&<>(){}$#\\n\\\\'"],
    ["quiet-mid-word", "const quiet = cur === null && QUIET.find(", "const quiet = QUIET.find("],
    ["quiet-suffix", "(i + q.length === cmd.length || ' \\t'.includes(cmd[i + q.length]))", "true"],
    ["quiet-extra", "const QUIET = ['2>&1', '2>/dev/null']", "const QUIET = ['2>&1', '2>/dev/null', '>', '1>&2']"],
    ["reads-python", "['shasum', []], ['sha256sum', []], ['diff', []],", "['shasum', []], ['sha256sum', []], ['diff', []], ['python3', []],"],
    ["reads-tail", "['grep', []], ['cat', []], ['head', []],", "['grep', []], ['cat', []], ['head', []], ['tail', []],"],
    ["git-status", "['log', 'show', 'diff', 'rev-parse',", "['log', 'show', 'diff', 'status', 'rev-parse',"],
    ["git-any-sub", "if (!subs.includes(w[1])) return", "if (false) return"],
    ["git-refused-off", "return refused ? `git ${w[1]} ${refused} writes a file or starts a program` : null", "return null"],
    ["git-prefix-exact", "GIT_REFUSED.some(r => r.startsWith(name))", "GIT_REFUSED.includes(name)"],
    ["git-equals-kept", "const name = a.split('=')[0]", "const name = a"],
    ["git-short-words", "return name.length > 2 &&", "return name.length > 1 &&"],
    ["git-no-output", "const GIT_REFUSED = ['--output', ", "const GIT_REFUSED = ["],
    ["git-no-ext-diff", "'--ext-diff', '--textconv',", "'--textconv',"],
    ["git-no-textconv", "'--ext-diff', '--textconv',", "'--ext-diff',"],
    ["git-no-filters", "'--filters', '--open-files-in-pager'", "'--open-files-in-pager'"],
    ["no-list-in-lens-prompt", "runs a command again only when it is one plain read: one of ${readList()}", "runs a command again only when it is one plain read: one of git log"],
    ["no-list-in-verify-prompt", "is one plain read (one of ${readList()}, plain words)", "is one plain read (one of git log, plain words)"],
    ["lens-may-run-tests", "Do not run the change's code or tests, and do not", "Do not"],
    ["ledger-no-verb", "ledger.py agents --session <id>", "ledger.py --session <id>"],
]

pins_moved = {
    "comments-are-code": ['        if kind not in ("ws", "comment"):', '        if kind != "ws":'],
}
pins = [[n, *pins_moved.get(n, [o, new])] for n, o, new in old_pins]
pins += [
    ["regex-check-off", 'if (kind, text) == ("punct", "/") and not (out and _division(out[-1], keyword_close)):', "if False:"],
    ["regex-at-start-ok", "and not (out and _division(out[-1], keyword_close))", "and out and not _division(out[-1], keyword_close)"],
    ["division-no-tpl", 'if kind in ("num", "str", "tpl"):', 'if kind in ("num", "str"):'],
    ["division-no-str", 'if kind in ("num", "str", "tpl"):', 'if kind in ("num", "tpl"):'],
    ["division-keyword-ident", "return text not in _BEFORE_EXPRESSION", "return True"],
    ["no-return-keyword", '_BEFORE_EXPRESSION = {"return", ', "_BEFORE_EXPRESSION = {"],
    ["no-close-paren-division", 'return text == "]" or (text == ")" and not closes_keyword_paren)', 'return text == "]"'],
    ["no-bracket-division", 'return text == "]" or (text == ")" and not closes_keyword_paren)', 'return text == ")" and not closes_keyword_paren'],
    ["any-close-paren-divides", '(text == ")" and not closes_keyword_paren)', '(text == ")")'],
    ["no-if-paren", '_PAREN_KEYWORDS = {"if", ', "_PAREN_KEYWORDS = {"],
    ["no-while-paren", '"while", "for", "with", "await"}', '"for", "with", "await"}'],
    ["close-not-tracked", "                closes = parens.pop()", "                parens.pop()"],
    ["template-code-skipped", 'out += [("punct", "("), *tokens(src[start:stop]), ("punct", ")")]', "pass"],
    ["template-code-unwrapped", 'out += [("punct", "("), *tokens(src[start:stop]), ("punct", ")")]', "out += tokens(src[start:stop])"],
    ["slash-in-template-ok", '                if c == "/":\n                    raise', '                if False:\n                    raise'],
    ["flagged-off", 'if kind == "ident" and text in FLAGGED:', "if False:"],
    ["no-eval", 'FLAGGED = {"eval", ', "FLAGGED = {"],
    ["no-Function", '"Function", "arguments",', '"arguments",'],
    ["no-arguments", '"Function", "arguments",', '"Function",'],
    ["no-constructor", '"constructor", "this",', '"this",'],
    ["no-this", '"constructor", "this",', '"constructor",'],
    ["no-globalThis", '"globalThis", "global",', '"global",'],
    ["ternary-is-key", 'if nxt == ("punct", ":") and prev in (("punct", "{"), ("punct", ",")):', 'if nxt == ("punct", ":"):'],
    ["computed-key-ok", '            return ["an option that is no `key: value` or plain name, which the reader cannot read"]', "            continue"],
]
for name, data in (("panel_mutants_v2.json", panel), ("pin_mutants_v2.json", pins)):
    (mut / name).write_text(json.dumps(data, indent=1) + "\n")
    print(name, len(data))
