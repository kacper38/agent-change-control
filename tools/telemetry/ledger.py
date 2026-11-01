#!/usr/bin/env python3
"""ledger — SessionEnd token ledger and cost report (plan step 3.6; Claude Code only).

  ledger.py hook                 SessionEnd: read the transcript (and its subagent transcripts), join the spawn
                                 log, price with prices.json, write one line per session id to
                                 <telemetry>/sessions-YYYY-MM.jsonl (an earlier line for the same session is
                                 replaced: the project and user hooks of one SessionEnd leave one line, and a
                                 resumed session carries cumulative figures). Always exit 0; problems land in
                                 the line as parse_errors. Copilot payloads and payloads without
                                 transcript_path write nothing.
  ledger.py cost [--days 7]      per project and model: tokens, cost, spawns, subagent share (> 70 % flagged),
                                 and hook prompts per rule from <telemetry>/decisions.jsonl.
Telemetry dir: KZ_TELEMETRY_DIR or ~/.claude/telemetry.
"""
import argparse
import datetime as _dt
import glob
import json
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


def usage_cost(u: dict, table: Optional[dict]) -> Optional[float]:
    if not table:
        return None
    return round((u["input"] * table["input"] + u["output"] * table["output"] + u["cache_read"] * table["cache_read"]
                  + u["cache_write"] * table["cache_write"]) / 1_000_000, 6)


def parse_transcript(path: str) -> tuple:
    """({model: {input, output, cache_read, cache_write, turns}}, parse_errors); one usage per requestId."""
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
        except (TypeError, ValueError):  # all or nothing: a half-counted turn is worse than a parse error
            errors += 1
            continue
        m = per_model.setdefault(model, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "turns": 0})
        m["input"], m["output"], m["cache_read"], m["cache_write"] = (
            m["input"] + vals[0], m["output"] + vals[1], m["cache_read"] + vals[2], m["cache_write"] + vals[3])
        m["turns"] += 1
    return per_model, errors


def merge(into: dict, other: dict) -> None:
    for model, u in other.items():
        m = into.setdefault(model, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "turns": 0})
        for k in m:
            m[k] += u[k]


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


def build_entry(raw: dict, tdir: str, prices: dict, now: Optional[_dt.datetime] = None) -> dict:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    session = str(raw.get("session_id") or "")
    transcript = os.path.expanduser(str(raw.get("transcript_path") or ""))
    main_usage, errors = parse_transcript(transcript) if transcript else ({}, 1)
    sub_usage: dict = {}
    sub_count = 0
    sub_dir = os.path.join(os.path.dirname(transcript), session, "subagents") if transcript else ""
    if sub_dir and os.path.isdir(sub_dir):
        for p in sorted(glob.glob(os.path.join(sub_dir, "*.jsonl"))):
            u, e = parse_transcript(p)
            errors += e
            sub_count += 1
            merge(sub_usage, u)
    models: dict = {}
    combined: dict = {}
    merge(combined, main_usage)
    merge(combined, sub_usage)
    for model, u in combined.items():
        if total_tokens({model: u}) == 0:  # "<synthetic>" rows and empty turns carry no usage
            continue
        models[model] = {**u, "cost_usd": usage_cost(u, price_for(model, prices))}
    main_t, sub_t = total_tokens(main_usage), total_tokens(sub_usage)
    share = round(sub_t / (main_t + sub_t), 3) if (main_t + sub_t) else 0.0
    costs = [m["cost_usd"] for m in models.values()]
    priced = bool(costs) and all(c is not None for c in costs)
    return {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": session,
        "project": str(raw.get("cwd") or ""),
        "reason": raw.get("reason"),
        "models": models,
        "cost_usd": round(sum(costs), 4) if priced else None,
        "subagents": {"transcripts": sub_count, "tokens": sub_t, "share": share, "flag": share > SUBAGENT_SHARE_FLAG},
        "spawns": spawns_for(session, tdir),
        "parse_errors": errors,
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
    for row in rows:
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
