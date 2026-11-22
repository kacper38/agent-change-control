"""Plan step 1.5 (tracker item #69, criterion 4): every `agent()` call in `.claude/workflows/*.js` names a model, or
an agent type whose `.claude/agents/<type>.md` pins one, and `meta` is a literal; and each workflow `.claude/guard.json`
lists is bound to its committed file (guard 0.12.1). The scripts are read as text by a small tokenizer; nothing runs.

What the reader holds to, so that a pin cannot hide: the options of a call are an object literal written at the call
(no variable, no spread), `model` is a string literal of a known tier or a `claude-` id, `agentType` a string
literal; the name `agent` appears only as a call (no alias, no own function of that name); a nested `workflow()`
names a saved workflow by a string literal (its own file is read here too). Comments and the text of strings are no
code. Limits: a regular expression literal is read as code, so `agent(` inside one counts as a call (it can only
fail the test, never pass a script)."""
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


def _template_end(src: str, i: int) -> int:
    """The index after the template literal that starts at src[i] == '`', through `${...}` and nested literals."""
    i += 1
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i + 1
        if src.startswith("${", i):
            depth, i = 1, i + 2
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
                    i = _template_end(src, i)
                    continue
                depth += {"{": 1, "}": -1}.get(c, 0)
                i += 1
            continue
        i += 1
    raise ValueError("an unclosed template literal")


def tokens(src: str) -> list:
    """(kind, text) for every token but blanks and comments; kind is str, tpl, num, ident or punct."""
    out, i = [], 0
    while i < len(src):
        if src[i] == "`":
            end = _template_end(src, i)
            out.append(("tpl", src[i:end]))
            i = end
            continue
        m = _TOKEN.match(src, i)
        if not m:
            raise ValueError(f"no token at {i}: {src[i:i + 20]!r}")
        if m.lastgroup not in ("ws", "comment"):
            out.append((m.lastgroup, m.group()))
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
        if kind != "ident" or text not in ("agent", "workflow"):
            continue
        prev = toks[n - 1] if n else ("", "")
        nxt = toks[n + 1] if n + 1 < len(toks) else ("", "")
        if prev in (("punct", "."), ("punct", "?.")) or nxt == ("punct", ":"):
            continue  # a property of another object, or an object key
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
])
def test_a_pinned_script_passes(body):
    assert problems(META + body + "\n") == []


def test_a_comment_in_meta_is_no_code():
    head = "export const meta = {\n  name: 'x', // the name\n  /* shown */ description: 'y',\n}\n"
    assert problems(head + "await agent('go', {model: 'opus'})\n") == []
