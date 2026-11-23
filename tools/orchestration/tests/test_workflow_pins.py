"""Plan step 1.5 (tracker item #69, criterion 4): every `agent()` call in `.claude/workflows/*.js` names a model, or
an agent type whose `.claude/agents/<type>.md` pins one, and `meta` is a literal; and each workflow `.claude/guard.json`
lists is bound to its committed file (guard 0.12.1). The scripts are read as text by a small tokenizer; nothing runs.

What the reader holds to, so that a pin cannot hide: the options of a call are an object literal written at the call
(no variable, no spread), `model` is a string literal of a known tier or a `claude-` id, `agentType` a string
literal; the name `agent` appears only as a call (no alias, no own function of that name); a nested `workflow()`
names a saved workflow by a string literal (its own file is read here too). Comments and the text of strings are no
code; the code inside a template's `${…}` is. What the reader cannot read fails the script, never passes it: a `/`
where a regular expression literal may start (write `new RegExp('…')`), a `/` inside `${…}`, and the names that
reach code without naming it (`eval`, `Function`, `arguments`, `constructor`, `this`, `globalThis`, …), wherever
they stand. Limit: it reads plain scripts and is no sandbox; a script built to hide a call (a computed member such as
x['constr' + 'uctor'] reaching a global `agent`, if the runtime has one) is for the review that writes the sha256
(review round 1 of item #69)."""
import hashlib
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".claude" / "workflows"
AGENTS = ROOT / ".claude" / "agents"
TIERS = {"opus", "sonnet", "haiku", "fable"}
_TOKEN = re.compile(r"""
    (?P<ws>\s+) | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<str>'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*")
  | (?P<num>\d[\w.]*) | (?P<ident>[A-Za-z_$][\w$]*)
  | (?P<punct>\.\.\.|=>|===|!==|==|!=|&&|\|\||\?\?|\?\.|[{}()\[\],:;.=+\-*/<>!?&|%^~])
""", re.S | re.X)
# Words after which a `/` starts a regular expression literal, and those whose `( … )` a regular expression may follow.
_BEFORE_EXPRESSION = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do",
                      "else", "yield", "await"}
_PAREN_KEYWORDS = {"if", "while", "for", "with", "await"}
# Names that reach code or a scope without writing `agent`: any use fails, as a property too.
FLAGGED = {"eval", "Function", "arguments", "constructor", "this", "globalThis", "global", "self", "window", "with",
           "import", "require"}


def _template_end(src: str, i: int) -> tuple:
    """(the index after the template literal that starts at src[i] == '`', the (start, stop) of each `${...}` in it);
    a `/` inside `${...}` (a comment, a regular expression, a division) is refused, so the closing } is never
    guessed wrong."""
    spans = []
    i += 1
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1, spans
        if src.startswith("${", i):
            depth, i = 1, i + 2
            start = i
            while depth:
                if i >= len(src):
                    raise ValueError("an unclosed ${ in a template literal")
                c = src[i]
                if c in "'\"":
                    m = _TOKEN.match(src, i)
                    if not m or m.lastgroup != "str":
                        raise ValueError(f"an unclosed string at {i}")
                    i = m.end()
                    continue
                if c == "`":
                    i = _template_end(src, i)[0]
                    continue
                if c == "/":
                    raise ValueError(f"a / inside ${{...}} at {i}, which the reader cannot read")
                depth += {"{": 1, "}": -1}.get(c, 0)
                i += 1
            spans.append((start, i - 1))
            continue
        i += 1
    raise ValueError("an unclosed template literal")


def _division(prev: tuple, closes_keyword_paren: bool) -> bool:
    """Whether a `/` after the token prev divides; else a regular expression literal may start there."""
    kind, text = prev
    if kind in ("num", "str", "tpl"):
        return True
    if kind == "ident":
        return text not in _BEFORE_EXPRESSION
    return text == "]" or (text == ")" and not closes_keyword_paren)


def tokens(src: str) -> list:
    """(kind, text) for every token but blanks and comments; kind is str, tpl, num, ident or punct. The code of each
    `${...}` of a template follows its tpl token, in parentheses."""
    out, i, parens, keyword_close = [], 0, [], False
    while i < len(src):
        if src[i] == "`":
            end, spans = _template_end(src, i)
            out.append(("tpl", src[i:end]))
            for start, stop in spans:
                out += [("punct", "("), *tokens(src[start:stop]), ("punct", ")")]
            i, keyword_close = end, False
            continue
        m = _TOKEN.match(src, i)
        if not m:
            raise ValueError(f"no token at {i}: {src[i:i + 20]!r}")
        kind, text = m.lastgroup, m.group()
        if kind not in ("ws", "comment"):
            if (kind, text) == ("punct", "/") and not (out and _division(out[-1], keyword_close)):
                raise ValueError(f"a regular expression literal at {i}, which the reader cannot read "
                                 "(write new RegExp('...'))")
            closes = False
            if (kind, text) == ("punct", "("):
                parens.append(bool(out) and out[-1][0] == "ident" and out[-1][1] in _PAREN_KEYWORDS)
            elif (kind, text) == ("punct", ")") and parens:
                closes = parens.pop()
            out.append((kind, text))
            keyword_close = closes
        i = m.end()
    return out


def _close(toks: list, i: int) -> int:
    """The index of the bracket that closes the one at toks[i]."""
    pairs, depth = {"(": ")", "[": "]", "{": "}"}, []
    for j in range(i, len(toks)):
        kind, text = toks[j]
        if kind != "punct":
            continue
        if text in pairs:
            depth.append(pairs[text])
        elif text in ")]}":
            if not depth or depth.pop() != text:
                raise ValueError(f"an unbalanced {text}")
            if not depth:
                return j
    raise ValueError("an unclosed bracket")


def _split(toks: list) -> list:
    """The top-level, comma-separated parts of a token list (an argument list or an object's body)."""
    parts, cur, depth = [], [], 0
    for kind, text in toks:
        if kind == "punct" and text in "([{":
            depth += 1
        elif kind == "punct" and text in ")]}":
            depth -= 1
        if depth == 0 and (kind, text) == ("punct", ","):
            parts.append(cur)
            cur = []
        else:
            cur.append((kind, text))
    if cur:
        parts.append(cur)
    return parts


def _literal(value: list):
    """The text of a value that is one string literal, else None."""
    if len(value) == 1 and value[0][0] == "str":
        return value[0][1][1:-1]
    return None


def pinned_agent(name: str) -> bool:
    path = AGENTS / f"{name}.md"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or not path.is_file():
        return False
    head = path.read_text(encoding="utf-8").split("---")
    return len(head) > 2 and bool(re.search(r"(?m)^model:\s*\S", head[1]))


def _options(opts: list) -> list:
    """What is wrong with the options of one agent() call: [] when the call names a pinned model or agent type."""
    if not opts or opts[0] != ("punct", "{") or _close(opts, 0) != len(opts) - 1:
        return ["the options are no object literal written at the call"]
    props = {}
    for part in _split(opts[1:-1]):
        if part and part[0] == ("punct", "..."):
            return ["a spread in the options can carry or override the model"]
        if len(part) >= 3 and part[0][0] in ("ident", "str") and part[1] == ("punct", ":"):
            props[part[0][1].strip("'\"")] = part[2:]
        elif len(part) == 1 and part[0][0] == "ident":  # {model} shorthand: a variable
            props[part[0][1]] = part
        else:  # a computed key ([k]: v), a method or a getter: a later one could set the model (review round 1)
            return ["an option that is no `key: value` or plain name, which the reader cannot read"]
    model = _literal(props["model"]) if "model" in props else None
    if "model" in props and model is None:
        return ["`model` is no string literal"]
    if model is not None:
        return [] if model in TIERS or model.startswith("claude-") else [f"`model` {model!r} is no known tier"]
    if "agentType" not in props:
        return ["the call names neither `model` nor `agentType`"]
    agent_type = _literal(props["agentType"])
    if agent_type is None:
        return ["`agentType` is no string literal and no `model` is named"]
    return [] if pinned_agent(agent_type) else [f"the agent type {agent_type!r} pins no model in .claude/agents/"]


def problems(src: str) -> list:
    """Every reason the script fails step 1.5; [] for a script that passes."""
    try:
        return _problems(tokens(src))
    except ValueError as exc:
        return [f"unreadable: {exc}"]


def _problems(toks: list) -> list:
    out = []
    head = [("ident", "export"), ("ident", "const"), ("ident", "meta"), ("punct", "="), ("punct", "{")]
    if toks[:5] != head:
        out.append("the script does not begin with `export const meta = {`")
    else:
        end = _close(toks, 4)
        for n, (kind, text) in enumerate(toks[5:end], start=5):
            nxt = toks[n + 1] if n + 1 < len(toks) else ("", "")
            if kind in ("str", "num") or (kind == "punct" and text in "{}[],:-"):
                continue
            if kind == "ident" and (text in ("true", "false", "null") or nxt == ("punct", ":")):
                continue
            out.append(f"`meta` is no literal: {text[:40]!r}")
            break
    for n, (kind, text) in enumerate(toks):
        if kind == "ident" and text in FLAGGED:
            out.append(f"`{text}` can reach code the reader does not see; a workflow script does not use it")
            continue
        if kind != "ident" or text not in ("agent", "workflow"):
            continue
        prev = toks[n - 1] if n else ("", "")
        nxt = toks[n + 1] if n + 1 < len(toks) else ("", "")
        if prev in (("punct", "."), ("punct", "?.")):
            continue  # a property of another object
        if nxt == ("punct", ":") and prev in (("punct", "{"), ("punct", ",")):
            continue  # an object key; `c ? agent : x` is no key (review round 1)
        if nxt != ("punct", "(") or prev == ("ident", "function"):
            out.append(f"`{text}` is used other than as a call (an alias or an own definition hides the pin)")
            continue
        args = _split(toks[n + 2:_close(toks, n + 1)])
        if text == "workflow":
            name = _literal(args[0]) if args else None
            if name is None or not (WORKFLOWS / f"{name}.js").is_file():
                out.append("a nested workflow() names no saved workflow of .claude/workflows/ by a string literal")
            continue
        if len(args) < 2:
            out.append("an agent() call without options names no model")
            continue
        out.extend(f"agent() call {sum(1 for t in toks[:n] if t == ('ident', 'agent')) + 1}: {why}"
                   for why in _options(args[1]))
    return out


def scripts() -> list:
    return sorted(WORKFLOWS.glob("*.js"))


def test_there_is_a_workflow_to_check():
    assert "review-panel.js" in [p.name for p in scripts()]


@pytest.mark.parametrize("path", scripts(), ids=lambda p: p.name)
def test_every_agent_call_is_pinned_and_meta_is_a_literal(path):
    assert problems(path.read_text(encoding="utf-8")) == []


def binding_problems(cfg: dict, folder: pathlib.Path) -> list:
    """Why an entry of `workflows` does not bind its name to the file in `folder` (guard 0.12.1)."""
    out = []
    for entry in cfg.get("workflows", []):
        if not isinstance(entry, dict) or set(entry) != {"name", "sha256"}:
            out.append(f"an entry that is no {{name, sha256}}: {entry!r}")
            continue
        path = folder / f"{entry['name']}.js"
        if not path.is_file():
            out.append(f"{entry['name']}: no file {path.name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            out.append(f"{path.name} changed after its sha256 was written: review it, then run "
                       f"`shasum -a 256 .claude/workflows/{path.name}` and write the value into .claude/guard.json")
    return out


def test_each_listed_workflow_is_bound_to_its_committed_file():
    cfg = json.loads((ROOT / ".claude" / "guard.json").read_text(encoding="utf-8"))
    assert binding_problems(cfg, WORKFLOWS) == []
    assert "review-panel" in [e["name"] for e in cfg["workflows"]]  # criterion 6 of item #69


def test_a_stale_or_missing_binding_fails(tmp_path):
    (tmp_path / "a.js").write_text("x\n", encoding="utf-8")
    good = hashlib.sha256(b"x\n").hexdigest()
    assert binding_problems({"workflows": [{"name": "a", "sha256": good}]}, tmp_path) == []
    assert "changed after" in binding_problems({"workflows": [{"name": "a", "sha256": "0" * 64}]}, tmp_path)[0]
    assert "no file" in binding_problems({"workflows": [{"name": "b", "sha256": good}]}, tmp_path)[0]
    assert "no {name, sha256}" in binding_problems({"workflows": ["a"]}, tmp_path)[0]


META = "export const meta = {name: 'x', description: 'y', phases: [{title: 'A', model: 'opus'}]}\n"


@pytest.mark.parametrize("body, why", [
    ("await agent('go')", "an agent() call without options names no model"),
    ("await agent('go', {label: 'a'})", "the call names neither `model` nor `agentType`"),
    ("const o = {model: 'opus'}\nawait agent('go', o)", "the options are no object literal written at the call"),
    ("await agent('go', {...o, model: 'opus'})", "a spread in the options can carry or override the model"),
    ("await agent('go', {model: 'opus', ...o})", "a spread in the options can carry or override the model"),
    ("const M = 'opus'\nawait agent('go', {model: M})", "`model` is no string literal"),
    ("await agent('go', {model})", "`model` is no string literal"),
    ("await agent('go', {model: 'gpt-5'})", "`model` 'gpt-5' is no known tier"),
    ("await agent('go', {agentType: 'no-such-agent'})", "pins no model in .claude/agents/"),
    ("await agent('go', {agentType: t})", "`agentType` is no string literal and no `model` is named"),
    ("const a = agent\nawait a('go', {model: 'opus'})", "is used other than as a call"),
    ("function agent(p) { return p }\nawait agent('go', {model: 'opus'})", "is used other than as a call"),
    ("await workflow({scriptPath: '/tmp/x.js'})", "a nested workflow() names no saved workflow"),
    ("await workflow('no-such-workflow')", "a nested workflow() names no saved workflow"),
    ("const a = c ? agent : null\nawait a('go', {})", "is used other than as a call"),
    ("await agent('go', {model: 'opus', ['model']: m})", "which the reader cannot read"),
    ("await agent('go', {model: 'opus', get agentType() { return t }})", "which the reader cannot read"),
    ("await agent('go', {model: 'opus', model: m})", "`model` is no string literal"),
    # review round 1 of item #69: each of these passed the reader at ae370d8 and calls agent() with no model
    ("const s = `${await agent('go')}`", "an agent() call without options names no model"),
    ("const s = `a ${`b ${await agent('go')}`}`", "an agent() call without options names no model"),
    ("const s = `${agent}`", "is used other than as a call"),
    ("const r = /`/\nawait agent('go')\nconst q = /`/", "a regular expression literal"),
    ("const r = /'/; await agent('go'); const q = /'/", "a regular expression literal"),
    ("if (c) /'/.test(s); await agent('go'); const q = /'/", "a regular expression literal"),
    ("while (c) /'/.test(s)", "a regular expression literal"),
    ("const f = () => /x/", "a regular expression literal"),
    ("return /x/", "a regular expression literal"),
    ("/x/.test(s)", "a regular expression literal"),
    ("const o = {}\n/'/.test(s); await agent('go'); /'/", "a regular expression literal"),
    ("const s = `${1 /* } */ + await agent('go')}`", "a / inside ${...}"),
    ("await agent(`${0, {model: 'opus'}}`)", "an agent() call without options names no model"),
    ("const s = `${a / b}`", "a / inside ${...}"),
    ("await eval('agent')('go')", "`eval` can reach code"),
    ("await arguments[0]('go')", "`arguments` can reach code"),
    ("await (async () => 1).constructor('return agent')()('go')", "`constructor` can reach code"),
    ("await new Function('return agent')()('go')", "`Function` can reach code"),
    ("await globalThis.agent('go')", "`globalThis` can reach code"),
    ("await this.agent('go')", "`this` can reach code"),
])
def test_a_script_without_a_pin_fails(body, why):
    found = problems(META + body + "\n")
    assert found and all(why in f for f in found[-1:]), found


@pytest.mark.parametrize("head, why", [
    ("export const meta = {name: NAME, description: 'y'}\n", "`meta` is no literal"),
    ("export const meta = {name: 'x', description: String(1)}\n", "`meta` is no literal"),
    ("export const meta = {name: `x${1}`, description: 'y'}\n", "`meta` is no literal"),
    ("export const meta = {...base, name: 'x'}\n", "`meta` is no literal"),
    ("const meta = {name: 'x'}\n", "does not begin with `export const meta = {`"),
    ("// first\nconst x = 1\nexport const meta = {name: 'x'}\n", "does not begin with `export const meta = {`"),
])
def test_a_meta_that_is_no_literal_fails(head, why):
    found = problems(head + "await agent('go', {model: 'opus'})\n")
    assert any(why in f for f in found), found


@pytest.mark.parametrize("body", [
    "await agent('go', {model: 'opus'})",
    "await agent('go', {label: `a:${k}`, model: 'sonnet', schema: S})",
    "await agent('go', {agentType: 'code-reviewer'})",
    "await agent(`x ${JSON.stringify({a: `nested ${1}`})}`, {model: 'claude-opus-5-5'})",
    "// agent('in a comment')\nconst s = 'agent(in a string)'\nconst o = {agent: 1}\nlog(o.agent)",
    "await parallel([1, 2].map(i => () => agent(`p${i}`, {phase: 'A', model: 'haiku'})))",
    "await workflow('review-panel', {diff: '/tmp/x.diff'})",
    "await agent('go', {model: 'opus' /* the tier */, label: 'a' // why\n})",
    # a / that divides, and a pattern written as a string (review round 1)
    "const h = n / 2\nconst k = (n + 1) / 2 / x[0] / 'a'.length / `b`.length\nconst q = x[1] /= 2",
    "const d = 3 / 'a' / `b` / 2",
    "const re = new RegExp('^[0-9a-f]{40}$')\nconst s = `${a} / ${b}`",
    "await agent(`${JSON.stringify({a: 1})}`, {model: 'opus'})",
    "const t = typeof_x / 2",
])
def test_a_pinned_script_passes(body):
    assert problems(META + body + "\n") == []


def test_a_comment_in_meta_is_no_code():
    head = "export const meta = {\n  name: 'x', // the name\n  /* shown */ description: 'y',\n}\n"
    assert problems(head + "await agent('go', {model: 'opus'})\n") == []


@pytest.mark.parametrize("src", ["/'/", "/x/.test(s)"])
def test_a_slash_that_begins_the_text_is_a_regular_expression(src):
    # review round 1: the first token has nothing before it to divide
    with pytest.raises(ValueError, match="a regular expression literal at 0"):
        tokens(src)
