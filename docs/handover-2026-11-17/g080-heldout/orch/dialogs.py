"""Print the questions, the offered labels and the answers of every AskUserQuestion call of a session transcript.

usage: python3 -I dialogs.py <transcript.jsonl>

The decision log quotes what the owner was offered and what he chose; this reads those words from the
harness's own record instead of from memory. Read-only; it prints the dialogs only, on the owner's machine.
"""
import json
import sys


def walk(node, found):
    """Collect every dict that looks like an AskUserQuestion call or its result."""
    if isinstance(node, dict):
        if node.get("type") == "tool_use" and node.get("name") == "AskUserQuestion":
            found.append(("ask", node.get("id"), node.get("input", {})))
        if node.get("type") == "tool_result":
            found.append(("result", node.get("tool_use_id"), node.get("content")))
        for value in node.values():
            walk(value, found)
    elif isinstance(node, list):
        for value in node:
            walk(value, found)


def main(argv):
    found = []
    with open(argv[0], encoding="utf-8") as handle:
        for line in handle:
            try:
                walk(json.loads(line), found)
            except ValueError:
                continue
    asked = {}
    for kind, ident, body in found:
        if kind == "ask":
            asked[ident] = body
    seen = set()
    for kind, ident, body in found:
        if kind == "ask" and ident not in seen:
            seen.add(ident)
            print(f"=== dialog {ident}")
            for question in body.get("questions", []):
                print("Q:", question.get("question"))
                for option in question.get("options", []):
                    print("   -", option.get("label"))
        if kind == "result" and ident in asked:
            text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            print("ANSWER:", text[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
