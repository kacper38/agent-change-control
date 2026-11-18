"""List the calls of a transcript whose permission record has one of the given reason types.

Usage: python3 -I perm_list.py <transcript.jsonl> <reason type>[,<reason type>...]

The reason type "none" stands for a call without a record; "reject" lists refused calls whatever
the reason. Each line: when the call was issued, when its result arrived, the tool, the record,
and the head of the call's input. Three path prefixes are cut short when the environment names
them: CUT_SCRATCH, CUT_WORKTREE, CUT_CHECKOUT.
"""
import json
import os
import sys

CUTS = (
    (os.environ.get("CUT_SCRATCH", ""), "<SP>"),
    (os.environ.get("CUT_WORKTREE", ""), "<WT>"),
    (os.environ.get("CUT_CHECKOUT", ""), "<REPO>"),
)


def short(text):
    for long_form, mark in CUTS:
        if long_form:
            text = text.replace(long_form, mark)
    return text.replace("\n", " \\n ")


def main():
    path, wanted = sys.argv[1], set(sys.argv[2].split(","))
    calls = {}
    order = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    data = block.get("input") or {}
                    head = data.get("command") or data.get("file_path") or json.dumps(data)[:200]
                    calls[block.get("id")] = {"tool": block.get("name"), "asked": entry.get("timestamp"),
                                              "head": str(head), "record": None, "done": None, "error": None}
                    order.append(block.get("id"))
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                    call = calls[block.get("tool_use_id")]
                    call["done"] = entry.get("timestamp")
                    call["error"] = block.get("is_error")
                    if "permissionDecision" in entry:
                        call["record"] = entry.get("permissionDecision")
    for ident in order:
        call = calls[ident]
        record = call["record"]
        if isinstance(record, dict):
            kind = str(record.get("reasonType"))
            if record.get("decision") == "reject":
                kind = "reject"
            shown = f"{record.get('decision')}/{record.get('source')}/{record.get('reasonType')}"
        else:
            kind, shown = "none", "no record"
        if kind not in wanted:
            continue
        print(call["asked"], "->", call["done"], "|", call["tool"], "|", shown, f"| error={call['error']}")
        print("     ", short(call["head"])[:260])


if __name__ == "__main__":
    main()
