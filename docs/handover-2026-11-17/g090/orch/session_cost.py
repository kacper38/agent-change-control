"""The cost of one Claude Code session so far, counted by the repository's own ledger (tools/telemetry/ledger.py)
from the session's transcript and its agent transcripts. Read-only: the ledger's entry is built and printed,
nothing is written to the telemetry folder.

usage: python3 -I session_cost.py <ledger.py> <transcript.jsonl> [--agents]

With --agents, one line per agent transcript as well (tokens and own-count cost).
"""
import importlib.util
import os
import sys


def load(path):
    spec = importlib.util.spec_from_file_location("ledger_scratch", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    agents = "--agents" in argv
    args = [a for a in argv if a != "--agents"]
    ledger, transcript = load(args[0]), args[1]
    session = os.path.basename(transcript)[: -len(".jsonl")]
    prices = ledger.load_prices()
    entry = ledger.build_entry({"session_id": session, "transcript_path": transcript, "cwd": "(this repository)"},
                               ledger.telemetry_dir(), prices)
    print(f"session cost so far: {entry['cost_usd']} USD | basis {entry['cost_basis']} | check {entry['cost_check']} | "
          f"own count {entry['cost_usd_own']} | Claude Code's figure {entry['cost_usd_cc']} | parse errors {entry['parse_errors']}")
    for model, u in sorted(entry["models"].items()):
        tokens = ledger.total_tokens({model: {k: v for k, v in u.items() if k != "cost_usd"}})
        print(f"  {model}: tokens {tokens:,} | own-count cost {u['cost_usd']}")
    sub = entry["subagents"]
    print(f"agent transcripts {sub['transcripts']} | agent tokens {sub['tokens']:,} | share {sub['share']} | spawns logged {len(entry['spawns'])}")
    if entry.get("unpriced"):
        print(f"unpriced requests: {entry['unpriced']}")
    if agents:
        sub_dir = os.path.join(os.path.dirname(transcript), session, "subagents")
        for path, _is_workflow in ledger.agent_transcripts(sub_dir):
            usage, _errors = ledger.parse_transcript(path, prices, {})
            total = ledger.total_tokens(usage)
            cost = sum((ledger.usage_cost(u, ledger.price_for(m, prices)) or 0.0) for m, u in usage.items())
            print(f"  {os.path.basename(path)} | tokens {total:,} | own-count cost {cost:.2f} USD | models {', '.join(sorted(usage))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
