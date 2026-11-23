"""The first live run's 18 findings through the panel script of the working tree, under the mock harness: which of
them the read-only list would still send to the verifier. usage: python3 -I replay_first_run.py <worktree> <run output>.
Prints one line per finding (id, kind, check, note) and the totals; no model is called."""
import json
import pathlib
import shutil
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
run = json.loads(pathlib.Path(sys.argv[2]).read_text())
found = run["result"]["findings"]
keep = ("severity", "file", "line", "title", "detail", "evidence")
answer = {"head": "0" * 40, "summary": "replay", "findings": [{k: f[k] for k in keep} for f in found]}
scenario = {"args": {"diff": "/tmp/replay.diff", "head": "0" * 40},
            "agents": {"lens:correctness": answer, "lens:infra": {"head": "0" * 40, "summary": "", "findings": []},
                       "lens:gxp": {"head": "0" * 40, "summary": "", "findings": []},
                       "verify": {"head": "0" * 40, "verdicts": []}}}
r = subprocess.run([shutil.which("node"), str(root / "tools/orchestration/tests/workflow_harness.mjs"),
                    str(root / ".claude/workflows/review-panel.js"), "/dev/stdin"], input=json.dumps(scenario),
                   capture_output=True, text=True, timeout=60)
out = json.loads(r.stdout)
assert out["error"] is None, out["error"]
orig = {i: f["id"] for i, f in enumerate(found)}
for i, f in enumerate(sorted(out["result"]["findings"], key=lambda x: int(x["id"].split("-")[1]))):
    print(f"{orig[i]:<15} {f['evidence']['kind']:<8} {f['check']:<15} {f['check_note'][:90]}")
kinds = [f["evidence"]["kind"] for f in found]
sent = [f for f in out["result"]["findings"] if f["check"] != "not re-checked"]
print(f"kinds: {dict((k, kinds.count(k)) for k in set(kinds))}; would reach the verifier: {len(sent)} of {len(found)}")
