"""The delete text pass on prose (guard 0.7.0, step A1).

The text pass (`DELETE_RE`) is the 0.6.0 one with two exceptions: `del\\s*\\(` needs a word boundary
(`\\bdel\\s*\\(`), so "model (" stops asking, and `truncate` counts as SQL only where a statement can start,
so "may truncate the description" stops asking. Rows copied from the owner-approved case list.
"""

import pathlib

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[2]

# (kind, expected, text): `command` rows are command lines; `script` rows are the content of a script that
# `python3 <file>.py` names
CASES = [
    ("script", "silent", "# Data model (step 2.4)\nprint(\"x\")"),
    ("script", "silent", "result = load_model(path)\nprint(result)"),
    ("script", "silent", "# long items may truncate the description in the export\nprint(\"x\")"),
    ("script", "silent", "\"\"\"Notes: the export will truncate the title when it is too long.\"\"\""),
    ("script", "ask", "cache = {}\ndel (cache)"),
    ("script", "ask", "cache = {}\ndel(cache)"),
    ("script", "ask", "client.del(key)"),
    ("script", "ask", "import os\nos.remove(\"x\")"),
    ("script", "ask", "QUERY = \"truncate users\""),
    ("script", "ask", "cur.execute(\"TRUNCATE TABLE audit\")"),
    ("script", "ask", "BEGIN; truncate users;"),
    ("script", "ask", "truncate users;"),
    ("command", "silent", "echo \"this may truncate the output\""),
    ("command", "silent", "grep -n \"Data model (\" tools/tracker/tracker.py"),
    ("command", "silent", "python3 -c \"print(model (1))\""),
    ("command", "ask", "psql -c \"truncate users\""),
    ("command", "ask", "psql -c 'TRUNCATE TABLE x'"),
    ("command", "ask", "truncate -s 0 app.log"),
    ("command", "ask", "python3 -c \"del (x)\""),
    ("command", "ask", "node -e \"client.del('k')\""),
]

# Found by the fresh review of the branch: SQL and delete calls that asked at 0.6.1 and that the two narrowed
# expressions let pass. The upper-case keyword asks wherever it stands, `truncate table` too, the lower-case word
# anywhere on a command line that names a SQL client, and `del(` after an underscore. Prose stays silent.
REVIEW_CASES = [
    ("command", "ask", "echo truncate table audit | psql"),
    ("command", "ask", "echo truncate audit | psql"),
    ("command", "ask", "echo TRUNCATE audit | psql -d app"),
    ("command", "ask", "echo TRUNCATE audit > cleanup.sql"),
    ("command", "ask", "psql -c \"/* cleanup */ truncate audit\""),
    ("command", "ask", "psql -c \"DO $$ BEGIN TRUNCATE TABLE audit; END $$\""),
    ("command", "ask", "psql -c \"do $$ begin truncate audit; end $$\""),
    ("command", "ask", "printf 'begin;\\ntruncate audit;\\n' | psql"),
    ("command", "ask", "printf 'begin;\\ntruncate audit;\\n' | /usr/bin/mysql app"),
    ("command", "ask", "echo truncate t1 | hbase shell"),
    ("command", "ask", "docker exec db psql -c \"select 1 /* x */; -- y\ntruncate audit\""),
    ("command", "ask", "python3 -c \"redis_del(key)\""),
    ("command", "ask", "python3 -c \"cache_del(k)\""),
    ("script", "ask", "cur.execute(\"/* cleanup */ TRUNCATE TABLE audit\")"),
    ("script", "ask", "sql = \"do $$ begin truncate table audit; end $$\""),
    ("script", "ask", "redis_del(key)"),
    ("command", "silent", "git commit -m \"fix: do not truncate the title\""),
    ("command", "silent", "echo \"we will truncate the log\""),
    ("command", "silent", "mysqldump app > dump.sql && echo \"long rows may truncate here\""),
    ("script", "silent", "# the export may truncate long titles\nprint(\"x\")"),
    ("script", "silent", "result = remodel(x)\nprint(result)"),
    # the price of the client rule, as at 0.6.1: prose on a line that names a SQL client asks
    ("command", "ask", "psql -c \"select 1 -- then truncate later\""),
    # found by the review of the commits after that one: the client name counted only with a space or the end
    # of the line behind it; it counts as a word of its own, whatever stands behind it or in front of it
    ("command", "ask", "bash -c \"echo truncate audit | psql\""),
    ("command", "ask", "sh -c 'echo truncate audit | mysql'"),
    ("command", "ask", "x=$(echo truncate audit | psql)"),
    ("command", "ask", "echo truncate audit | psql;"),
    ("command", "ask", "echo truncate audit | psql<conn"),
    ("command", "ask", "(echo truncate audit | psql)"),
    ("command", "ask", "echo truncate audit | psql&"),
    ("command", "ask", "echo truncate audit | psql>out.txt"),
    ("command", "ask", "echo truncate audit | psql|tee log"),
    ("command", "ask", "echo truncate audit | `which psql`"),
    ("command", "ask", "echo truncate audit | \"psql\""),
    ("command", "ask", "echo truncate audit | psql.exe -d app"),
    ("command", "ask", "echo truncate audit | clickhouse-client"),
    ("command", "ask", "echo truncate audit | clickhouse-local"),
    ("command", "ask", "echo truncate t1 | hbase;"),
    ("command", "ask", "echo truncate audit | \\psql"),
    ("command", "ask", "echo truncate audit | bin\\psql.exe"),
    ("command", "ask", "echo truncate audit | {psql,cat}"),
    ("command", "ask", "echo truncate audit | $HOME/bin/psql"),
    ("command", "ask", "echo truncate audit |psql"),
    ("command", "silent", "pip show pymysql; echo \"may truncate the list\""),
    ("command", "silent", "cat ~/.psqlrc; echo \"will truncate output\""),
    ("command", "silent", "echo \"we will truncate the log\" > notes-mysql_old.txt"),
    ("command", "silent", "mysqladmin status; echo \"may truncate rows\""),
    # found while checking that fix: no list names every tool that takes the text. Outside quotes and in a
    # here-document the lower-case word asks wherever it stands, as at 0.6.1; prose stands inside quotes
    ("command", "ask", "gtruncate -s 0 app.log"),
    ("command", "ask", "sudo gtruncate -s 0 /var/log/x"),
    ("command", "ask", "hdfs dfs -truncate 0 /data/part-0"),
    ("command", "ask", "rados -p pool truncate obj 0"),
    ("command", "ask", "echo truncate users | pgcli"),
    ("command", "ask", "echo truncate users | python manage.py dbshell"),
    ("command", "ask", "echo truncate users | docker exec -i db sh -c 'exec $CLIENT'"),
    ("command", "ask", "echo begin\\; truncate users\\; commit | ysqlsh"),
    ("command", "ask", "echo the export may truncate long titles"),
    ("command", "ask", "pgcli <<EOF\n/* cleanup */ truncate users;\nEOF"),
    ("command", "ask", "bash <<'EOF'\necho truncate users | pgcli\nEOF"),
    ("command", "ask", "git commit -F - <<'EOF'\nfix: an in-place truncate and rewrite\nEOF"),
    ("command", "ask", "cat <<EOF > notes.txt\nit's done\nEOF\necho truncate users | pgcli"),
    ("command", "ask", "# don't wait\necho truncate users | pgcli"),
    ("command", "silent", "git commit -m \"it's fine\" -m \"don't truncate the title\""),
    ("command", "silent", "bash -c \"git commit -m \\\"do not truncate the title\\\"\""),
    ("command", "silent", "bash -c 'git commit -m \"do not truncate the title\"'"),
    ("command", "silent", "gh pr create --title x --body \"list items may truncate the description\""),
    ("command", "silent", "echo 'this may truncate the output' | tee notes.txt"),
    ("command", "silent", "git commit -m \"$(cat <<'EOF'\nfix: title\nEOF\n)\" && echo \"may truncate it\""),
    # what the cut still gives up: the word inside quotes, away from a statement start, no listed client
    ("command", "silent", "pgcli -c \"/* cleanup */ truncate users\""),
    # found by the review of that commit: its own expression for quoted strings took an apostrophe that is no
    # quote for one, and hid a substitution inside double quotes. The reader of the token rules decides now what
    # stands outside quotes, in the line and in every script it nests
    ("command", "ask", "echo don\\'t; echo truncate users | pgcli; echo won\\'t"),
    ("command", "ask", "echo $'a\\'b'; echo truncate users | pgcli; echo 'c'"),
    ("command", "ask", "# it's\necho truncate users | pgcli\n# that's"),
    ("command", "ask", "echo \"$(echo truncate users | pgcli)\""),
    ("command", "ask", "echo \"`echo truncate users | pgcli`\""),
    ("command", "ask", "bash -c \"echo truncate users | pgcli\""),
    ("command", "ask", "ssh db 'echo truncate users | pgcli'"),
    ("command", "ask", "eval \"echo truncate users | pgcli\""),
    ("command", "ask", "docker exec db sh -c 'echo truncate users | pgcli'"),
    ("command", "ask", "echo \"never closed truncate users | pgcli"),
    ("command", "silent", "bash -c 'echo \"this may truncate the output\"'"),
    ("command", "silent", "ssh host 'git commit -m \"do not truncate the title\"'"),
    ("command", "silent", "grep -n \"truncate\" tools/guard/guard.py"),
]
ALL_CASES = CASES + REVIEW_CASES


def _ev(guard, command, cwd):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
                        "tool_input": {"command": command}})


@pytest.mark.parametrize("kind,expected,text", ALL_CASES,
                         ids=[f"{c[0]}-{c[1]}-{i}" for i, c in enumerate(ALL_CASES)])
def test_case(guard, tmp_path, kind, expected, text):
    if kind == "script":
        (tmp_path / "step.py").write_text(text + "\n", encoding="utf-8")
        command = "python3 step.py"
    else:
        command = text
    got = guard.rule_delete_guard(_ev(guard, command, tmp_path), {})
    if expected == "silent":
        assert got is None, f"{kind} {text!r}: {got}"
    else:
        assert got is not None and got[0] == "ask", f"{kind} {text!r}: {got}"


@pytest.mark.parametrize("text", ["model (", "load_model(x)", "handel(", "may truncate the description",
                                  "echo \"this may truncate the output\"", "remodel(x)", "model2del(x)",
                                  "will truncate tables of contents"])
def test_prose_does_not_match_the_text_pass(guard, text):
    assert not guard.DELETE_RE.search(text), text


@pytest.mark.parametrize("text", ["del (x)", "del(x)", "client.del(key)", "psql -c \"truncate users\"",
                                  "psql -c 'TRUNCATE TABLE x'", "truncate users;", "BEGIN; truncate x",
                                  "cur.execute(\"truncate users\")", "x = 1\ntruncate users;",
                                  "then TRUNCATE audit", "we truncate table names", "redis_del(key)", "_del (x)"])
def test_code_and_sql_still_match_the_text_pass(guard, text):
    assert guard.DELETE_RE.search(text), text


@pytest.mark.parametrize("rel", ["tracker/tracker.py", "tracker/evidence_export.py"])
def test_the_tracker_sources_no_longer_match(guard, rel):
    """37 of a week's 117 asks came from one comment in tracker.py; evidence_export.py tripped on prose too."""
    text = (TOOLS / rel).read_text(encoding="utf-8")
    m = guard.DELETE_RE.search(text)
    assert m is None, f"{rel}: {m.group(0)!r}"
