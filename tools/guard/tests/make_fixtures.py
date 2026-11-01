#!/usr/bin/env python3
"""Generate the per-rule fixture corpus from CASES, using the recorded harness shapes as envelopes.

Run from anywhere: `python3 tools/guard/tests/make_fixtures.py`. test_fixtures.py checks that the
files on disk equal this generator's output, so the case tables and the corpus cannot drift.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "fixtures"

CLIENT = {"boundary": "client"}


def shell(decision, *commands):
    return [(decision, "shell", {"command": c}) for c in commands]


# rule -> list of (decision, kind, payload[, config]); payload keys: command | path (+ content)
CASES: dict = {
    "delete-guard": [
        *shell(
            "ask",
            "rm -rf build", "sudo rm -r /tmp/x", "git branch -D feature/x", "git push origin --force",
            "git push origin :old-branch", "find . -name '*.pyc' -delete", "kubectl delete pod web-0",
            "docker system prune -af", "rclone sync remote:a remote:b", "psql -c \"DELETE FROM users WHERE id = 1\"",
            "python3 -c \"import shutil; shutil.rmtree('x')\"", "npm uninstall lodash", "cd dist && rm bundle.js",
            "git -C ../repo clean -fd", "truncate -s 0 app.log", "git restore --staged main.py", "git stash drop",
        ),
        *shell(
            "allow",
            "ls -la", "git status", "grep -rn \"rmdir\" src/", "echo \"please do not rm this\"", "npm run build",
            "git push origin feature/x", "git branch -a", "cat README.md", "python3 -m pytest -q", "terraform plan",
            "git branch --show-current", "docker ps", "rsync -av src/ dst/", "git checkout feature/x",
            "git commit -m 'remove dead code'", "make test", "git diff --stat",
        ),
    ],
    "secret-write": [
        ("deny", "write", {"path": ".env", "content": "TOKEN=abc"}),
        ("deny", "write", {"path": "config/.env.production", "content": "DB=x"}),
        ("deny", "edit", {"path": "certs/server.key"}),
        ("deny", "write", {"path": "certs/server.pem", "content": "-----BEGIN"}),
        ("deny", "edit", {"path": "infra/terraform.tfstate"}),
        ("deny", "write", {"path": "~/.aws/credentials", "content": "[default]"}),
        ("deny", "write", {"path": "~/.ssh/id_ed25519", "content": "x"}),
        ("ask", "write", {"path": "infra/prod.tfvars", "content": "region = \"eu-central-1\""}),
        ("ask", "edit", {"path": "terraform.tfvars"}),
        ("allow", "write", {"path": ".env.example", "content": "TOKEN="}),
        ("allow", "write", {"path": "prod.tfvars.example", "content": "region = \"\""}),
        ("allow", "write", {"path": "README.md", "content": "# x"}),
        ("allow", "edit", {"path": "main.tf"}),
        ("allow", "edit", {"path": "src/keys.py"}),
        ("allow", "write", {"path": "~/.ssh/id_ed25519.pub", "content": "ssh-ed25519 AAAA"}),
    ],
    "secret-read": [
        ("ask", "read", {"path": ".env"}),
        ("ask", "read", {"path": "~/.aws/credentials"}),
        ("ask", "read", {"path": "~/.ssh/id_ed25519"}),
        ("ask", "read", {"path": "~/.kube/config"}),
        ("ask", "read", {"path": "infra/terraform.tfstate"}),
        ("ask", "read", {"path": "~/.config/gh/hosts.yml"}),
        ("allow", "read", {"path": ".env.example"}),
        ("allow", "read", {"path": "~/.ssh/id_ed25519.pub"}),
        ("allow", "read", {"path": "README.md"}),
        ("allow", "read", {"path": "src/config.py"}),
        ("allow", "read", {"path": "infra/prod.tfvars"}),
    ],
    "secret-shell": [
        *shell(
            "deny",
            "echo TOKEN=x > .env", "echo X=1 >> config/.env.local", "cp ~/Downloads/key.pem certs/server.pem",
            "git add .env", "sed -i 's/a/b/' terraform.tfstate", "tee -a .env.local <<< 'X=1'",
            "cat secret.txt > ~/.aws/credentials",
        ),
        *shell(
            "ask",
            "cat .env", "jq . ~/.aws/credentials", "grep KEY config/.env.production", "base64 ~/.ssh/id_rsa",
            "source .env && npm start", "kubectl --kubeconfig ~/.kube/config get pods", "less infra/terraform.tfstate",
        ),
        *shell(
            "allow",
            "cat .env.example", "ls -la", "grep -rn API_KEY src/", "cat ~/.ssh/id_ed25519.pub",
            "terraform plan -var-file=prod.tfvars", "echo 'TOKEN=' > .env.example", "git add README.md",
            "cat docs/keys-and-locks.md",
            "cat > notes.md <<'EOF'\nTo rotate: echo NEW=1 > .env and restart\nEOF",
            "python3 - <<'PY'\nopen('.env.example').read()\nPY\necho done",
        ),
    ],
    "git-guard": [
        *shell(
            "deny",
            "git push --force origin feature/x", "git push -f", "git push origin main", "git push origin HEAD:main",
            "git push -u origin main", "git push origin +feature:feature", "git push --all origin",
            "git commit --no-verify -m x", "git commit -n -m x", "git push --no-verify origin feature/x",
            "git -C ../repo push origin main", "git push --force-with-lease=main origin feature",
            "git push origin feature:refs/heads/main", "cd repo && git push origin main",
        ),
        *shell(
            "allow",
            "git push origin feature/x", "git push -u origin step-1.4-boundary", "git status",
            "git commit -m 'feat: x'", "git push origin feature/x:feature/x", "git fetch --force",
            "git log --oneline -n 5", "git push origin HEAD:feature/x", "git push -o ci.skip origin feature/x",
            "gh pr merge 12 --squash",
            "git commit -q -F - <<'EOF'\nfeat: x\n\nnever run git push --force\nEOF",
        ),
    ],
    "deploy-ask": [
        *shell(
            "ask",
            "terraform apply -auto-approve", "terraform destroy", "tofu apply", "kubectl apply -f deploy.yaml",
            "kubectl rollout restart deploy/web", "helm upgrade --install web ./chart",
            "docker push ghcr.io/x/y:abc123",
            "gh workflow run deploy.yml", "gh release create v1.0.0", "az deployment group create -g rg -f main.bicep",
            "aws cloudformation deploy --stack-name x", "hcloud server create --name x", "pulumi up", "cdk deploy",
            "ansible-playbook site.yml", "sudo terraform apply", "make build && terraform apply",
        ),
        *shell(
            "allow",
            "terraform plan", "terraform validate", "kubectl get pods", "kubectl apply -f x.yaml --dry-run=server",
            "helm template web ./chart", "docker build -t x .", "gh pr create --fill", "gh run list",
            "ansible-playbook site.yml --check", "aws s3 ls", "terraform fmt -check", "kubectl diff -f x.yaml",
            "cat > runbook.md <<'EOF'\nthen run terraform apply\nEOF",
        ),
    ],
    "egress-guard": [
        ("ask", "shell", {"command": "agy review plan.md"}, CLIENT),
        ("ask", "shell", {"command": "gemini -p 'summarize this'"}, CLIENT),
        ("ask", "shell", {"command": "curl https://api.openai.com/v1/chat/completions -d @req.json"}, CLIENT),
        ("ask", "shell", {"command": "ollama run llama3 < notes.txt"}, CLIENT),
        ("allow", "shell", {"command": "agy review plan.md"}),
        ("allow", "shell", {"command": "curl https://api.github.com/repos/x/y"}, CLIENT),
        ("allow", "shell", {"command": "git status"}, CLIENT),
    ],
    # blocking cases need a real git tree and live in test_scratch_md.py
    "scratch-md": [
        ("allow", "write", {"path": "docs/notes.md", "content": "# notes"}),
        ("allow", "write", {"path": "README.md", "content": "# x"}),
        ("allow", "write", {"path": "src/README.md", "content": "# x"}),
        ("allow", "write", {"path": "notes.txt", "content": "x"}),
    ],
    # the envelope cwd /work/repo is not a repository on disk: blocking cases live in test_protected_branch.py
    "protected-branch": [
        ("allow", "write", {"path": "x.md", "content": "x"}),
        ("allow", "edit", {"path": "src/a.py"}),
        ("allow", "read", {"path": "README.md"}),
        *shell("allow", "git status", "git log --oneline -3", "git switch -c step-2"),
    ],
    # the first spawns of a session pass; the 6th/16th/… need the spawn log and live in test_fan_out.py
    "fan-out": [
        ("allow", "spawn", {"agent": "python-engineer", "model": "opus"}),
        ("allow", "spawn", {"agent": "Explore"}),
        *shell("allow", "ls -la"),
    ],
    "guard-config": [
        ("ask", "edit", {"path": ".claude/settings.json"}),
        ("ask", "write", {"path": ".claude/settings.local.json", "content": "{}"}),
        ("ask", "edit", {"path": ".claude/guard.json"}),
        ("ask", "edit", {"path": ".github/hooks/guard.json"}),
        ("ask", "write", {"path": ".github/hooks/lint.json", "content": "{}"}),
        ("ask", "edit", {"path": "tools/guard/guard.py"}),
        ("ask", "write", {"path": "tools/guard/tests/make_fixtures.py", "content": "x"}),
        ("ask", "edit", {"path": "~/.claude/settings.json"}),
        ("ask", "edit", {"path": "~/.claude/settings.local.json"}),
        ("ask", "edit", {"path": "~/.claude/hooks/ask-on-delete.sh"}),
        ("ask", "edit", {"path": "sub/project/.claude/guard.json"}),
        ("allow", "edit", {"path": "README.md"}),
        ("allow", "write", {"path": ".claude/agents/x.md", "content": "x"}),
        ("allow", "write", {"path": ".claude/skills/x/SKILL.md", "content": "x"}),
        ("allow", "edit", {"path": ".github/workflows/ci.yml"}),
        ("allow", "edit", {"path": "tools/tracker/cli.py"}),
        ("allow", "edit", {"path": "~/.claude/agents/x.md"}),
        ("allow", "edit", {"path": "~/.claude/CLAUDE.md"}),
        ("allow", "edit", {"path": "docs/settings.json"}),
        ("allow", "read", {"path": ".claude/settings.json"}),
    ],
    "tracker-guard": [
        *shell(
            "deny",
            "gh issue close 1", "gh issue create --title x --body y", "gh issue edit 3 --add-label status/done",
            "gh issue comment 2 --body done", "gh issue reopen 4", "gh issue delete 5", "gh label create foo",
            "gh label delete bar", "gh api -X PATCH repos/o/r/issues/1 -f state=closed",
            "gh api repos/o/r/issues/1/labels -f labels[]=x", "gh api --method DELETE repos/o/r/labels/foo",
            "curl -X PATCH https://api.github.com/repos/o/r/issues/1 -d '{}'",
            "curl -H 'Authorization: x' https://api.github.com/repos/o/r/issues -d @body.json",
            "http PATCH https://api.github.com/repos/o/r/issues/1 state=closed",
            "tracker owner ready 1", "python3 tools/tracker/tracker.py owner done 2", "cd repo && gh issue close 7",
        ),
        *shell(
            "allow",
            "gh issue view 1", "gh issue list --state open", "gh issue status", "gh api repos/o/r/issues/1",
            "gh api repos/o/r/issues --jq '.[].number'", "curl https://api.github.com/repos/o/r/issues/1",
            "gh pr create --fill", "gh pr merge 3 --rebase", "gh label list",
            "tracker claim 4 --branch step-5", "python3 tools/tracker/tracker.py new --title x",
            "tracker list --status ready", "gh issue create --label handoff --title 'handoff: x' --body y",
            "gh issue create --title x --label agent-loop", "gh api -X POST repos/o/r/pulls -f title=x",
            "echo 'gh issue close 1'",
        ),
        # Azure DevOps (ADO port step A3): work items are issues, tags are labels
        *shell(
            "deny",
            "az boards work-item create --type Task --title x", "az boards work-item update --id 12 --state Closed",
            "az boards work-item update --id 12 --fields System.Tags=status/done",
            "az boards work-item delete --id 12 --yes",
            "az boards work-item relation add --id 12 --relation-type parent --target-id 3",
            "az devops invoke --area wit --resource workitems --route-parameters id=12 --http-method PATCH",
            "az devops invoke --area wit --resource workitems --route-parameters id=12",
            "az rest --method patch --uri https://dev.azure.com/o/p/_apis/wit/workitems/12 --body @p.json",
            "az rest -u https://o.visualstudio.com/p/_apis/wit/workItems/12/comments?api-version=7.1-preview.4 -b '{}'",
            "curl -X PATCH https://dev.azure.com/o/p/_apis/wit/workitems/12?api-version=7.1 -d @p.json",
            "curl -XDELETE https://dev.azure.com/o/p/_apis/wit/workitems/12?api-version=7.1",
            "curl -H 'Content-Type: application/json' -d@c.json https://o.visualstudio.com/p/_apis/wit/workItems/1",
            "wget --method=PATCH https://dev.azure.com/o/p/_apis/wit/workitems/12",
            "http PATCH https://dev.azure.com/o/p/_apis/wit/workitems/12 op=add",
            "xh https://dev.azure.com/o/p/_apis/wit/workitems/12 System.Title=x",
            "curl 'https://dev.azure.com/o/p/_apis/wit/workitems/12?bypassRules=true&api-version=7.1'",
            "python3 sync.py --bypass-rules",
            "az repos pr create --title x --bypass-policy true --bypass-policy-reason y",
            "az repos pr create --title x --auto-complete true --transition-work-items true",
            "az repos pr update --id 7 --status completed", "az repos pr update --id 7 --transition-work-items",
            "cd repo && az boards work-item update --id 1 --state Done",
        ),
        *shell(
            "allow",
            "az boards work-item show --id 12", "az boards query --wiql 'SELECT [System.Id] FROM workitems'",
            "az boards work-item relation show --id 12",
            "az rest --uri https://dev.azure.com/o/p/_apis/wit/workitems/12?api-version=7.1",
            "az rest --method post --uri https://dev.azure.com/o/p/_apis/git/repositories/r/pullrequests -b @pr.json",
            "curl https://dev.azure.com/o/p/_apis/wit/workitems/12?api-version=7.1",
            "http https://dev.azure.com/o/p/_apis/wit/workitems/12 api-version==7.1 'Authorization:Bearer abc='",
            "az repos pr create --title x --source-branch step-1 --transition-work-items false",
            "az repos pr update --id 7 --title y", "az repos pr list --status completed",
            "git commit -q -F - <<'EOF'\ndocs: x\n\nnever send bypassRules=true\nEOF",
        ),
    ],
}

ENVELOPES = {
    "claude": {
        "shell": "PreToolUse-Bash", "read": "PreToolUse-Read", "write": "PreToolUse-Write", "edit": "PreToolUse-Edit",
        "spawn": "PreToolUse-Agent",
    },
    "copilot": {
        "shell": "PreToolUse-bash", "read": "PreToolUse-view", "write": "PreToolUse-create", "edit": "PreToolUse-edit",
        "spawn": "PreToolUse-task",
    },
}


def tool_input(harness: str, kind: str, payload: dict) -> dict:
    if kind == "shell":
        return {"command": payload["command"]}
    if kind == "spawn":
        ti = {"description": "d", "prompt": "p"}
        if harness == "claude":
            ti["subagent_type"] = payload["agent"]
            if payload.get("model"):
                ti["model"] = payload["model"]
        return ti  # the Copilot `task` shape is synthesized; replace via a capture at work (step 1.3)
    path = payload["path"]
    if harness == "claude":
        ti = {"file_path": path}
        if kind == "write":
            ti["content"] = payload.get("content", "")
        if kind == "edit":
            ti.update({"old_string": "a", "new_string": "b", "replace_all": False})
        return ti
    ti = {"path": path}
    if kind == "write":
        ti["file_text"] = payload.get("content", "")
    if kind == "edit":
        ti.update({"old_str": "a", "new_str": "b"})
    return ti


def slug(payload: dict) -> str:
    text = payload.get("command") or payload.get("path") or payload.get("agent") or ""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def generate(out: pathlib.Path) -> dict:
    files = {}
    envelopes = {
        h: {k: json.loads((FIX / "_shapes" / h / f"{n}.json").read_text()) for k, n in m.items()}
        for h, m in ENVELOPES.items()
    }
    for rule, cases in CASES.items():
        for harness in ("claude", "copilot"):
            counters: dict = {}
            for case in cases:
                decision, kind, payload = case[0], case[1], case[2]
                config = case[3] if len(case) > 3 else None
                env = json.loads(json.dumps(envelopes[harness][kind]))
                env["tool_input"] = tool_input(harness, kind, payload)
                env["_fixture"] = {**env.get("_fixture", {}), "rule": rule, "case": payload}
                if config:
                    env["_fixture"]["config"] = config
                counters[decision] = counters.get(decision, 0) + 1
                rel = pathlib.Path(rule) / harness / decision / f"{counters[decision]:02d}-{slug(payload)}.json"
                files[rel] = json.dumps(env, indent=2, sort_keys=True) + "\n"
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text)
    return files


if __name__ == "__main__":
    written = generate(FIX)
    print(f"wrote {len(written)} fixtures under {FIX}")
    sys.exit(0)
