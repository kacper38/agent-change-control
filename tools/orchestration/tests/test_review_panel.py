"""The review panel (tracker item #69, plan step 1.4) offline: `.claude/workflows/review-panel.js` runs under Node with
a mock `agent()` (workflow_harness.mjs), so no model is called. The cases criterion 3 names: success, one lens
`null`, a verifier error, and a finding with no evidence kind rejected; and a few its code paths need (a verifier
`null`, a verdict missing, nothing to verify, arguments that are no diff path). A missing Node fails, never skips."""
import json
import pathlib
import shutil
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCRIPT = ROOT / ".claude" / "workflows" / "review-panel.js"
HARNESS = HERE / "workflow_harness.mjs"
DIFF = "/tmp/review-panel-test.diff"
LABELS = ("lens:correctness", "lens:infra", "lens:gxp")
OMIT = object()  # no `args` at all: the script sees undefined


def finding(kind, n=1, severity="MAJOR", **extra):
    evidence = {"kind": kind}
    evidence.update({"command": {"command": f"grep -n x tools/a{n}.py", "output": f"{n}: x"},
                     "quote": {"quote": f"x = {n}"}, "inference": {"reasoning": "the loop never ends"}}[kind])
    out = {"severity": severity, "file": f"tools/a{n}.py", "line": n, "title": f"t{n}", "detail": "d",
           "evidence": evidence}
    out.update(extra)
    return out


def lens(*findings):
    return {"summary": "s", "findings": list(findings)}


def run(agents, args=None):
    """The harness's output for one scenario; args None is the default {diff: DIFF}, OMIT leaves args out."""
    node = shutil.which("node")
    if node is None:
        pytest.fail("node is not on PATH: the review panel's offline test needs Node and does not skip (item #69)")
    scenario = {"agents": agents}
    if args is not OMIT:
        scenario["args"] = {"diff": DIFF} if args is None else args
    r = subprocess.run([node, str(HARNESS), str(SCRIPT), "/dev/stdin"], input=json.dumps(scenario),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def by_id(result):
    return {f["id"]: f for f in result["findings"]}


def test_success_three_lenses_and_one_batched_verifier():
    agents = {
        "lens:correctness": lens(finding("command", 1, "BLOCKER"), finding("quote", 2, "MINOR")),
        "lens:infra": lens(finding("inference", 3)),
        "lens:gxp": lens(),
        "verify": {"verdicts": [
            {"id": "correctness-1", "status": "confirmed", "how": "ran grep"},
            {"id": "correctness-2", "status": "refuted", "how": "read tools/a2.py:2", "note": "the line is y = 2"},
        ]},
    }
    out = run(agents)
    assert out["error"] is None, out
    res = out["result"]
    assert [c["label"] for c in out["calls"]] == [*LABELS, "verify"]
    assert all(c["model"] == "opus" and c["schema"] for c in out["calls"])
    assert [c["agentType"] for c in out["calls"]] == [
        "code-reviewer", "infra-reviewer", "gxp-compliance-reviewer", "code-reviewer"]
    assert out["phases"] == ["Review", "Verify"]
    f = by_id(res)
    assert f["correctness-1"]["check"] == "confirmed" and f["correctness-1"]["check_note"] == "ran grep"
    assert f["correctness-2"]["check"] == "refuted" and "y = 2" in f["correctness-2"]["check_note"]
    assert f["infra-1"]["check"] == "not re-checked"
    verify_prompt = out["calls"][3]["prompt"]
    assert "correctness-1" in verify_prompt and "correctness-2" in verify_prompt and "infra-1" not in verify_prompt
    assert res["counts"] == {"findings": 3, "confirmed": 1, "refuted": 1, "unconfirmed": 0, "not_rechecked": 1,
                             "rejected": 0, "lenses_null": 0}
    assert [x["severity"] for x in res["findings"]] == ["BLOCKER", "MAJOR", "MINOR"]
    assert res["verifier"] == {"status": "ok", "note": ""}
    assert res["cap_usd"] == 15 and res["diff"] == DIFF and res["schema"] == "review-panel/1"
    assert any("cap $15 a run" in line and "four agents" in line for line in out["logs"])
    assert DIFF in out["calls"][0]["prompt"]


def test_one_lens_null_is_reported_and_not_dropped():
    agents = {"lens:correctness": lens(finding("quote", 1)), "lens:infra": None, "lens:gxp": lens(),
              "verify": {"verdicts": [{"id": "correctness-1", "status": "confirmed", "how": "read"}]}}
    out = run(agents)
    res = out["result"]
    infra = [x for x in res["lenses"] if x["key"] == "infra"]
    assert infra == [{"key": "infra", "agent_type": "infra-reviewer", "status": "null", "findings": 0, "summary": ""}]
    assert res["counts"]["lenses_null"] == 1 and res["counts"]["confirmed"] == 1
    assert any("lens infra returned no result" in line for line in out["logs"])


def test_a_lens_that_throws_counts_as_null():
    agents = {"lens:correctness": {"$throw": "API error"}, "lens:infra": lens(), "lens:gxp": lens()}
    res = run(agents)["result"]
    assert res["counts"]["lenses_null"] == 1 and res["verifier"]["status"] == "not run"


def test_a_verifier_error_leaves_its_findings_unconfirmed():
    agents = {"lens:correctness": lens(finding("command", 1)), "lens:infra": lens(finding("inference", 2)),
              "lens:gxp": lens(finding("quote", 3)), "verify": {"$throw": "terminal API error"}}
    out = run(agents)
    res = out["result"]
    assert out["error"] is None
    assert res["verifier"] == {"status": "error", "note": "terminal API error"}
    f = by_id(res)
    assert f["correctness-1"]["check"] == f["gxp-1"]["check"] == "unconfirmed"
    assert "terminal API error" in f["gxp-1"]["check_note"]
    assert f["infra-1"]["check"] == "not re-checked"
    assert res["counts"]["unconfirmed"] == 2 and res["counts"]["findings"] == 3
    assert any("the verifier error" in line for line in out["logs"])


def test_a_verifier_null_leaves_its_findings_unconfirmed():
    agents = {"lens:correctness": lens(finding("command", 1)), "lens:infra": lens(), "lens:gxp": lens(),
              "verify": None}
    res = run(agents)["result"]
    assert res["verifier"]["status"] == "null"
    assert by_id(res)["correctness-1"]["check"] == "unconfirmed"


def test_a_finding_with_no_evidence_kind_is_rejected_listed_and_counted():
    no_kind = finding("quote", 2)
    no_kind["evidence"] = {"quote": "x = 2"}
    agents = {"lens:correctness": lens(finding("quote", 1), no_kind), "lens:infra": lens(), "lens:gxp": lens(),
              "verify": {"verdicts": [{"id": "correctness-1", "status": "confirmed", "how": "read"}]}}
    out = run(agents)
    res = out["result"]
    assert [r["id"] for r in res["rejected"]] == ["correctness-2"]
    assert res["rejected"][0]["reason"] == "no evidence kind (command, quote or inference)"
    assert res["rejected"][0]["finding"] == no_kind
    assert res["counts"]["rejected"] == 1 and res["counts"]["findings"] == 1
    assert "correctness-2" not in out["calls"][3]["prompt"]


@pytest.mark.parametrize("change, reason", [
    ({"evidence": {"kind": "proof", "quote": "x"}}, "no evidence kind (command, quote or inference)"),
    ({"evidence": {"kind": "command"}}, "evidence of kind command without its command"),
    ({"evidence": {"kind": "quote", "quote": "  "}}, "evidence of kind quote without its quote"),
    ({"evidence": {"kind": "inference"}}, "evidence of kind inference without its reasoning"),
    ({"severity": "HIGH"}, "no severity of BLOCKER, MAJOR or MINOR"),
    ({"line": "3"}, "no line number"),
    ({"file": ""}, "no file"),
])
def test_other_findings_the_panel_cannot_use_are_rejected(change, reason):
    bad = finding("quote", 1)
    bad.update(change)
    res = run({"lens:correctness": lens(bad), "lens:infra": lens(), "lens:gxp": lens()})["result"]
    assert [(r["id"], r["reason"]) for r in res["rejected"]] == [("correctness-1", reason)]
    assert res["verifier"]["status"] == "not run"


def test_a_missing_verdict_is_unconfirmed():
    agents = {"lens:correctness": lens(finding("command", 1), finding("quote", 2)), "lens:infra": lens(),
              "lens:gxp": lens(), "verify": {"verdicts": [{"id": "correctness-1", "status": "confirmed", "how": "x"},
                                                          {"id": "correctness-2", "status": "maybe", "how": "x"}]}}
    f = by_id(run(agents)["result"])
    assert f["correctness-2"]["check"] == "unconfirmed"
    assert f["correctness-2"]["check_note"] == "the verifier gave no verdict for this finding"


def test_nothing_to_verify_starts_no_verifier():
    out = run({"lens:correctness": lens(finding("inference", 1)), "lens:infra": lens(), "lens:gxp": lens()})
    assert [c["label"] for c in out["calls"]] == list(LABELS)
    assert out["result"]["verifier"]["status"] == "not run" and out["phases"] == ["Review"]


@pytest.mark.parametrize("args", [OMIT, {}, {"diff": "relative.diff"}, {"diff": 3}, "/tmp/x.diff"],
                         ids=["none", "empty", "relative", "number", "a-string"])
def test_arguments_that_are_no_diff_path_start_no_agent(args):
    out = run({}, args=args)
    assert out["calls"] == [] and out["result"] is None
    assert "args must be {diff:" in out["error"]
