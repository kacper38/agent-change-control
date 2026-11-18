#!/usr/bin/env python3
"""ledger — SessionEnd token ledger and cost report (plan step 3.6; Claude Code only).

  ledger.py hook                 SessionEnd: read the transcript (and its subagent and workflow-agent
                                 transcripts, any agent-*.jsonl under <session>/subagents/), join the spawn
                                 log, price with prices.json, write one line per session id to
                                 <telemetry>/sessions-YYYY-MM.jsonl (an earlier line for the same session is
                                 replaced: the project and user hooks of one SessionEnd leave one line, and a
                                 resumed session carries cumulative figures). The line holds the ledger's own
                                 count (cost_usd_own), Claude Code's own figure from the transcript's
                                 cost-state lines (cost_usd_cc), and cost_usd = the figure of cost_basis
                                 (claude-code or own; cost_check says why). Always exit 0; problems land in
                                 the line as parse_errors or cost_check. Copilot payloads and payloads without
                                 transcript_path write nothing. Requests the prices do not cover (usage speed
                                 other than standard, inference_geo other than global) are counted under
                                 "unpriced", a key the line has only when there is one.
  ledger.py cost [--days 7]      per project and model: tokens, own-count cost, spawns, subagent share (> 70 %
                                 flagged), the total of the session costs (cost_usd of the lines with a
                                 cost_basis; the rest counted as left out), sessions per cost basis and
                                 marked sessions, sessions with unpriced
                                 requests (their own count is too low), and hook prompts per rule from
                                 <telemetry>/decisions.jsonl (guard >= 0.7.0: `ran X of Y`, Y the asks
                                 that carry a call id, X those whose call went ahead).
  ledger.py recount [--write]    one-off for lines written before 2026-11-15 (no cost_basis, no recount key):
                                 rebuild each from its transcript under <CLAUDE_CONFIG_DIR or ~/.claude>/
                                 projects/*/<session>.jsonl, keeping its ts, or label it transcript: missing;
                                 the old figures go under "recount". A transcript with no model or fewer
                                 tokens than the old line is not a recount: the line stays and is labelled
                                 transcript: incomplete. Byte-identical lines of one session in a month file
                                 are one candidate and become one line (recount.lines says how many);
                                 differing lines of one session are an error. A dry run unless --write; a
                                 line that fails stays as it was and the run exits 1.
  ledger.py agents [--session ID] [--watch]
                                 one session as a tree, read from local files and written nowhere: the session on the
                                 first line, under it every agent it started (the agents of a workflow under the
                                 workflow, an agent under the agent that started it where its meta file names one).
                                 Per line: state, duration (first to last line of the transcript), cost in USD (the
                                 ledger's own count: the lines add up to cost_usd_own), tool calls, model. The state
                                 is inferred from the end of each transcript, Claude Code reports none: a session or
                                 agent that was cut off still reads as running. Without --session: the session of the
                                 current project folder whose transcript was written last; ID is a full id or a
                                 prefix that fits one session. --watch draws the tree again every 2 s until Ctrl-C
                                 (once when the output is no terminal). Prints no prompt, tool input or tool output.
                                 Claude Code only.
Telemetry dir: KZ_TELEMETRY_DIR or ~/.claude/telemetry.
"""
import argparse
import datetime as _dt
import glob
import json
import math
import os
import re
import shutil
import sys
import time
from typing import Optional

try:
    import fcntl
except ImportError:  # Windows: no lock, the reader still keeps one row per session
    fcntl = None

HERE = os.path.dirname(os.path.abspath(__file__))
PRICES_PATH = os.path.join(HERE, "prices.json")
SUBAGENT_SHARE_FLAG = 0.70
CC_LOW, CC_HIGH = 0.98, 1.5  # Claude Code's figure is the session cost within [own * low, own * high]
LOCK_FILE = ".ledger.lock"


def telemetry_dir() -> str:
    return os.path.expanduser(os.environ.get("KZ_TELEMETRY_DIR") or "~/.claude/telemetry")


def load_prices(path: str = PRICES_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("usd_per_mtok") or {}
    except (OSError, ValueError):
        return {}


def price_for(model: str, prices: dict) -> Optional[dict]:
    best = None
    for prefix, table in prices.items():
        if model.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, table)
    return best[1] if best else None


COUNTERS = ("input", "output", "cache_read", "cache_write", "cache_write_1h", "turns")


def new_counters() -> dict:
    return {k: 0 for k in COUNTERS}


def long_prompt_tier(table: Optional[dict]) -> Optional[dict]:
    """The higher rates of a model priced by prompt length (Haiku 5.5), else None."""
    tier = table.get("long_prompt") if isinstance(table, dict) else None
    return tier if isinstance(tier, dict) and isinstance(tier.get("over_tokens"), int) else None


def _rates_cost(u: dict, rates: dict) -> float:
    # cache_write counts every cache write; cache_write_1h is the 1-hour part of it. Rows written before
    # 2026-11-15 have no cache_write_1h, so all their writes are priced at the 5-minute rate, as they were then.
    w1h = u.get("cache_write_1h") or 0
    return (u["input"] * rates["input"] + u["output"] * rates["output"] + u["cache_read"] * rates["cache_read"]
            + (u["cache_write"] - w1h) * rates["cache_write"] + w1h * rates.get("cache_write_1h", rates["cache_write"]))


def usage_cost(u: dict, table: Optional[dict]) -> Optional[float]:
    if not table:
        return None
    tier, long_u = long_prompt_tier(table), u.get("long")
    if tier and isinstance(long_u, dict):  # the requests over the threshold pay the higher row, the rest the base
        base = {k: u.get(k, 0) - long_u.get(k, 0) for k in COUNTERS}
        return round((_rates_cost(base, table) + _rates_cost(long_u, tier)) / 1_000_000, 6)
    return round(_rates_cost(u, table) / 1_000_000, 6)


# Usage values the prices cover. Anything else (fast mode at 2x, US-only inference at 1.1x) is marked, not priced.
STANDARD_USAGE = {"speed": (None, "", "standard"), "inference_geo": (None, "", "global", "not_available")}


def unpriced_marks(usage: dict) -> list:
    """`<field>:<value>` for each usage value outside STANDARD_USAGE: the ledger's price is too low for that request."""
    marks = []
    for field, standard in STANDARD_USAGE.items():
        value = usage.get(field)
        if value in standard:  # absent reads as None
            continue
        name = value if isinstance(value, str) else type(value).__name__
        marks.append(f"{field}:{name[:20]}")
    return marks


def parse_transcript(path: str, prices: Optional[dict] = None, unpriced: Optional[dict] = None) -> tuple:
    """({model: {input, output, cache_read, cache_write, cache_write_1h, turns[, long]}}, parse_errors); one usage
    per requestId. cache_write_1h is the 1-hour part of cache_write (0 when the usage has no breakdown). For a
    model whose price row has a long_prompt tier, `long` holds the same counters for the requests whose prompt
    is over its threshold; the model's own counters include them. A dict passed as `unpriced` gains the request
    count per unpriced_marks() name (the return shape stays as it was)."""
    per_model: dict = {}
    seen: dict = {}
    errors = 0
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return per_model, 1
    with fh:
        for n, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except (ValueError, RecursionError):  # no JSON, or nested deeper than Python follows
                errors += 1
                continue
            if not isinstance(d, dict) or d.get("type") != "assistant":
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            key = d.get("requestId") or msg.get("id") or d.get("uuid") or ("line", n)  # no id: count the line
            if isinstance(key, (list, dict)):  # an id that cannot be a key is no id either
                key = ("line", n)
            seen[key] = (str(msg.get("model") or "unknown"), usage)
    for model, usage in seen.values():
        if unpriced is not None:
            for mark in unpriced_marks(usage):
                unpriced[mark] = unpriced.get(mark, 0) + 1
        try:
            vals = [int(usage.get(k) or 0) for k in
                    ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
            split = usage.get("cache_creation")
            w1h = int(split.get("ephemeral_1h_input_tokens") or 0) if isinstance(split, dict) else 0
            if any(abs(v) >= 2 ** 63 for v in vals + [w1h]):  # no real counter is that large, and usage_cost
                raise ValueError("count out of range")  # would overflow multiplying it by a float price
        except (TypeError, ValueError, OverflowError):  # int(Infinity) overflows; all or nothing: a half-counted
            # turn is worse than a parse error
            errors += 1
            continue
        req = dict(zip(COUNTERS, vals + [min(w1h, vals[3]), 1]))  # no split: every write at the 5-minute rate
        m = per_model.setdefault(model, new_counters())
        add(m, req)
        tier = long_prompt_tier(price_for(model, prices)) if prices else None
        if tier and vals[0] + vals[2] + vals[3] > tier["over_tokens"]:
            add(m.setdefault("long", new_counters()), req)
    return per_model, errors


def add(into: dict, u: dict) -> None:
    for k in COUNTERS:
        into[k] = into.get(k, 0) + (u.get(k) or 0)


def merge(into: dict, other: dict) -> None:
    for model, u in other.items():
        m = into.setdefault(model, new_counters())
        add(m, u)
        if isinstance(u.get("long"), dict):
            add(m.setdefault("long", new_counters()), u["long"])


def total_tokens(per_model: dict) -> int:
    return sum(u["input"] + u["output"] + u["cache_read"] + u["cache_write"] for u in per_model.values())


def spawns_for(session: str, tdir: str) -> list:
    path = os.path.join(tdir, "spawns.jsonl")
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("session") == session and row.get("event") == "PreToolUse":
                out.append({"agent": row.get("agent"), "model": row.get("model")})
    return out


def agent_transcripts(sub_dir: str) -> list:
    """[(path, is_workflow_agent)] for every agent-*.jsonl under <session>/subagents/ at any depth, sorted.
    Subagents sit directly in it; workflow agents in workflows/wf_<id>/, next to journal.jsonl (no usage) and
    *.meta.json / agent-*.json files, which are not transcripts and are skipped."""
    found = []
    for root, dirs, files in os.walk(sub_dir):
        dirs.sort()
        rel = os.path.relpath(root, sub_dir)
        is_workflow = rel.split(os.sep)[0] == "workflows"
        for name in sorted(files):
            if name.startswith("agent-") and name.endswith(".jsonl"):
                found.append((os.path.join(root, name), is_workflow))
    return found


def read_session(transcript: str, session: str, prices: Optional[dict] = None) -> dict:
    """Usage of the main transcript and of every agent transcript of the session, kept apart; the unpriced
    request counts over all of them together."""
    unpriced: dict = {}
    main_usage, errors = parse_transcript(transcript, prices, unpriced) if transcript else ({}, 1)
    sub_usage: dict = {}
    sub_count = workflow_count = 0
    sub_dir = os.path.join(os.path.dirname(transcript), session, "subagents") if transcript else ""
    if sub_dir and os.path.isdir(sub_dir):
        for p, is_workflow in agent_transcripts(sub_dir):
            u, e = parse_transcript(p, prices, unpriced)
            errors += e
            sub_count += 1
            workflow_count += is_workflow
            merge(sub_usage, u)
    return {"main": main_usage, "sub": sub_usage, "errors": errors, "transcripts": sub_count,
            "workflow_transcripts": workflow_count, "unpriced": unpriced}


def session_models(read: dict, prices: dict) -> dict:
    """{model: counters + cost_usd} over all transcripts of a session read by read_session()."""
    models: dict = {}
    combined: dict = {}
    merge(combined, read["main"])
    merge(combined, read["sub"])
    for model, u in combined.items():
        if total_tokens({model: u}) == 0:  # "<synthetic>" rows and empty turns carry no usage
            continue
        models[model] = {**u, "cost_usd": usage_cost(u, price_for(model, prices))}
    return models


def own_cost(models: dict) -> Optional[float]:
    """The ledger's own count, unrounded: the sum of the per-model costs, None if any model has no price (or none
    has usage), never a partial sum."""
    costs = [m["cost_usd"] for m in models.values()]
    return sum(costs) if costs and all(c is not None for c in costs) else None


def read_cost_state(path: str) -> tuple:
    """Claude Code's own figure from the `cost-state` lines of a main transcript: (usd or None, any counted
    snapshot has hasUnknownModelCost, lines ignored). Lines with one startTime are cumulative snapshots, so the
    last one counts; a resumed session may start a new startTime from zero, so the last of each is summed. A line
    whose totalCostUSD is missing or not a finite number >= 0 is ignored and counted."""
    last: dict = {}
    ignored = 0
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None, False, 0
    with fh:
        for line in fh:
            if '"cost-state"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue  # parse_transcript already counts an unparsable line
            if not isinstance(d, dict) or d.get("type") != "cost-state":
                continue
            usd = d.get("totalCostUSD")
            if isinstance(usd, bool) or not isinstance(usd, (int, float)) or not math.isfinite(usd) or usd < 0:
                ignored += 1
                continue
            last[json.dumps(d.get("startTime"), sort_keys=True)] = (float(usd), d.get("hasUnknownModelCost") is True)
    if not last:
        return None, False, ignored
    return sum(u for u, _ in last.values()), any(k for _, k in last.values()), ignored


def choose_cost(own: Optional[float], cc: Optional[float], cc_unknown: bool) -> tuple:
    """(session cost, basis, check). Claude Code's figure is the cost when it lies between 98 % of the own count
    and 1.5 times it: it also sees requests that never reach a transcript. Outside that range (a figure carried
    over from another session file), with no figure, or with a model Claude Code could not price, the own count
    is used and the session is marked (check != ok). With no own count to check it against, Claude Code's figure
    is used and marked `unchecked`."""
    if cc is None:
        return own, "own", "missing"
    if cc_unknown:
        return own, "own", "unknown-model-cost"
    if own is None:
        return cc, "claude-code", "unchecked"
    if own * CC_LOW <= cc <= own * CC_HIGH:
        return cc, "claude-code", "ok"
    return own, "own", "out-of-range"


def build_entry(raw: dict, tdir: str, prices: dict, now: Optional[_dt.datetime] = None) -> dict:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    session = str(raw.get("session_id") or "")
    transcript = os.path.expanduser(str(raw.get("transcript_path") or ""))
    read = read_session(transcript, session, prices)
    main_usage, sub_usage, errors = read["main"], read["sub"], read["errors"]
    models = session_models(read, prices)
    main_t, sub_t = total_tokens(main_usage), total_tokens(sub_usage)
    share = round(sub_t / (main_t + sub_t), 3) if (main_t + sub_t) else 0.0
    own = own_cost(models)
    cc, cc_unknown, cc_ignored = read_cost_state(transcript) if transcript else (None, False, 0)
    cost, basis, check = choose_cost(own, cc, cc_unknown)
    entry = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": session,
        "project": str(raw.get("cwd") or ""),
        "reason": raw.get("reason"),
        "models": models,
        "cost_usd": None if cost is None else round(cost, 4),
        "cost_usd_own": None if own is None else round(own, 4),
        "cost_usd_cc": None if cc is None else round(cc, 4),
        "cost_basis": basis,
        "cost_check": check,
        "subagents": {"transcripts": read["transcripts"], "workflow_transcripts": read["workflow_transcripts"],
                      "tokens": sub_t, "share": share, "flag": share > SUBAGENT_SHARE_FLAG},
        "spawns": spawns_for(session, tdir),
        "parse_errors": errors + cc_ignored,
    }
    if read["unpriced"]:  # only then: a session without such a request keeps the line it always had
        entry["unpriced"] = read["unpriced"]
    return entry


def append_entry(entry: dict, tdir: str) -> str:
    """One line per session id in the month file: an earlier line for the same session is dropped first.
    The check and the write happen under a lock file, so the project hook and the user hook of one
    SessionEnd serialise; a rewrite goes through a temp file and os.replace, so a crash leaves the old
    file or the new one, never a torn one."""
    os.makedirs(tdir, exist_ok=True)
    path = os.path.join(tdir, f"sessions-{entry['ts'][:7]}.jsonl")
    line = (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8")
    with open(os.path.join(tdir, LOCK_FILE), "a+b") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            existing = []
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    existing = fh.read().splitlines(keepends=True)
            kept = [ln for ln in existing if not _same_session(ln, entry["session"])]
            if len(kept) == len(existing):
                with open(path, "ab") as fh:
                    fh.write(line)
            else:
                tmp = path + ".tmp"
                with open(tmp, "wb") as fh:
                    fh.write(b"".join(ln if ln.endswith(b"\n") else ln + b"\n" for ln in kept) + line)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, path)
        finally:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_UN)
    return path


def _same_session(line: bytes, session: str) -> bool:
    if not session:
        return False
    try:
        row = json.loads(line.decode("utf-8", errors="replace"))
    except ValueError:
        return False
    return isinstance(row, dict) and row.get("session") == session


def cmd_hook(stdin, tdir: str, err) -> int:
    try:
        raw = json.loads(stdin.read() or "{}")
    except ValueError:
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    if "timestamp" in raw or "toolName" in raw or "toolArgs" in raw:  # Copilot payload: not our ledger
        return 0
    if not raw.get("transcript_path"):  # nothing to count (Claude Code always sends it)
        return 0
    try:
        entry = build_entry(raw, tdir, load_prices())
    except Exception as exc:  # noqa: BLE001 - a ledger must never hold a session end hostage; the line says why
        entry = {"ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "session": str(raw.get("session_id") or ""), "project": str(raw.get("cwd") or ""),
                 "reason": raw.get("reason"), "models": {}, "cost_usd": None, "cost_usd_own": None,
                 "cost_usd_cc": None, "cost_basis": "own", "cost_check": "error",  # marked, not a pre-2026-11-15 row
                 "subagents": {}, "spawns": [], "parse_errors": 1, "error": f"{type(exc).__name__}: {exc}"[:200]}
    try:
        append_entry(entry, tdir)
    except OSError as exc:
        err.write(f"ledger: {exc}\n")
    return 0


def load_sessions(tdir: str, since: _dt.datetime) -> list:
    """Rows since `since`; one per session id, the last written wins (a session may end in two month files)."""
    rows = []
    by_session: dict = {}
    for path in sorted(glob.glob(os.path.join(tdir, "sessions-*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                try:
                    ts = _dt.datetime.strptime(row.get("ts", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
                except ValueError:
                    continue
                if ts < since:
                    continue
                if row.get("session"):
                    by_session[row["session"]] = row
                else:
                    rows.append(row)
    return rows + list(by_session.values())


def load_decisions(tdir: str, since: _dt.datetime) -> dict:
    """{rule: {ask: n, deny: n, and any other verdict seen: skipped}} from decisions.jsonl written by the guard.

    guard >= 0.7.0 adds `markable` (Y) and `ran` (X) per rule: Y counts the asks of rows answered `ask` that carry
    a call id, the only asks its post hook can mark; X counts the `ran` rows whose session and call match such an
    ask in the window. An ask without a call id (older guard, Copilot) can never get a ran row, so it is not in Y."""
    out: dict = {}
    markable: set = set()  # (session, call, rule) of the asks a ran row can match
    ran: set = set()
    path = os.path.join(tdir, "decisions.jsonl")
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
                ts = _dt.datetime.strptime(row.get("ts", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
            except ValueError:
                continue
            if ts < since:
                continue
            rules = row.get("rules")
            if isinstance(rules, dict):  # guard >= 0.4.1: each rule's own verdict
                pairs = list(rules.items())
            else:
                pairs = [(r, row.get("verdict", "ask")) for r in rules or ["?"]]
            if row.get("verdict") == "ran":  # counted below, only against an ask of the same call
                ran.update((row.get("session"), row.get("call"), rule) for rule, _ in pairs)
                continue
            for rule, verdict in pairs:
                r = out.setdefault(rule, {"ask": 0, "deny": 0})
                r[verdict] = r.get(verdict, 0) + 1
                if verdict == "ask" and row.get("verdict") == "ask" and row.get("call"):
                    markable.add((row.get("session"), row["call"], rule))
    for key in markable:
        r = out[key[2]]
        r["markable"] = r.get("markable", 0) + 1
        r["ran"] = r.get("ran", 0) + (key in ran)
    return out


def cost_report(tdir: str, days: int, out, now: Optional[_dt.datetime] = None) -> int:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    since = now - _dt.timedelta(days=days)
    rows = load_sessions(tdir, since)
    if not rows:
        out.write(f"ledger: no sessions in the last {days} days under {tdir}\n")
        return 0
    agg: dict = {}
    flagged = []
    spawn_count = 0
    bases: dict = {}
    marks: dict = {}
    unpriced_sessions = 0
    unpriced: dict = {}
    total = {"cost": 0.0, "counted": 0, "unrecorded": 0, "no cost": 0}
    for row in rows:
        basis = row.get("cost_basis") or "unrecorded"  # rows written before 2026-11-15 carry no basis
        bases[basis] = bases.get(basis, 0) + 1
        cost_usd = row.get("cost_usd")
        if not row.get("cost_basis"):
            total["unrecorded"] += 1
        elif isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or not math.isfinite(cost_usd):
            total["no cost"] += 1
        else:
            total["cost"] += cost_usd
            total["counted"] += 1
        check = row.get("cost_check")
        if check and check != "ok":
            marks[check] = marks.get(check, 0) + 1
        row_unpriced = row.get("unpriced")
        if isinstance(row_unpriced, dict) and row_unpriced:
            unpriced_sessions += 1
            for mark, n in row_unpriced.items():
                unpriced[mark] = unpriced.get(mark, 0) + (n if isinstance(n, int) else 0)  # a hand-edited row
        project = os.path.basename(row.get("project") or "") or "?"
        for model, u in (row.get("models") or {}).items():
            a = agg.setdefault((project, model), {"sessions": 0, "tokens": 0, "output": 0, "cost": 0.0, "priced": True})
            a["sessions"] += 1
            a["tokens"] += u["input"] + u["output"] + u["cache_read"] + u["cache_write"]
            a["output"] += u["output"]
            if u.get("cost_usd") is None:
                a["priced"] = False
            else:
                a["cost"] += u["cost_usd"]
        spawn_count += len(row.get("spawns") or [])
        if (row.get("subagents") or {}).get("flag"):
            flagged.append(row.get("session", "")[:8])
    out.write(f"ledger: {len(rows)} sessions in the last {days} days\n")
    out.write(f"{'project':<32} {'model':<26} {'sess':>4} {'tokens':>12} {'output':>9} {'cost':>9}\n")
    for (project, model), a in sorted(agg.items()):
        cost = f"${a['cost']:.2f}" if a["priced"] else "n/a"
        out.write(f"{project[:32]:<32} {model[:26]:<26} {a['sessions']:>4} "
                  f"{a['tokens']:>12,} {a['output']:>9,} {cost:>9}\n")
    left_out = total["unrecorded"] + total["no cost"]
    out.write(f"total session cost: ${total['cost']:,.2f} over {total['counted']} sessions"
              + (f"; left out: {left_out} (unrecorded {total['unrecorded']}, no cost {total['no cost']})"
                 if left_out else "") + "\n")
    out.write("sessions by cost basis: " + ", ".join(f"{b} {n}" for b, n in sorted(bases.items()))
              + f"; marked {sum(marks.values())}"
              + (" (" + ", ".join(f"{c} {n}" for c, n in sorted(marks.items())) + ")" if marks else "") + "\n")
    if unpriced_sessions:  # fast mode or US-only inference: the own count of these sessions is too low
        out.write(f"sessions with requests the ledger does not price: {unpriced_sessions} ("
                  + ", ".join(f"{m} {n}" for m, n in sorted(unpriced.items())) + ")\n")
    out.write(f"spawns: {spawn_count}; sessions with subagent share > {int(SUBAGENT_SHARE_FLAG * 100)} %: "
              + (", ".join(flagged) if flagged else "none") + "\n")
    decisions = load_decisions(tdir, since)
    if decisions:
        out.write("hook prompts per rule (ask/deny): " + ", ".join(
            f"{rule} {v['ask']}/{v['deny']}"
            # guard >= 0.7.0: asked calls that went ahead, of the asks that carry a call id (see load_decisions)
            + (f" ran {v['ran']} of {v['markable']}" if v.get("markable") else "")
            + (f" skipped {v['skipped']}" if v.get("skipped") else "")
            for rule, v in sorted(decisions.items())) + "\n")
    return 0


TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def find_transcript(session) -> Optional[str]:
    """<CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<session id>.jsonl; None unless the id is plain and exactly one
    project folder holds it (the idea of probe.find_transcript: two hits are not evidence of which one counts)."""
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", session):
        return None
    root = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    hits = glob.glob(os.path.join(root, "projects", "*", session + ".jsonl"))
    return hits[0] if len(hits) == 1 else None


def _usd(value) -> str:
    finite = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return f"${value:,.2f}" if finite else "null"


RECOUNT_WAS = ("cost_usd", "models", "parse_errors", "spawns", "subagents")  # what a rebuild replaces


def old_tokens(models) -> int:
    """The token total of an old line's models, so a rebuild never shrinks it; 0 when missing or malformed."""
    try:
        return total_tokens(models) if isinstance(models, dict) else 0
    except (AttributeError, KeyError, TypeError):  # a hand-edited or cut line: there is no figure to protect
        return 0


def recount_row(row: dict, path: str, same: list, tdir: str, prices: dict, at: str) -> tuple:
    """(new line, output note, "recounted", "missing" or "incomplete") for one line without a cost_basis; `same`
    holds the raw bytes of every line with its session id in this file. Raises on anything that would make the
    replacement through append_entry unsafe, so the caller leaves the line as it is."""
    when = _dt.datetime.strptime(row.get("ts"), TS_FORMAT).replace(tzinfo=_dt.timezone.utc)
    name = os.path.basename(path)
    if name != f"sessions-{row['ts'][:7]}.jsonl":  # append_entry writes to the month file of the ts
        raise ValueError(f"the ts {row['ts']} does not belong in {name}")
    session = row.get("session")
    if not isinstance(session, str) or not session:  # append_entry finds the line to replace by its session id
        raise ValueError("no session id, so the line cannot be replaced")
    if len(set(same)) > 1:  # append_entry would drop them all and write one: only safe when they are one line
        raise ValueError(f"{len(same)} differing lines with this session id in {name}")
    stamp: dict = {"at": at}
    suffix = ""
    if len(same) > 1:  # identical copies (a hook that ran twice): append_entry replaces them all by the new line
        stamp["lines"] = len(same)
        suffix = f" ({len(same)} identical lines become one)"
    transcript = find_transcript(session)
    if transcript is None:
        return dict(row, recount=dict(stamp, transcript="missing")), "no transcript" + suffix, "missing"
    with open(transcript, "rb"):  # build_entry would count an unreadable transcript as a parse error and go on
        pass
    new = build_entry({"session_id": session, "transcript_path": transcript, "cwd": row.get("project"),
                       "reason": row.get("reason")}, tdir, prices, now=when)
    was_tokens, now_tokens = old_tokens(row.get("models")), total_tokens(new["models"])
    if not new["models"] or now_tokens < was_tokens:  # the transcript lost data: keep the old counters
        note = f"incomplete transcript (old {was_tokens} tokens, transcript {now_tokens})" + suffix
        return dict(row, recount=dict(stamp, transcript="incomplete")), note, "incomplete"
    new["recount"] = dict(stamp, was={k: row[k] for k in RECOUNT_WAS if k in row})
    note = f"{_usd(row.get('cost_usd'))} -> {_usd(new['cost_usd'])} ({new['cost_basis']}, {new['cost_check']})"
    return new, note + suffix, "recounted"


def recount(tdir: str, write: bool, out, now: Optional[_dt.datetime] = None) -> int:
    """Rebuild the lines written before 2026-11-15 (no cost_basis) from their transcripts, or label them
    `transcript: missing`; a dry run unless `write`. Exit 1 if any line failed (it stays as it was), else 0."""
    at = (now or _dt.datetime.now(_dt.timezone.utc)).strftime(TS_FORMAT)
    prices = load_prices()
    counts = {"recounted": 0, "missing": 0, "incomplete": 0, "errors": 0, "unparsable": 0}
    total = 0.0
    for path in sorted(glob.glob(os.path.join(tdir, "sessions-*.jsonl"))):
        with open(path, "rb") as fh:
            raw_lines = fh.read().splitlines()
        rows = []
        for raw in raw_lines:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                row = None
            if not isinstance(row, dict):  # kept as it is: append_entry never touches a line it cannot read
                counts["unparsable"] += 1
                continue
            rows.append((raw, row))
        lines_of_id: dict = {}  # session id -> raw bytes of each of its lines in this file
        for raw, row in rows:
            if isinstance(row.get("session"), str):  # any other id is refused by recount_row
                lines_of_id.setdefault(row["session"], []).append(raw)
        done: set = set()
        for raw, row in rows:
            if row.get("cost_basis") or "recount" in row:
                continue
            session = row.get("session")
            same = lines_of_id.get(session, [raw]) if isinstance(session, str) else [raw]
            if isinstance(session, str) and len(set(same)) == 1:  # identical copies are one candidate: skip the rest
                if session in done:
                    continue
                done.add(session)
            label = (f"{row.get('ts')} {str(session or '')[:8]} "
                     f"{os.path.basename(str(row.get('project') or '')) or '?'}")
            try:
                new, note, kind = recount_row(row, path, same, tdir, prices, at)
                if write:
                    append_entry(new, tdir)
            except Exception as exc:  # noqa: BLE001 - one bad line must not stop the others; it is named and left as is
                counts["errors"] += 1
                out.write(f"{label} error: {type(exc).__name__}: {str(exc)[:200]}\n")
                continue
            counts[kind] += 1
            if kind == "recounted" and _usd(new["cost_usd"]) != "null":
                total += new["cost_usd"]
            out.write(f"{label} {note}\n")
    if not write:
        tail = "dry run, nothing written (--write applies it)"
    else:
        tail = "written" if counts["recounted"] + counts["missing"] + counts["incomplete"] else "nothing to write"
    out.write(f"recount: {counts['recounted']} recounted ({_usd(total)}), {counts['missing']} without a transcript, "
              f"{counts['incomplete']} with an incomplete transcript, "
              f"{counts['errors']} errors, {counts['unparsable']} unparsable lines kept; {tail}\n")
    return 1 if counts["errors"] else 0


AGENT_END_TOOLS = ("StructuredOutput", "SubagentHandback")  # the tools an agent ends its run on
INTERRUPTED = "[Request interrupted"


def _when(value) -> Optional[_dt.datetime]:
    """A transcript timestamp as an aware time (no offset reads as UTC), None for anything that is no ISO text."""
    if not isinstance(value, str):
        return None
    try:
        when = _dt.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:  # other text in the key: the line has no time, the rest of it still counts
        return None
    return when if when.tzinfo else when.replace(tzinfo=_dt.timezone.utc)


def _user_ends_agent(content, end_ids: set) -> bool:
    """True when a user line closes an agent's run: an interruption, or the result of a call of AGENT_END_TOOLS."""
    if isinstance(content, str):
        return content.startswith(INTERRUPTED)
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        text, tid = block.get("text"), block.get("tool_use_id")
        if block.get("type") == "text" and isinstance(text, str) and text.startswith(INTERRUPTED):
            return True
        if block.get("type") == "tool_result" and isinstance(tid, str) and tid in end_ids:
            return True
    return False


def scan_transcript(path: str) -> Optional[dict]:
    """One pass for what parse_transcript does not give: first and last time, tool calls, the inferred end state.
    None when the file cannot be opened. Lines that are no JSON object are skipped (parse_transcript counts them)."""
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    first = last = None
    call_ids: set = set()
    loose_calls = 0
    end_ids: set = set()
    agent_state, talked, cost_state_after, cost_state_any = "running", False, False, False
    with fh:
        for line in fh:
            try:
                d = json.loads(line) if line.strip() else None
            except (ValueError, RecursionError):  # no JSON or nested too deep: parse_transcript counts it
                continue
            if not isinstance(d, dict):
                continue
            when = _when(d.get("timestamp"))
            if when is not None:
                first = when if first is None else first
                last = when
            kind = d.get("type")
            if kind == "cost-state":
                cost_state_after = cost_state_any = True
            if kind not in ("assistant", "user"):  # system, attachment, last-prompt, ...: looked through
                continue
            talked, cost_state_after = True, False
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            content = msg.get("content")
            if kind == "user":
                agent_state = "finished" if _user_ends_agent(content, end_ids) else "running"
                continue
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tid = block.get("id")
                if not isinstance(tid, str):
                    loose_calls += 1
                    continue
                call_ids.add(tid)
                if block.get("name") in AGENT_END_TOOLS:
                    end_ids.add(tid)
            agent_state = "running" if msg.get("stop_reason") in (None, "tool_use", "pause_turn") else "finished"
    seconds = None if first is None else (last - first) // _dt.timedelta(seconds=1)
    session_state = "finished" if (cost_state_after if talked else cost_state_any) else "running"
    return {"start": first, "end": last, "seconds": seconds, "tools": len(call_ids) + loose_calls,
            "agent_state": agent_state, "session_state": session_state}


def _clean(text) -> str:
    """Text from a file, safe to print: every character that is not printable becomes `?`."""
    return "".join(c if c.isprintable() else "?" for c in str(text))


def _cut(text: str, width: int) -> str:
    """The text if it fits `width`, else its first width - 3 characters and `...` (a plain cut below 3)."""
    if len(text) <= width:
        return text
    return text[:width - 3] + "..." if width >= 3 else text[:max(width, 0)]


def _priced(per_model: dict, prices: dict) -> tuple:
    """(models with tokens and their cost, cost or None) for one transcript's usage, as the ledger's own count."""
    models = session_models({"main": per_model, "sub": {}}, prices)
    return models, (own_cost(models) if models else 0.0)


def _model_label(models: dict) -> str:
    """The model with the most turns without `claude-`, ` +N` for N further models, cut to 14; `-` for none."""
    if not models:
        return "-"
    top = sorted(models, key=lambda m: (-models[m]["turns"], m))[0]
    name = top[len("claude-"):] if top.startswith("claude-") else top
    return _cut(_clean(name + (f" +{len(models) - 1}" if len(models) > 1 else "")), 14)


def _read_meta(path: str) -> tuple:
    """(meta dict, 1 if the file exists and is unreadable or no JSON object else 0)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            meta = json.load(fh)
    except FileNotFoundError:  # most agents have one, an older one may not: normal, nothing to count
        return {}, 0
    except (OSError, ValueError, RecursionError):  # there but unreadable, cut off or nested too deep: counted,
        # the row goes on without it
        return {}, 1
    return (meta, 0) if isinstance(meta, dict) else ({}, 1)


def _spawn_log(session: str, tdir: str) -> tuple:
    """({agent id: type}, {agent id: earliest start or None}, files not read, lines not read) from the
    SubagentStart rows of this session in <tdir>/spawns.jsonl."""
    types: dict = {}
    starts: dict = {}
    try:
        fh = open(os.path.join(tdir, "spawns.jsonl"), encoding="utf-8", errors="replace")
    except FileNotFoundError:  # no guard installed or no agent spawned yet: normal
        return types, starts, 0, 0
    except OSError:  # there but unreadable: the view goes on with the transcripts, counted
        return types, starts, 1, 0
    bad = 0
    with fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):  # no JSON or nested too deep: counted as a line not read
                bad += 1
                continue
            if not isinstance(row, dict) or row.get("event") != "SubagentStart" or row.get("session") != session:
                continue
            aid = row.get("agent_id")
            if not isinstance(aid, str) or not aid:
                continue
            if isinstance(row.get("agent"), str) and row["agent"]:
                types.setdefault(aid, row["agent"])
            when, was = _when(row.get("ts")), starts.get(aid)
            starts[aid] = when if was is None or (when is not None and when < was) else was
    return types, starts, 0, bad


def _workflow_name(session_dir: str, run: str) -> str:
    """The name in workflows/scripts/<name>-<run>.js, found by comparing file names; else the run id."""
    suffix = f"-{run}.js"
    try:
        names = sorted(os.listdir(os.path.join(session_dir, "workflows", "scripts")))
    except OSError:  # no scripts folder: the run id is the label
        names = []
    for name in names:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return run


def _transcript_row(path: str, prices: dict, kind: str) -> dict:
    """The figures of one transcript (4.3); `read` is False when the file could not be opened."""
    scan = scan_transcript(path)
    row = {"kind": kind, "path": path, "read": scan is not None, "state": "-", "seconds": None, "cost": None,
           "tools": None, "model": None, "mark": False, "marks": {}, "usage": {}, "models": {}, "errors": 0,
           "start": None, "end": None}
    if scan is None:
        return row
    marks: dict = {}
    usage, errors = parse_transcript(path, prices, marks)
    models, cost = _priced(usage, prices)
    row.update(state=scan["session_state" if kind == "session" else "agent_state"], seconds=scan["seconds"],
               cost=cost, tools=scan["tools"], model=_model_label(models), mark=bool(marks), marks=marks,
               usage=usage, models=models, errors=errors, start=scan["start"], end=scan["end"])
    return row


def _sum_workflow(row: dict, agents: list, prices: dict) -> None:
    """A workflow row as the subtotal of the agents shown under it at any depth."""
    read = [a for a in agents if a["read"]]
    usage: dict = {}
    for a in read:
        merge(usage, a["usage"])
    starts = [a["start"] for a in read if a["start"] is not None]
    ends = [a["end"] for a in read if a["end"] is not None]
    costs = [a["cost"] for a in read]
    row.update(cost=None if None in costs else sum(costs, 0.0), tools=sum(a["tools"] for a in read),
               model=_model_label(_priced(usage, prices)[0]), mark=any(a["mark"] for a in read),
               start=min(starts) if starts else None,
               seconds=(max(ends) - min(starts)) // _dt.timedelta(seconds=1) if starts else None)


def read_agents(transcript: str, tdir: str, prices: dict) -> dict:
    """One session as a tree of rows (section 4 of the agent-view brief), read from local files, printing nothing.
    `rows` are in print order; each has kind, depth, parent (index of its parent row), label, state, seconds,
    cost (unrounded, None without one), tools and model."""
    session = os.path.basename(transcript)[:-len(".jsonl")]
    session_dir = os.path.join(os.path.dirname(transcript), session)
    sub_dir = os.path.join(session_dir, "subagents")
    types, spawn_starts, files_bad, lines_bad = _spawn_log(session, tdir)
    top = _transcript_row(transcript, prices, "session")
    top["label"] = f"session {_clean(session)}"
    agents, workflows = [], {}
    for path, _ in agent_transcripts(sub_dir):  # os.walk of a missing folder yields nothing
        row = _transcript_row(path, prices, "agent")
        row["agent_id"] = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        meta, bad = _read_meta(path[:-len(".jsonl")] + ".meta.json")
        files_bad += bad
        atype = meta.get("agentType") if isinstance(meta.get("agentType"), str) else None
        atype = _clean(atype or types.get(row["agent_id"]) or "agent")
        desc = meta.get("description")
        row["label"] = f"{atype}  {_cut(_clean(desc), 30)}" if isinstance(desc, str) and desc else atype
        row["parent_id"] = meta.get("parentAgentId") if isinstance(meta.get("parentAgentId"), str) else None
        parts = os.path.relpath(path, sub_dir).split(os.sep)
        if parts[0] == "workflows" and len(parts) > 2:  # workflows/<run>/.../agent-*.jsonl
            run = parts[1]
            if run not in workflows:
                done = os.path.exists(os.path.join(session_dir, "workflows", run + ".json"))
                workflows[run] = {"kind": "workflow", "path": os.path.join(sub_dir, "workflows", run), "read": True,
                                  "state": "finished" if done else "running",
                                  "label": f"workflow  {_clean(_workflow_name(session_dir, run))}"}
            row["workflow"] = workflows[run]
        if not row["read"]:
            files_bad += 1
        lines_bad += row["errors"]
        agents.append(row)
    # where each row hangs: its parent agent (no loops), else its workflow, else the session
    first_of: dict = {}
    for row in agents:
        first_of.setdefault(row["agent_id"], row)
    parent_of: dict = {}
    for row in agents:
        up = first_of.get(row["parent_id"])
        walk = up
        while walk is not None and walk is not row:
            walk = parent_of.get(id(walk))
        if up is not None and walk is None:
            parent_of[id(row)] = up
    children: dict = {}
    for row in agents:
        parent = parent_of.get(id(row)) or row.get("workflow") or top
        children.setdefault(id(parent), []).append(row)
    for run_row in workflows.values():
        children.setdefault(id(top), []).append(run_row)
    seen_ids = {row["agent_id"] for row in agents}
    for aid in sorted(set(spawn_starts) - seen_ids):
        children.setdefault(id(top), []).append({
            "kind": "missing", "path": aid, "agent_id": aid, "read": False, "state": "-", "seconds": None,
            "cost": None, "tools": None, "model": None, "mark": False, "start": spawn_starts[aid],
            "label": f"{_clean(types.get(aid) or 'agent')}  (no transcript)"})

    def below(row: dict) -> list:
        """Every row under `row`, at any depth."""
        out = []
        for child in children.get(id(row), []):
            out += [child] + below(child)
        return out

    for run_row in workflows.values():
        _sum_workflow(run_row, below(run_row), prices)
    epoch = _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)
    rows: list = []

    def place(row: dict, depth: int, parent: Optional[int]) -> None:
        """Append `row` and, ordered by start time (none last, then by path), the rows under it."""
        row.update(depth=depth, parent=parent)
        rows.append(row)
        here = len(rows) - 1
        for child in sorted(children.get(id(row), []),
                            key=lambda r: (r["start"] is None, r["start"] or epoch, r["path"])):
            place(child, depth + 1, here)

    place(top, 0, None)
    counted = [r for r in rows if r["kind"] in ("session", "agent") and r["read"]]
    costs = [r["cost"] for r in counted]
    marks: dict = {}
    unpriced_models: set = set()
    for r in counted:
        for name, n in r["marks"].items():
            marks[name] = marks.get(name, 0) + n
        unpriced_models.update(m for m, v in r["models"].items() if v["cost_usd"] is None)
    agent_rows = [r for r in rows if r["kind"] in ("agent", "missing")]
    total = {"cost": None if None in costs else sum(costs, 0.0), "tools": sum(r["tools"] for r in counted),
             "mark": any(r["mark"] for r in counted), "agents": len(agent_rows),
             "running": sum(r["state"] == "running" for r in agent_rows)}
    return {"session": session, "rows": rows, "total": total, "marks": marks,
            "unpriced_models": sorted(unpriced_models), "workflows": bool(workflows),
            "files_not_read": files_bad + (not top["read"]), "lines_not_read": lines_bad + top["errors"]}


def fmt_duration(seconds: Optional[int]) -> str:
    """45s, 3m46s, 1h05m, 2d03h: two units at most, so the column stays six wide; `-` for none."""
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    if seconds < 86400:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    return f"{seconds // 86400}d{seconds % 86400 // 3600:02d}h"


def fmt_cost(cost: Optional[float], read: bool = True) -> str:
    """`$1,234.50`; `<$0.01` for a cost above zero that rounds to nothing; `n/a` without a price, `-` unread."""
    if cost is None:
        return "n/a" if read else "-"
    text = f"${cost:,.2f}"
    return "<$0.01" if cost > 0 and text == "$0.00" else text


def _row_line(state: str, time: str, cost: str, mark: bool, tools: str, model: str, label: str) -> str:
    return f"{state:<8}  {time:>6}  {cost:>9}{'*' if mark else ' '}  {tools:>5}  {model:<14}  {label}".rstrip()


AGENT_NOTES = ("columns: state, duration, cost in USD, tool calls, model",
               "duration: first to last line of the transcript; cost: the ledger's own count",
               "state: inferred from the transcript's end, so a cut-off run reads as running")


def agent_lines(data: dict) -> list:
    """The rows of read_agents() as a tree, then the notes under it; lines without line ends."""
    rows = data["rows"]
    last_child: dict = {}
    for i, row in enumerate(rows):
        if row["parent"] is not None:
            last_child[row["parent"]] = i
    lines = []
    for i, row in enumerate(rows):
        prefix = ""
        if row["parent"] is not None:
            prefix = "`- " if last_child[row["parent"]] == i else "|- "
            up = row["parent"]
            while rows[up]["parent"] is not None:  # each ancestor below the session, the outermost ends up first
                prefix = ("   " if last_child[rows[up]["parent"]] == up else "|  ") + prefix
                up = rows[up]["parent"]
        lines.append(_row_line(row["state"], fmt_duration(row["seconds"]), fmt_cost(row["cost"], row["read"]),
                               row["mark"], "-" if row["tools"] is None else str(row["tools"]), row["model"] or "-",
                               prefix + row["label"]))
    total = data["total"]
    lines.append(_row_line("total", "", fmt_cost(total["cost"]), total["mark"], str(total["tools"]), "",
                           f"agents {total['agents']}, running {total['running']}"))
    lines += [""] + list(AGENT_NOTES)
    if data["workflows"]:
        lines.append("a workflow line sums the agents under it; the total counts each agent once")
    if data["marks"]:
        marks = ", ".join(f"{_clean(name)} {n}" for name, n in sorted(data["marks"].items()))
        lines.append(f"* requests the ledger does not price ({marks}): these costs are too low")
    if data["unpriced_models"]:
        names = ", ".join(_clean(m) for m in data["unpriced_models"])
        lines.append(f"n/a: no price row for {names}, so these lines and the total have no cost")
    files, bad = data["files_not_read"], data["lines_not_read"]
    if files + bad:
        lines.append(f"not read: files {files}, lines {bad} (what they held is missing above)")
    return lines


def _encodable(text: str, stream) -> str:
    """`text` with every character the stream cannot encode replaced, so that writing it never raises."""
    encoding = getattr(stream, "encoding", None)
    if not isinstance(encoding, str):  # a StringIO and its kind take any text
        return text
    try:
        return text.encode(encoding, "replace").decode(encoding)
    except LookupError:  # an encoding Python does not know: let the stream decide
        return text


def find_session(text: Optional[str], cwd: str) -> tuple:
    """(transcript, None) or (None, error line): the session `--session TEXT` names, or without it the session
    of the project folder of `cwd` whose transcript was written last."""
    root = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
    projects = os.path.join(root, "projects")
    if text is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
            return None, "ledger agents: a session id holds only letters, digits, - and _"
        hits = sorted(glob.glob(os.path.join(glob.escape(projects), "*", text + "*.jsonl")))
        exact = [h for h in hits if os.path.basename(h) == text + ".jsonl"]
        if len(hits) == 1:
            return hits[0], None
        if len(exact) == 1:
            return exact[0], None
        if not hits:
            return None, f"ledger agents: no session fits {text} under {projects}"
        return None, f"ledger agents: {text} fits {len(hits)} sessions, give more of the id"
    folder = os.path.join(projects, re.sub(r"[^A-Za-z0-9]", "-", cwd))
    try:
        names = os.listdir(folder)
    except OSError:  # no project folder: the same answer as a folder without sessions
        names = []
    newest = None
    for name in names:
        path = os.path.join(folder, name)
        if not name.endswith(".jsonl") or not os.path.isfile(path):
            continue
        try:
            key = (os.stat(path).st_mtime_ns, name)
        except OSError:  # gone since the listing: not a candidate
            continue
        newest = key if newest is None or key > newest else newest
    if newest is None:
        return None, f"ledger agents: no session of this folder under {folder}; name one with --session"
    return os.path.join(folder, newest[1]), None


WATCH_ENTER = "\x1b[?1049h\x1b[?25l"  # the alternate screen, cursor hidden
WATCH_LEAVE = "\x1b[?25h\x1b[?1049l"  # cursor shown, the screen as it was
WATCH_LAST = "watching: redrawn every 2 s, Ctrl-C ends"


def watch_frame(lines: list, width: int, height: int) -> str:
    """One screen: the lines and WATCH_LAST, each cut to width - 1 and ended by erase-to-end-of-line; a frame
    taller than the window keeps its first lines and says how many it leaves out."""
    if len(lines) + 1 > height:
        keep = max(height - 2, 0)
        lines = lines[:keep] + [f"... {len(lines) - keep} more lines (a larger window shows them)"]
    return "\n".join(_cut(line, width - 1) + "\x1b[K" for line in lines + [WATCH_LAST])


def watch_agents(transcript: str, out, tdir: str, prices: dict, sleep, size) -> int:
    """Draw the tree on the alternate screen every 2 s, only when it changed, until Ctrl-C; the terminal is
    restored on every way out, an error included."""
    shown = None
    try:
        out.write(WATCH_ENTER)
        out.flush()
        while True:
            width, height = size()
            frame = watch_frame(agent_lines(read_agents(transcript, tdir, prices)), width, height)
            if frame != shown:
                out.write(_encodable("\x1b[H" + frame + "\x1b[J", out))
                out.flush()
                shown = frame
            sleep(2)
    except KeyboardInterrupt:  # Ctrl-C is how a watch ends
        return 0
    finally:
        out.write(WATCH_LEAVE)
        out.flush()


def cmd_agents(session: Optional[str], out, err, tdir: str, prices: dict, cwd: Optional[str] = None,
               watch: bool = False, sleep=time.sleep, size=shutil.get_terminal_size) -> int:
    """The `agents` verb: one session as a tree on `out`; an error is one line on `err` and exit 1. With `watch`
    on a terminal the tree is redrawn (sleep and size are parameters so a test runs the loop without either)."""
    transcript, problem = find_session(session, os.getcwd() if cwd is None else cwd)
    if problem:
        err.write(_encodable(_clean(problem) + "\n", err))
        return 1
    isatty = getattr(out, "isatty", None)
    if watch and callable(isatty) and isatty():
        return watch_agents(transcript, out, tdir, prices, sleep, size)
    out.write(_encodable("".join(line + "\n" for line in agent_lines(read_agents(transcript, tdir, prices))), out))
    return 0


def main(argv: list, stdin=None, out=None, err=None) -> int:
    stdin, out, err = stdin or sys.stdin, out or sys.stdout, err or sys.stderr
    ap = argparse.ArgumentParser(prog="ledger", add_help=False)
    sub = ap.add_subparsers(dest="verb")
    sub.add_parser("hook")
    s = sub.add_parser("cost")
    s.add_argument("--days", type=int, default=7)
    r = sub.add_parser("recount")
    r.add_argument("--write", action="store_true")
    g = sub.add_parser("agents")
    g.add_argument("--session")
    g.add_argument("--watch", action="store_true")
    if not argv or argv[0] in ("help", "-h", "--help"):
        out.write(__doc__.strip() + "\n")
        return 0
    try:
        ns = ap.parse_args(argv)
    except SystemExit:
        return 1
    if ns.verb == "hook":
        return cmd_hook(stdin, telemetry_dir(), err)
    if ns.verb == "cost":
        return cost_report(telemetry_dir(), ns.days, out)
    if ns.verb == "recount":
        return recount(telemetry_dir(), ns.write, out)
    if ns.verb == "agents":
        return cmd_agents(ns.session, out, err, telemetry_dir(), load_prices(), watch=ns.watch)
    out.write(__doc__.strip() + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
