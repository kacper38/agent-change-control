"""guard 0.12.2 (tracker item #90): an edit to an agent definition asks, as one to a workflow script does.

An agent type takes its tools and its prompt from its definition file, in a workflow and in an Agent call alike, and
the sha256 binding of 0.12.1 covers a workflow's script, not those files. Since 0.12.2 guard-config names them "an
agent definition": `.claude/agents` itself and every path below it (the repo's, a nested project's and the user's
`~/.claude/agents`), and every path at or below the folder a `.claude/agents` link of one of the path's folders
resolves to (`agents/` in this kit, where `.claude/agents` is a link to `../agents`). On the host a Write, an Edit,
a shell write or a GitHub file tool asks; in a box the edit is logged and the box merges no head that changes one,
the link read in the judge's folder (the session cannot move it); in cloud it is a deny. Reads stay silent.

The rows were written before the code; the commands are data, nothing runs. Row ids: A1 file tools, A2 shell
writes, A3 the GitHub file tool, A4 box and cloud, A5 the neighbours that stay silent, M the box merge check.
"""
import importlib.util
import json
import os
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
CLASS = "an agent definition"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("_g0122_guard_0120", HERE / "test_guard_0120.py")
BP = G.BP
judge = G.judge  # the fixtures of 0.12.0: a judge folder and a work clone on feat/x
work = G.work


def _layout(root: pathlib.Path, name: str) -> None:
    """`kit`: `.claude/agents` is a link to `../agents`, as in this kit; `plain`: a folder `agents/` and no link;
    `real`: `.claude/agents` is a folder of its own; `-`: neither."""
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    if name in ("kit", "plain"):
        (root / "agents").mkdir(exist_ok=True)
        (root / "agents" / "code-reviewer.md").write_text("---\nname: code-reviewer\ntools: Read\n---\nReview.\n")
    if name == "kit":
        os.symlink(os.path.join("..", "agents"), root / ".claude" / "agents")
    if name == "real":
        (root / ".claude" / "agents").mkdir()
        (root / ".claude" / "agents" / "code-reviewer.md").write_text("---\nname: code-reviewer\n---\n")


# id | profile | layout of the work clone | expected | tool | input ({w} the work clone, {h} the user's home)
ROWS = r"""
A1 | host | kit | ask | Write | {"file_path": "{w}/.claude/agents/x.md", "content": "x"}
A1 | host | kit | ask | Edit | {"file_path": "{w}/.claude/agents/code-reviewer.md", "old_string": "a", "new_string": "b"}
A1 | host | kit | ask | Write | {"file_path": "{w}/agents/x.md", "content": "x"}
A1 | host | kit | ask | Edit | {"file_path": "{w}/agents/code-reviewer.md", "old_string": "a", "new_string": "b"}
A1 | host | kit | ask | Write | {"file_path": "{w}/agents/sub/x.md", "content": "x"}
A1 | host | kit | ask | Write | {"file_path": "agents/x.md", "content": "x"}
A1 | host | kit | ask | Write | {"file_path": "{w}/AGENTS/X.md", "content": "x"}
A1 | host | kit | ask | Write | {"file_path": "{w}/.CLAUDE/Agents/X.md", "content": "x"}
A1 | host | real | ask | Write | {"file_path": "{w}/.claude/agents/x.md", "content": "x"}
A1 | host | - | ask | Write | {"file_path": "{w}/sub/project/.claude/agents/x.md", "content": "x"}
A1 | host | - | ask | Write | {"file_path": "{h}/.claude/agents/x.md", "content": "x"}
A1 | host | - | ask | Edit | {"file_path": "~/.claude/agents/x.md", "old_string": "a", "new_string": "b"}
# a shell write to the same paths; one that names the folder or the link writes inside it or moves the link
A2 | host | kit | ask | Bash | {"command": "sed -i s/a/b/ agents/code-reviewer.md"}
A2 | host | kit | ask | Bash | {"command": "echo x > agents/x.md"}
A2 | host | kit | ask | Bash | {"command": "tee -a .claude/agents/x.md < y"}
A2 | host | kit | ask | Bash | {"command": "cp /tmp/x.md agents/"}
A2 | host | kit | ask | Bash | {"command": "cp evil.md agents"}
A2 | host | kit | ask | Bash | {"command": "mv d .claude/agents"}
A2 | host | kit | ask | Bash | {"command": "ln -sfn /tmp/d .claude/agents"}
A2 | host | - | ask | Bash | {"command": "cp x.md ~/.claude/agents/"}
A3 | host | kit | ask | mcp__github__create_or_update_file | {"owner": "o", "repo": "r", "path": ".claude/agents/x.md", "content": "x", "message": "m", "branch": "feat/x"}
A3 | host | kit | ask | mcp__github__create_or_update_file | {"owner": "o", "repo": "r", "path": "agents/x.md", "content": "x", "message": "m", "branch": "feat/x"}
A4 | box | kit | logged | Write | {"file_path": "{w}/agents/x.md", "content": "x"}
A4 | box | kit | logged | Write | {"file_path": "{w}/.claude/agents/x.md", "content": "x"}
A4 | box | kit | logged | Bash | {"command": "sed -i s/a/b/ agents/code-reviewer.md"}
A4 | cloud | kit | deny | Write | {"file_path": "{w}/agents/x.md", "content": "x"}
A4 | cloud | kit | deny | Bash | {"command": "sed -i s/a/b/ .claude/agents/x.md"}
# neighbours: a read, a copy out, a folder of the same name no link names, a sibling of the same prefix
A5 | host | kit | silent | Read | {"file_path": "{w}/agents/code-reviewer.md"}
A5 | host | kit | silent | Bash | {"command": "cat agents/code-reviewer.md .claude/agents/code-reviewer.md"}
A5 | host | kit | silent | Bash | {"command": "cp agents/code-reviewer.md /tmp/x.txt"}
A5 | host | kit | silent | Write | {"file_path": "{w}/docs/agents/x.md", "content": "x"}
A5 | host | kit | silent | Write | {"file_path": "{w}/sub/agents/x.txt", "content": "x"}
A5 | host | kit | silent | Write | {"file_path": "{w}/agents-old/x.txt", "content": "x"}
A5 | host | kit | silent | Write | {"file_path": "{w}/.claude/agents-notes.md", "content": "x"}
A5 | host | kit | silent | Write | {"file_path": "{w}/.claude/skills/x/SKILL.md", "content": "x"}
A5 | host | plain | silent | Write | {"file_path": "{w}/agents/x.md", "content": "x"}
A5 | host | real | silent | Write | {"file_path": "{w}/agents/x.md", "content": "x"}
A5 | host | - | silent | Write | {"file_path": "{h}/.claude/agents-notes.txt", "content": "x"}
A5 | box | kit | silent | Read | {"file_path": "{w}/agents/code-reviewer.md"}
"""  # noqa: E501
TABLE = G._rows(ROWS)


@pytest.mark.parametrize("rid, prof, layout, expected, tool, text", TABLE,
                         ids=[f"{r[0]}-{r[1]}-{n}" for n, r in enumerate(TABLE)])
def test_the_row(guard, monkeypatch, judge, work, tmp_path, rid, prof, layout, expected, tool, text):
    home = tmp_path / "home"
    (home / ".claude" / "agents").mkdir(parents=True)
    _layout(work, layout)
    G._profile(guard, monkeypatch, judge, prof)
    monkeypatch.setenv("HOME", str(home))
    tool_input = json.loads(text.replace("{w}", str(work)).replace("{h}", str(home)))
    final, rows = BP._hook(guard, monkeypatch, BP._tool(work, tool, tool_input))
    assert G._word(final, rows) == expected, (final, rows)
    if expected in ("ask", "deny"):
        rules = rows[-1]["rules"]
        assert "guard-config" in rules or (tool.startswith("mcp__") and "github-tools" in rules), rows
        assert CLASS in final[1], final
    if expected == "logged":
        assert rows[-1]["rules"] == {"guard-config": "logged"}, rows


# ----------------------------------------------------------------------------
# M: a box merges no head that changes an agent definition; the link is read in the judge's folder
# ----------------------------------------------------------------------------

def _link(rel: str, target: str):
    def change(root):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, path)
    return change


# id | layout of the judge's folder | the head's change | expected | named in the deny
MERGE_ROWS = [
    ("M1-link-target", "kit", BP._write("agents/x.md"), "deny", "agents/x.md"),
    ("M2-below-the-target", "kit", BP._write("agents/sub/y.md"), "deny", "agents/sub/y.md"),
    ("M3-below-the-link", "-", BP._write(".claude/agents/x.md"), "deny", ".claude/agents/x.md"),
    ("M4-a-new-link", "-", _link(".claude/agents", "../docs"), "deny", ".claude/agents"),
    ("M5-no-link-in-the-judge", "plain", BP._write("agents/x.md"), "logged", None),
    ("M6-a-neighbour", "kit", BP._write("docs/agents.md"), "logged", None),
]


@pytest.mark.parametrize("rid, layout, change, expected, named", MERGE_ROWS, ids=[r[0] for r in MERGE_ROWS])
def test_a_box_merges_no_head_that_changes_an_agent_definition(guard, monkeypatch, judge, work, rid, layout,
                                                               change, expected, named):
    _layout(judge, layout)  # the work clone has no link: the judge's folder is what the check reads
    sha, base = BP._head_with(work, change)
    BP._receipt(work, sha, "COMMENT")
    BP._box(guard, monkeypatch, judge, BP._judged(base))
    final, rows = BP._hook(guard, monkeypatch, BP._bash(work, f"gh pr merge 76 --merge --match-head-commit {sha}"))
    assert BP._answer(final, rows) == expected, (rid, final, rows)
    if named:
        assert named in final[1] and CLASS in final[1], final[1]


# ----------------------------------------------------------------------------
# The class itself
# ----------------------------------------------------------------------------

def test_the_class_names_an_agent_definition(guard, tmp_path):
    root = tmp_path / "r"
    _layout(root, "kit")
    r = str(root)
    for path in (".claude/agents/x.md", ".claude/agents", "agents/x.md", "agents", "agents/sub/x.md"):
        assert guard.guard_config_class(str(root / path), root=r) == CLASS, path
    assert guard.guard_config_class("agents/x.md", root=r) == CLASS  # the merge check's root-relative form
    assert guard.guard_config_class("~/.claude/agents/x.md", root=r) == CLASS
    for path in ("agents-old/x.md", "docs/agents/x.md", ".claude/agents-notes.md", ".claude/skills/x/SKILL.md"):
        assert guard.guard_config_class(str(root / path), root=r) is None, path
    assert guard.guard_config_class("/r/.claude/workflows/review-panel.js") == "a workflow script"
    # a session in a subfolder reads the link of the folder above it; with no root no link is read at all
    (root / "docs").mkdir()
    assert guard.guard_config_class(str(root / "agents" / "x.md"), root=str(root / "docs")) == CLASS
    assert guard.guard_config_class(str(root / "agents" / "x.md")) is None
    assert guard.guard_config_class(str(root / ".claude" / "agents" / "x.md")) == CLASS


def test_the_class_reads_no_folder_the_path_names(guard, tmp_path, monkeypatch):
    # review of #90, round 1 (MAJOR): a path on a network mount must not make the hook touch that mount. The class
    # reads only the `.claude/agents` link of the call's folder and of the folders above it
    root = tmp_path / "r"
    _layout(root, "kit")
    seen = []
    for name in ("islink", "realpath", "exists", "isdir", "lexists"):
        real = getattr(os.path, name)
        monkeypatch.setattr(os.path, name, lambda p, *a, _real=real, **k: seen.append(str(p)) or _real(p, *a, **k))
    real_readlink = os.readlink  # the calls the class makes; realpath of a link it found follows only that link
    monkeypatch.setattr(os, "readlink", lambda p, *a, **k: seen.append(str(p)) or real_readlink(p, *a, **k))
    assert guard.guard_config_class("/net/host/share/agents/x.md", root=str(root)) is None
    # every look is the call's folder, a folder above it or a path inside it (Python 3.9's realpath of the link it
    # found also looks at each folder of the link's own path); none is a folder the written path names
    above = {str(root), *map(str, root.parents)}
    links = {os.path.join(d, ".claude", "agents") for d in above}
    outside = [p for p in seen if p not in above | links and not p.startswith(str(root) + os.sep)]
    assert str(root / ".claude" / "agents") in seen and outside == [], outside


def test_a_nested_project_link_is_a_named_limit(guard, tmp_path):
    # DECISIONS.md, 2026-11-24 (item #90): a link below the call's folder is not read; `.claude/agents/**` of the
    # nested project still asks by its parts
    root = tmp_path / "r"
    _layout(root / "sub", "kit")
    assert guard.guard_config_class(str(root / "sub" / "agents" / "x.md"), root=str(root)) is None
    assert guard.guard_config_class(str(root / "sub" / ".claude" / "agents" / "x.md"), root=str(root)) == CLASS
    assert guard.guard_config_class(str(root / "sub" / "agents" / "x.md"), root=str(root / "sub")) == CLASS


def test_a_link_loop_or_a_nul_byte_is_no_crash(guard, tmp_path):
    root = tmp_path / "r"
    (root / ".claude").mkdir(parents=True)
    os.symlink("agents", root / ".claude" / "agents")  # .claude/agents -> .claude/agents: a loop
    r = str(root)
    assert guard.guard_config_class(str(root / "docs" / "x.md"), root=r) is None
    assert guard.guard_config_class(str(root / "docs" / "x\0.md"), root=r) is None
    assert guard.guard_config_class(str(root / ".claude" / "agents" / "x\0.md"), root=r) == CLASS


# ----------------------------------------------------------------------------
# Never weaker: the corpus answers as before but for the five inputs that are an agent definition
# ----------------------------------------------------------------------------

def _listed(changes: dict) -> set:
    return {rid for (rid, _which), (_old, _new, why) in changes.items() if why.startswith("#90")}


def test_every_change_of_0122_is_an_agent_definition_and_none_is_left_out():
    """The never-weaker checks of 0.9.0 (test_never_weaker.py), 0.10.0 (test_box_profile.py) and 0.11.0
    (test_guard_0120.py) hold at 0.12.2; the inputs whose answer changes are listed there (stricter only) or, for
    0.10.0, left out by the same reading of the path. That reading (a plain string test, not the code under test)
    finds exactly the listed inputs in each baseline."""
    nw = BP.NW
    for name, baseline, listed in (
            ("0.9.0", nw._baseline(), _listed(nw._changes())),
            ("0.10.0", BP._baseline(), _listed(G._changed())),
            ("0.11.0", G._baseline(), _listed(G._changed()))):
        agents = {row["id"] for row in baseline if BP._agent_definition(row["in"])}
        assert len(listed) == 5 and agents == listed, (name, sorted(agents ^ listed))


def test_the_version_is_0_12_2(guard):
    assert guard.VERSION == "0.12.2"
