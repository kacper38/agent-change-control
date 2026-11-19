#!/usr/bin/env python3
"""A design probe of the orchestrating session, never handed to an engineer and never copied into the repository:
the guard file of a commit with the smallest change per addendum topic, to see whether the drafted rows can hold
together with every frozen row before an engineer is asked for them.

usage: python3 -I make_proto.py <guard.py of the commit> <out guard.py> [<topic> ...]     topics: f37 f38 f39
       (no topic: all three)
"""
import sys

EDITS = {
    # F37: a pipe the reader of 0.8.0 reads (one simple command into `{ sh`) is left to _nc_fed
    # second form (the first one passed over a bar by the look of the command behind it, and so could make
    # `cat run.sh | { ssh -n build; sh; }` silent): the compound check leaves out exactly the bars through which
    # _nc_fed has read a script
    "f37": [(
        "    if cmds is not None and _nc_compound_pipe(rows, seps):\n"
        "        raise CommandNotRead(_PIPE_NOT_READ)\n"
        "    # (script, the environment it inherits)",
        "    read_bars: set = set()\n"
        "    # (script, the environment it inherits)",
    ), (
        "        fed, runner = _nc_fed(raw, toks, piped, bodies)\n"
        "        if not fed and toks in ([], [\"}\"]):\n",
        "        fed, runner = _nc_fed(raw, toks, piped, bodies)\n"
        "        if piped is not None and runner is piped:\n"
        "            read_bars.add(k + 1)\n"
        "        if not fed and toks in ([], [\"}\"]):\n",
    ), (
        "    for script, script_env in nested:\n"
        "        if (script, script_env) not in seen:",
        "    if cmds is not None and _nc_compound_pipe(rows, seps, read_bars):\n"
        "        raise CommandNotRead(_PIPE_NOT_READ)\n"
        "    for script, script_env in nested:\n"
        "        if (script, script_env) not in seen:",
    ), (
        "def _nc_compound_pipe(rows: list, seps: list) -> bool:\n",
        "def _nc_compound_pipe(rows: list, seps: list, read=frozenset()) -> bool:\n",
    ), (
        "        if bar < 0 or sep.replace(\"(\", \"\").replace(\")\", \"\") not in (\"|\", \"|&\"):\n"
        "            continue\n",
        "        if bar < 0 or sep.replace(\"(\", \"\").replace(\")\", \"\") not in (\"|\", \"|&\") or r in read:\n"
        "            continue\n",
    )],
    # F40 (applied after f37): a pipe the guard cannot read is a finding of the read, not its end. The read goes on
    # as at 0.8.0, every rule judges every command, a deny wins, and the ask is added where no deny was found
    "f40": [(
        "    envs: list[tuple[str, ...]] = []\n"
        "    try:\n"
        "        _nc_read(command, 0, out, set(), local, inputs, [], envs)\n"
        "    except CommandNotRead as exc:  # kept as a value so the second rule does not read the line again\n"
        "        return exc\n"
        "    return tuple(out), tuple(inputs), tuple(envs)\n",
        "    envs: list[tuple[str, ...]] = []\n"
        "    unread: list = []\n"
        "    try:\n"
        "        _nc_read(command, 0, out, set(), local, inputs, [], envs, (), unread)\n"
        "    except CommandNotRead as exc:  # kept as a value so the second rule does not read the line again\n"
        "        return exc\n"
        "    return tuple(out), tuple(inputs), tuple(envs), bool(unread)\n",
    ), (
        "             env: tuple = ()) -> None:\n",
        "             env: tuple = (), unread: Optional[list] = None) -> None:\n",
    ), (
        "    if cmds is not None and _nc_compound_pipe(rows, seps, read_bars):\n"
        "        raise CommandNotRead(_PIPE_NOT_READ)\n",
        "    if cmds is not None and _nc_compound_pipe(rows, seps, read_bars):\n"
        "        if unread is None:\n"
        "            raise CommandNotRead(_PIPE_NOT_READ)\n"
        "        unread.append(1)\n",
    ), (
        "        fed, runner = _nc_fed(raw, toks, piped, bodies)\n"
        "        if piped is not None and runner is piped:\n",
        "        try:\n"
        "            fed, runner = _nc_fed(raw, toks, piped, bodies)\n"
        "        except CommandNotRead as exc:\n"
        "            if unread is None or str(exc) != _PIPE_NOT_READ:\n"
        "                raise\n"
        "            unread.append(1)\n"
        "            fed, runner = [], None\n"
        "        if piped is not None and runner is piped:\n",
    ), (
        "            _nc_read(script, depth + 1, out, seen, local, inputs, bodies, envs, script_env)\n",
        "            _nc_read(script, depth + 1, out, seen, local, inputs, bodies, envs, script_env, unread)\n",
    ), (
        "def _nc_inputs(raw: list[str]) -> list[str]:\n",
        "def nested_unread(command: str, local: bool = False) -> bool:\n"
        "    got = _nc_cached(command, local)\n"
        "    if isinstance(got, CommandNotRead):\n"
        "        raise CommandNotRead(str(got))\n"
        "    return got[3]\n"
        "\n"
        "\n"
        "def _nc_inputs(raw: list[str]) -> list[str]:\n",
    ), (
        "        return combine(asks)\n"
        "    except CommandNotRead as exc:  # too deep or too many words: ask rather than pass it unread\n",
        "        if nested_unread(text, local):\n"
        "            asks.append((\"ask\", READER_MSG.format(rule=rule, what=_PIPE_NOT_READ)))\n"
        "        return combine(asks)\n"
        "    except CommandNotRead as exc:  # too deep or too many words: ask rather than pass it unread\n",
    ), (
        "    return delete_what(ev.command)  # the reader takes the here-document bodies out itself (0.8.0)\n",
        "    return delete_what(ev.command) or (_PIPE_NOT_READ if nested_unread(ev.command) else None)\n",
    ), (
        "        what = _deploy_text(text) or deploy_what(ev.command)\n",
        "        what = _deploy_text(text) or deploy_what(ev.command) or (\n"
        "            _PIPE_NOT_READ if nested_unread(ev.command) else None)\n",
    )],
    # the first form of f37, kept to show the difference
    "f37v1": [(
        "        compound = (\")\" in sep[:bar] or left[:1] in ([\"}\"], [\"fi\"], [\"done\"], [\"esac\"])\n"
        "                    or (not left and \")\" in compact[r - 1]))\n",
        "        compound = (\")\" in sep[:bar] or left[:1] in ([\"}\"], [\"fi\"], [\"done\"], [\"esac\"])\n"
        "                    or (not left and \")\" in compact[r - 1]))\n"
        "        if not compound and \"(\" not in sep and _nc_runs_stdin(rows[r][1]):\n"
        "            continue\n",
    )],
    # F38: httpie's --raw is a body, a call that shows no body sends its standard input; wget's --body-data and
    # --body-file
    "f38": [(
        "        if name in (\"-T\", \"--upload-file\", \"--post-file\"):\n",
        "        if name in (\"-T\", \"--upload-file\", \"--post-file\", \"--body-file\"):\n",
    ), (
        "        if httpie and t.lstrip(\"0123456789\").startswith(\"<\"):\n"
        "            return True, None  # F05: httpie sends its standard input as the body (`http …/graphql < q.json`)\n",
        "",
    ), (
        "        if name in _CURL_MUTATING_FLAGS or t.startswith(\"--data\"):\n",
        "        if name in _CURL_MUTATING_FLAGS or t.startswith(\"--data\") or name == \"--body-data\" or (\n"
        "                httpie and name == \"--raw\"):\n",
    ), (
        "            found, doc = _http_graphql_query(seg, head)\n"
        "            d = _graphql_verdict(doc, f\"{head} …/graphql\") if found else None\n",
        "            found, doc = _http_graphql_query(seg, head)\n"
        "            found = found or head not in (\"curl\", \"wget\")\n"
        "            d = _graphql_verdict(doc, f\"{head} …/graphql\") if found else None\n",
    )],
    # F39: the redirect targets are read on the line as the shell joins it
    "f39": [(
        "    for target in _REDIRECT_RE.findall(command):\n",
        "    for target in _REDIRECT_RE.findall(command.replace(\"\\\\\\n\", \"\")):\n",
    )],
}


def main(argv):
    src, dst = argv[1], argv[2]
    topics = argv[3:] or ["f37", "f40", "f38", "f39"]
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    for topic in topics:
        for old, new in EDITS[topic]:
            if text.count(old) != 1:
                print(f"{topic}: the text to replace stands {text.count(old)} times, wanted once:\n{old}")
                return 1
            text = text.replace(old, new)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {dst} with {', '.join(topics)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
