#!/usr/bin/env python3
"""fresh-review — independent, fresh-context review of the branch diff, with a receipt (plan step 3.3).

  bin/fresh-review [--base origin/main] [--model opus] [--dry-run] [--pr N [--post-only]]
`git diff <base>...HEAD` goes through the egress screen, then with the version-controlled
prompt (tools/review/prompt.md) to `claude -p` with no tools and a JSON schema. The verdict
lands in .git/fresh-review/<head-sha>.json and on stdout. Advisory, never a hook: exit 0 for
APPROVE or COMMENT, 1 for BLOCKER, 3 when the screen holds the diff, 2 on errors.
The diff is one pinned command (DIFF_FLAGS, DIFF_ENV) the receipt records as `diff_command`, so an auditor
can recompute `diff_sha256` in any clone. --pr N posts the receipt as a comment on pull request N (its lasting
copy); --post-only posts the newest receipt of HEAD without calling the model. A failed post is exit 2.
At work the same prompt is .github/instructions/review.instructions.md for Copilot code review.
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "egress"))
import egress_screen  # noqa: E402

PROMPT_PATH = os.path.join(HERE, "prompt.md")
SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVE", "COMMENT", "BLOCKER"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["BLOCKER", "MAJOR", "MINOR"]},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "summary": {"type": "string"},
                },
                "required": ["severity", "file", "line", "summary"],
            },
        },
    },
    "required": ["verdict", "summary", "findings"],
}
EXIT_BY_VERDICT = {"APPROVE": 0, "COMMENT": 0, "BLOCKER": 1}
TARGET = "claude"  # the destination is always `claude -p`; the egress label must say so, not a flag
SEVERITY_RANK = {"MINOR": 1, "MAJOR": 2, "BLOCKER": 3}
# pin, at git's defaults, what a repository's .git/config could change; the env removes the system and global
# config files, and DIFF_UNSET what the environment itself could change (GIT_DIFF_OPTS overrides --unified)
DIFF_FLAGS = ["--full-index", "--no-ext-diff", "--no-color", "--no-textconv", "--diff-algorithm=myers",
              "--src-prefix=a/", "--dst-prefix=b/", "--unified=3", "--find-renames", "--no-relative",
              "--indent-heuristic", "--inter-hunk-context=0", "--submodule=short", "--ignore-submodules=none",
              "-O/dev/null"]
DIFF_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
DIFF_UNSET = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_DIFF_OPTS")
COMMENT_LIMIT = 65000  # GitHub refuses a comment body over 65,536 characters


def effective_verdict(verdict: str, findings: list) -> str:
    """The verdict the findings justify: a BLOCKER finding makes a BLOCKER, any finding makes at least COMMENT."""
    top = max((SEVERITY_RANK.get(str(f.get("severity")), 0) for f in findings), default=0)
    if top == 3:
        return "BLOCKER"
    if top > 0 and verdict == "APPROVE":
        return "COMMENT"
    return verdict


class ReviewError(Exception):
    pass


def git(args: list, cwd: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ReviewError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def diff_text(base_sha: str, head_sha: str, cwd: str) -> tuple:
    """The diff the screen reads, the model reviews and the hash covers, and the shell command that remakes it."""
    args = ["git", "diff", *DIFF_FLAGS, f"{base_sha}...{head_sha}"]
    # config given through the environment (GIT_CONFIG_PARAMETERS, GIT_CONFIG_COUNT/KEY_n/VALUE_n) is dropped too
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG") and k not in DIFF_UNSET}
    r = subprocess.run(args, cwd=cwd, capture_output=True, env={**env, **DIFF_ENV})
    if r.returncode != 0:
        raise ReviewError(f"git diff: {r.stderr.decode('utf-8', 'replace').strip()}")
    try:
        text = r.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewError(f"the diff is not UTF-8: {exc}") from exc
    command = ["env", *(w for k in DIFF_UNSET for w in ("-u", k)), *(f"{k}={v}" for k, v in DIFF_ENV.items()), *args]
    return text, " ".join(shlex.quote(a) for a in command)


def default_base(cwd: str) -> str:
    for cand in ("origin/main", "main"):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", cand], cwd=cwd, capture_output=True).returncode == 0:
            return cand
    raise ReviewError("no origin/main or main to diff against; pass --base")


def receipt_path(rdir: str, head: str) -> str:
    """<sha>.json for the first review of a commit, <sha>.2.json, <sha>.3.json ... for re-runs."""
    n = 1
    while True:
        cand = os.path.join(rdir, f"{head}.json" if n == 1 else f"{head}.{n}.json")
        if not os.path.exists(cand):
            return cand
        n += 1


def newest_receipt(rdir: str, head: str) -> Optional[str]:
    """The receipt with the highest number for head (the last one receipt_path handed out), or None."""
    found, n = None, 1
    while True:
        cand = os.path.join(rdir, f"{head}.json" if n == 1 else f"{head}.{n}.json")
        if not os.path.exists(cand):
            return found
        found, n = cand, n + 1


def summary_line(receipt: dict, model: str, name: str) -> str:
    """One line for stdout and the comment, with the range reviewed (a delta review shows its own base); it reads
    the optional fields of a receipt file whatever their type."""
    cost = f"${receipt['cost_usd']:.2f}" if isinstance(receipt.get("cost_usd"), (int, float)) else "cost n/a"
    findings, models, base = receipt.get("findings"), receipt.get("models"), receipt.get("base_sha")
    names = ", ".join(m for m in models if isinstance(m, str)) if isinstance(models, list) else ""
    span = f"{base[:12] if isinstance(base, str) else '?'}...{receipt['sha'][:12]}"
    return (f"fresh-review: {receipt['verdict']} ({len(findings) if isinstance(findings, list) else 0} findings) "
            f"model {names or model}, {cost}; reviewed {span}; receipt {name}")


def post_receipt(rpath: str, pr: int, gh_bin: str, cwd: str) -> Optional[str]:
    """Post the receipt at rpath as a comment on pull request pr; the reason when it was not posted, else None."""
    try:
        with open(rpath, encoding="utf-8") as fh:
            raw = fh.read().rstrip("\n")
        receipt = json.loads(raw)
    except (OSError, ValueError) as exc:
        return f"cannot read the receipt: {exc}"
    if not isinstance(receipt, dict) or not all(isinstance(receipt.get(k), str) for k in ("sha", "verdict")):
        return "the receipt has no `sha` or `verdict`"
    try:  # the pull request must have the reviewed commit as its head: a wrong N or remote gets no evidence
        v = subprocess.run([gh_bin, "pr", "view", str(pr), "--json", "headRefOid"], cwd=cwd,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{gh_bin}: {exc}"
    if v.returncode != 0:
        return f"{gh_bin} pr view exited {v.returncode}: {v.stderr.strip()[:400]}"
    try:
        pr_head = json.loads(v.stdout).get("headRefOid")
    except (ValueError, AttributeError):
        pr_head = None
    if pr_head != receipt["sha"]:
        return f"pull request {pr} has head {pr_head or 'unknown'}, the receipt is for {receipt['sha']}"
    fence = "```"
    while fence in raw:
        fence += "`"
    body = (f"<!-- fresh-review-receipt: {receipt['sha']} -->\n"
            f"{summary_line(receipt, receipt.get('model_requested', ''), os.path.basename(rpath))}\n\n"
            f"{fence}json\n{raw}\n{fence}\n")
    if len(body) > COMMENT_LIMIT:
        return f"the comment would be {len(body)} characters, over {COMMENT_LIMIT}"
    try:
        fd, bpath = tempfile.mkstemp(prefix="fresh-review-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            r = subprocess.run([gh_bin, "pr", "comment", str(pr), "--body-file", bpath], cwd=cwd,
                               capture_output=True, text=True, timeout=120)
        finally:
            os.unlink(bpath)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{gh_bin}: {exc}"
    if r.returncode != 0:
        return f"{gh_bin} exited {r.returncode}: {r.stderr.strip()[:400]}"
    return None


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call_claude(prompt: str, model: str, claude_bin: str = "claude") -> dict:
    cmd = [claude_bin, "-p", "--model", model, "--output-format", "json", "--tools", "", "--no-session-persistence",
           "--json-schema", json.dumps(SCHEMA)]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReviewError(f"{claude_bin}: {exc}") from exc
    if r.returncode != 0:
        raise ReviewError(f"{claude_bin} exited {r.returncode}: {r.stderr.strip()[:400]}")
    try:
        data = json.loads(r.stdout)
    except ValueError as exc:
        raise ReviewError(f"{claude_bin} returned no JSON: {r.stdout[:200]!r}") from exc
    so = data.get("structured_output")
    if data.get("is_error") or not isinstance(so, dict) or so.get("verdict") not in EXIT_BY_VERDICT \
            or not isinstance(so.get("findings"), list):
        raise ReviewError(f"{claude_bin} gave no usable structured verdict: {str(data.get('result'))[:300]}")
    return data


def main(argv: list, cwd: Optional[str] = None, out=None) -> int:
    out = out or sys.stdout
    cwd = cwd or os.getcwd()
    ap = argparse.ArgumentParser(prog="fresh-review", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--dry-run", action="store_true", help="screen and size the prompt, do not call the model")
    ap.add_argument("--claude-bin", default="claude")
    ap.add_argument("--pr", type=int, help="post the receipt as a comment on this pull request")
    ap.add_argument("--post-only", action="store_true", help="with --pr: post the newest receipt of HEAD, no model")
    ap.add_argument("--gh-bin", default="gh")
    ns = ap.parse_args(argv)
    if ns.post_only and ns.pr is None:
        ap.error("--post-only needs --pr N")
    try:
        head = git(["rev-parse", "HEAD"], cwd).strip()
        rdir = os.path.join(git(["rev-parse", "--git-dir"], cwd).strip(), "fresh-review")
        rdir = rdir if os.path.isabs(rdir) else os.path.join(cwd, rdir)
        if ns.post_only:
            rpath = newest_receipt(rdir, head)
            if rpath is None:
                out.write(f"fresh-review: error: no receipt for {head} in {os.path.relpath(rdir, cwd)}\n")
                return 2
            with open(rpath, encoding="utf-8") as fh:
                receipt = json.load(fh)
            return finish_post(rpath, receipt, ns, cwd, out)
        base = ns.base or default_base(cwd)
        base_sha = git(["rev-parse", "--verify", f"{base}^{{commit}}"], cwd).strip()
        merge_base = git(["merge-base", base_sha, head], cwd).strip()
        diff, diff_command = diff_text(base_sha, head, cwd)
        if not diff.strip():
            out.write(f"fresh-review: nothing to review ({base}...HEAD is empty)\n")
            return 0
        held = egress_screen.screen_text(diff, TARGET, egress_screen.load_config(cwd))
        if held:
            out.write("fresh-review: diff held by the egress screen: " + ", ".join(held) + "\n")
            return 3
        with open(PROMPT_PATH, encoding="utf-8") as fh:
            prompt_text = fh.read()
        header = f"Diff ({base}...HEAD, {len(diff.splitlines())} lines):"
        prompt = prompt_text.rstrip() + f"\n\n{header}\n\n```diff\n{diff}\n```\n"
        if ns.dry_run:
            out.write(f"fresh-review: dry run, prompt {len(prompt)} chars, diff {len(diff)} chars, base {base}\n")
            return 0
        started = _dt.datetime.now(_dt.timezone.utc)
        data = call_claude(prompt, ns.model, ns.claude_bin)
        verdict = data["structured_output"]
        usage = data.get("modelUsage") or {}
        receipt = {
            "sha": head, "base": base, "base_sha": base_sha, "ts": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model_requested": ns.model, "models": sorted(usage), "cost_usd": data.get("total_cost_usd"),
            "duration_ms": data.get("duration_ms"), "prompt_sha256": sha256(prompt), "diff_sha256": sha256(diff),
            "diff_command": diff_command, "merge_base": merge_base,
            "base_tree": git(["rev-parse", f"{merge_base}^{{tree}}"], cwd).strip(),
            "head_tree": git(["rev-parse", f"{head}^{{tree}}"], cwd).strip(),
            "prompt_file": os.path.relpath(PROMPT_PATH, cwd),
            "verdict": effective_verdict(verdict["verdict"], verdict.get("findings", [])),
            "verdict_as_answered": verdict["verdict"],
            "summary": verdict.get("summary", ""), "findings": verdict.get("findings", []),
        }
        os.makedirs(rdir, exist_ok=True)
        rpath = receipt_path(rdir, head)
        with open(rpath, "x", encoding="utf-8") as fh:  # append-only evidence: never overwrite an earlier receipt
            json.dump(receipt, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except (ReviewError, OSError, ValueError) as exc:
        out.write(f"fresh-review: error: {exc}\n")
        return 2
    out.write(summary_line(receipt, ns.model, os.path.relpath(rpath, cwd)) + "\n")
    if receipt["summary"]:
        out.write(f"  {receipt['summary']}\n")
    for f in receipt["findings"]:
        out.write(f"  {f['severity']:<7} {f['file']}:{f['line']}  {f['summary']}\n")
    if ns.pr is not None:
        return finish_post(rpath, receipt, ns, cwd, out)
    return EXIT_BY_VERDICT.get(receipt["verdict"], 2)


def finish_post(rpath: str, receipt: dict, ns, cwd: str, out) -> int:
    """Post the receipt with --pr: the verdict's exit code when posted, 2 (the receipt stays) when not."""
    reason = post_receipt(rpath, ns.pr, ns.gh_bin, cwd)
    if reason:
        out.write(f"fresh-review: error: receipt not posted to pull request {ns.pr} ({reason}); the local receipt "
                  f"{os.path.relpath(rpath, cwd)} stays; retry with: bin/fresh-review --pr {ns.pr} --post-only\n")
        return 2
    out.write(f"fresh-review: receipt posted to pull request {ns.pr}\n")
    return EXIT_BY_VERDICT.get(receipt["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
