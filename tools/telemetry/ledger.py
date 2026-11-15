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
                                 transcript_path write nothing.
  ledger.py cost [--days 7]      per project and model: tokens, own-count cost, spawns, subagent share (> 70 %
                                 flagged), sessions per cost basis and marked sessions, and hook prompts per
                                 rule from <telemetry>/decisions.jsonl.
Telemetry dir: KZ_TELEMETRY_DIR or ~/.claude/telemetry.
"""
import argparse
import datetime as _dt
import glob
import json
import math
import os
import sys
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


def parse_transcript(path: str, prices: Optional[dict] = None) -> tuple:
    """({model: {input, output, cache_read, cache_write, cache_write_1h, turns[, long]}}, parse_errors); one usage
    per requestId. cache_write_1h is the 1-hour part of cache_write (0 when the usage has no breakdown). For a
    model whose price row has a long_prompt tier, `long` holds the same counters for the requests whose prompt
    is over its threshold; the model's own counters include them."""
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
            except ValueError:
                errors += 1
                continue
            if not isinstance(d, dict) or d.get("type") != "assistant":
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            key = d.get("requestId") or msg.get("id") or d.get("uuid") or ("line", n)  # no id: count the line
            seen[key] = (str(msg.get("model") or "unknown"), usage)
    for model, usage in seen.values():
        try:
            vals = [int(usage.get(k) or 0) for k in
                    ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
            split = usage.get("cache_creation")
            w1h = int(split.get("ephemeral_1h_input_tokens") or 0) if isinstance(split, dict) else 0
        except (TypeError, ValueError):  # all or nothing: a half-counted turn is worse than a parse error
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
    """Usage of the main transcript and of every agent transcript of the session, kept apart."""
    main_usage, errors = parse_transcript(transcript, prices) if transcript else ({}, 1)
    sub_usage: dict = {}
    sub_count = workflow_count = 0
    sub_dir = os.path.join(os.path.dirname(transcript), session, "subagents") if transcript else ""
    if sub_dir and os.path.isdir(sub_dir):
        for p, is_workflow in agent_transcripts(sub_dir):
            u, e = parse_transcript(p, prices)
            errors += e
            sub_count += 1
            workflow_count += is_workflow
            merge(sub_usage, u)
    return {"main": main_usage, "sub": sub_usage, "errors": errors, "transcripts": sub_count,
            "workflow_transcripts": workflow_count}


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
    return {
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
                 "reason": raw.get("reason"), "models": {}, "cost_usd": None, "subagents": {}, "spawns": [],
                 "parse_errors": 1, "error": f"{type(exc).__name__}: {exc}"[:200]}
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
    """{rule: {ask: n, deny: n}} from decisions.jsonl written by the guard."""
    out: dict = {}
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
            for rule, verdict in pairs:
                r = out.setdefault(rule, {"ask": 0, "deny": 0})
                r[verdict] = r.get(verdict, 0) + 1
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
    for row in rows:
        basis = row.get("cost_basis") or "unrecorded"  # rows written before 2026-11-15 carry no basis
        bases[basis] = bases.get(basis, 0) + 1
        check = row.get("cost_check")
        if check and check != "ok":
            marks[check] = marks.get(check, 0) + 1
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
    out.write("sessions by cost basis: " + ", ".join(f"{b} {n}" for b, n in sorted(bases.items()))
              + f"; marked {sum(marks.values())}"
              + (" (" + ", ".join(f"{c} {n}" for c, n in sorted(marks.items())) + ")" if marks else "") + "\n")
    out.write(f"spawns: {spawn_count}; sessions with subagent share > {int(SUBAGENT_SHARE_FLAG * 100)} %: "
              + (", ".join(flagged) if flagged else "none") + "\n")
    decisions = load_decisions(tdir, since)
    if decisions:
        out.write("hook prompts per rule (ask/deny): " + ", ".join(
            f"{rule} {v['ask']}/{v['deny']}" + (f" skipped {v['skipped']}" if v.get("skipped") else "")
            for rule, v in sorted(decisions.items())) + "\n")
    return 0


def main(argv: list, stdin=None, out=None, err=None) -> int:
    stdin, out, err = stdin or sys.stdin, out or sys.stdout, err or sys.stderr
    ap = argparse.ArgumentParser(prog="ledger", add_help=False)
    sub = ap.add_subparsers(dest="verb")
    sub.add_parser("hook")
    s = sub.add_parser("cost")
    s.add_argument("--days", type=int, default=7)
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
    out.write(__doc__.strip() + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
