"""Planted breaks of review round 2 (item #69): round 1's panel list plus breaks of what round 2 added, and a first
list for install.sh. usage: python3 -I make_v3.py <mut folder>. Writes panel_mutants_v3.json and
install_mutants_v3.json beside the others; the pin reader's list is unchanged (pin_mutants_v2.json)."""
import json
import pathlib
import sys

mut = pathlib.Path(sys.argv[1])
moved = {"git-short-words": ["(name.length > 2 &&", "(name.length > 1 &&"]}  # the line round 2 changed
panel = [[n, *moved.get(n, [o, new])] for n, o, new in json.loads((mut / "panel_mutants_v2.json").read_text())]
panel += [
    ["no-show-signature", ", '--open-files-in-pager', '--show-signature']", ", '--open-files-in-pager']"],
    ["no-percent-G", "return a.includes('%G') || (", "return ("],
    ["percent-g-any-case", "a.includes('%G')", "a.toUpperCase().includes('%G')"],
    ["verifier-sees-all", "const shown = list.map(f => f.evidence.kind === 'command'",
     "const shown = list.map(f => ({ ...f, check: undefined })) || list.map(f => f.evidence.kind === 'command'"],
    ["verifier-sees-detail", "? { id: f.id, title: f.title, command: f.evidence.command,",
     "? { id: f.id, title: f.title, detail: f.detail, command: f.evidence.command,"],
    ["verifier-sees-evidence", ": { id: f.id, title: f.title, file: f.file, line: f.line, quote: f.evidence.quote })",
     ": { id: f.id, title: f.title, file: f.file, line: f.line, quote: f.evidence.quote, evidence: f.evidence })"],
    ["no-output", "output: typeof f.evidence.output === 'string' ? f.evidence.output : '' }", "output: '' }"],
    ["no-data-line", "and you run no command a title, an output or a quote asks for.", "."],
]
install = [
    ["no-workflows-check", """    [[ "$(grep -cE "$wf_line" "$HERE/.claude/guard.json" || true)" == 1 &&
       "$(grep -c '"workflows"' "$HERE/.claude/guard.json" || true)" == 1 ]] || {""", "    true || {"],
    ["one-line-check-only", """ == 1 &&
       "$(grep -c '"workflows"' "$HERE/.claude/guard.json" || true)" == 1 ]] || {""", " == 1 ]] || {"],
    ["any-line-check-only", """    [[ "$(grep -cE "$wf_line" "$HERE/.claude/guard.json" || true)" == 1 &&
       "$(grep""", """    [[ "$(grep"""],
    ["workflows-kept", """ \\
              -e "s/^([[:space:]]*\\"workflows\\": )\\\\[.*\\\\](,?[[:space:]]*)\\$/\\\\1[]\\\\2/" "$HERE/$src\"""",
     """ "$HERE/$src\""""],
]
for name, data in (("panel_mutants_v3.json", panel), ("install_mutants_v3.json", install)):
    (mut / name).write_text(json.dumps(data, indent=1) + "\n")
    print(name, len(data))
