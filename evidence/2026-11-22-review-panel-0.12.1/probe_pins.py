"""Probe the pin checker at the working tree: scripts that call agent() with no model, hidden in ways the review
round named or I suspect; usage: python3 -I probe_pins.py <worktree>. Prints each case and the checker's answer."""
import importlib.util
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("pins", root / "tools/orchestration/tests/test_workflow_pins.py")
pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pins)
META = "export const meta = {name: 'x', description: 'y'}\n"
CASES = {
    "template-expr": "const s = `${await agent('go')}`\n",
    "regex-backtick": "const r = /`/\nawait agent('go')\nconst q = /`/\n",
    "regex-quote": "const r = /'/; await agent('go'); const q = /'/\n",
    "regex-after-if": "if (c) /'/.test(s); await agent('go'); const q = /'/\n",
    "eval": "await eval('agent')('go')\n",
    "arguments": "await arguments[0]('go')\n",
    "ctor": "await (async () => 1).constructor('return agent')()('go')\n",
    "ternary": "const a = c ? agent : null\nawait a('go', {})\n",
    "computed-key": "await agent('go', {model: 'opus', ['model']: m})\n",
    "template-comma": "await agent(`${0, {model: 'opus'}}`)\n",
}
for name, body in CASES.items():
    print(f"{name}: {pins.problems(META + body)}")
