"""guard 0.10.0 (tracker item #65, plan step 1.7): the boundary only tightens, cloud launches are denied, a cloud
session turns every ask into a deny, guard-config sees shell writes and wider paths, the owner's stored GitHub
credentials are read by no session, the refs the guard reads are not rewritten, and the harness's own GitHub tools
get the verdict of their twin. These rows were written before the code (D1 to D9 of the host's design); the
commands are data, nothing runs.

Row ids: C cloud-launch, W guard-config shell writes, K stored credentials, G refs, P an approval, T a tool call
of cloud-launch, H a GitHub tool, M a tool the host classed after the first run (Monitor, ExitWorktree,
DesignSync). A trailing `s` marks a silent neighbour, `l` a named limit (silent on purpose), `c` broken input
(ask or deny, never silent, never a traceback).
"""
import io
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD_PY = os.path.join(os.path.dirname(HERE), "guard.py")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OLD_SHELL_RULES = ("delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
                   "tracker-guard", "host-install")
# rule `shell` in a row: every shell rule silent, the two that judge shell commands since 0.10.0 included
SHELL_RULES = OLD_SHELL_RULES + ("cloud-launch", "guard-config")
CLOUD_PREFIX = ("cloud session (CLAUDE_CODE_REMOTE): this would ask on the owner's machine, and nobody can answer "
                "here, so it is denied.")

# id | branch[@boundary] | rule | expected | command, as in test_table_forms.py
SHELL_ROWS = r"""
# --- D3: cloud-launch, the shell forms
C1 | feat/x | cloud-launch | deny | claude --cloud "fix the flaky test"
C1 | feat/x | cloud-launch | deny | claude --remote "fix it"
C1 | feat/x | cloud-launch | deny | claude --cloud=env-1 "fix it"
C1 | feat/x | cloud-launch | deny | claude --remote=env-1 "fix it"
C1 | feat/x | cloud-launch | deny | claude -p "fix it" --cloud
C1 | feat/x | cloud-launch | deny | claude "/autofix-pr"
C1 | feat/x | cloud-launch | deny | claude -p "/autofix-pr 12"
C1 | feat/x | cloud-launch | deny | claude -p ' /autofix-pr 12'
C1 | feat/x | cloud-launch | deny | claude -p "'/autofix-pr'"
C1 | feat/x | cloud-launch | deny | timeout 600 claude --cloud "x"
C1 | feat/x | cloud-launch | deny | env FOO=1 claude --cloud "x"
C1 | feat/x | cloud-launch | deny | sudo -u dev claude --remote "x"
C1 | feat/x | cloud-launch | deny | bash -c 'claude --cloud "x"'
C1 | feat/x | cloud-launch | deny | echo task | claude --cloud "x"
C1 | feat/x | cloud-launch | deny | git push origin feat/x && claude --cloud "x"
C1 | feat/x | cloud-launch | deny | /usr/local/bin/claude --cloud "x"
C1 | feat/x | cloud-launch | deny | CLAUDE --cloud "x"
C1 | feat/x | cloud-launch | deny | x=$(claude --cloud "x")
C1c | feat/x | cloud-launch | deny | claude --cloud 'x
Cs | feat/x | shell | silent | claude -p "explain the remote setup"
Cs | feat/x | shell | silent | claude -p "run /autofix-pr later"
Cs | feat/x | shell | silent | claude --version
Cs | feat/x | shell | silent | claude remote-control
Cs | feat/x | shell | silent | claude --teleport
Cs | feat/x | shell | silent | claude mcp list
Cs | feat/x | shell | silent | echo claude --cloud
Cs | feat/x | shell | silent | grep -- --cloud f
Cs | feat/x | shell | silent | git remote -v
# --- D7: guard-config, shell writes to its paths ask
W1 | feat/x | guard-config | ask | echo x > tools/guard/guard.py
W1 | feat/x | guard-config | ask | echo x >> .claude/settings.json
W1 | feat/x | guard-config | ask | echo x >| .github/hooks/guard.json
W1 | feat/x | guard-config | ask | echo x &> .github/workflows/ci.yml
W1 | feat/x | guard-config | ask | "echo x \\\n> tools/scan/latest_tag.py"
W1 | feat/x | guard-config | ask | tee tools/testguard/testguard.py < x
W1 | feat/x | guard-config | ask | cat x | tee -a .claude/guard.json
W1 | feat/x | guard-config | ask | cp /tmp/x tools/commit_msg.py
W1 | feat/x | guard-config | ask | mv /tmp/x tools/tracker/tracker.py
W1 | feat/x | guard-config | ask | install -m 644 x .github/workflows/release.yml
W1 | feat/x | guard-config | ask | ln -sf /tmp/x tools/guard/guard.py
W1 | feat/x | guard-config | ask | rsync -a /tmp/x/ tools/guard/
W1 | feat/x | guard-config | ask | cp -t tools/scan /tmp/x.py
W1 | feat/x | guard-config | ask | cp --target-directory=.github/workflows /tmp/ci.yml
W1 | feat/x | guard-config | ask | dd if=/tmp/x of=tools/guard/guard.py
W1 | feat/x | guard-config | ask | sed -i s/a/b/ tools/guard/guard.py
W1 | feat/x | guard-config | ask | sed -i.bak 's/ask/x/' .claude/settings.json
W1 | feat/x | guard-config | ask | sed -i s/a/b/ ~/.claude/settings.json
W1 | feat/x | guard-config | ask | perl -pi -e 's/a/b/' tools/tracker/tracker.py
W1 | feat/x | guard-config | ask | truncate -s 0 tools/guard/guard.py
W1 | feat/x | guard-config | ask | touch .github/workflows/new.yml
W1 | feat/x | guard-config | ask | chmod +x tools/scan/latest_tag.py
W1 | feat/x | guard-config | ask | curl -o tools/guard/guard.py https://example.org/g.py
W1 | feat/x | guard-config | ask | curl --output .claude/settings.json https://example.org/s
W1 | feat/x | guard-config | ask | wget -O tools/commit_msg.py https://example.org/c.py
W1 | feat/x | guard-config | ask | patch tools/guard/guard.py fix.diff
W1 | feat/x | guard-config | ask | "git apply <<'EOF'\n--- a/tools/guard/guard.py\n+++ b/tools/guard/guard.py\n@@ -1 +1 @@\n-x\n+y\nEOF"
W1 | feat/x | guard-config | ask | git checkout main -- tools/guard/guard.py
W1 | feat/x | guard-config | ask | git restore tools/tracker/tracker.py
W1 | feat/x | guard-config | ask | git restore --source=HEAD~3 .github/workflows/ci.yml
W1 | feat/x | guard-config | ask | python3 -c "open('tools/guard/guard.py', 'w').write('')"
W1 | feat/x | guard-config | ask | python -c "import os; os.remove('.claude/settings.json')"
W1 | feat/x | guard-config | ask | node -e "require('fs').writeFileSync('tools/scan/latest_tag.py', '')"
W1 | feat/x | guard-config | ask | perl -e 'unlink "tools/commit_msg.py"'
W1 | feat/x | guard-config | ask | ruby -e 'File.write(".github/workflows/ci.yml", "")'
W1 | feat/x | guard-config | ask | bash -c 'echo x > tools/guard/guard.py'
W1 | feat/x | guard-config | ask | sudo tee .github/hooks/guard.json < x
W1 | feat/x | guard-config | ask | SED -i s/a/b/ tools/guard/guard.py
W1 | feat/x | guard-config | ask | echo x > Tools/Guard/guard.py
W1 | feat/x | guard-config | ask | echo x > .GITHUB/WORKFLOWS/ci.yml
Ws | feat/x | guard-config | silent | cat tools/guard/guard.py
Ws | feat/x | guard-config | silent | grep -n ask .claude/settings.json
Ws | feat/x | guard-config | silent | sed -n 1,20p tools/guard/guard.py
Ws | feat/x | guard-config | silent | head -50 .github/workflows/ci.yml
Ws | feat/x | guard-config | silent | diff tools/scan/latest_tag.py /tmp/x
Ws | feat/x | guard-config | silent | git diff -- tools/guard/guard.py
Ws | feat/x | guard-config | silent | cp tools/guard/guard.py /tmp/guard-0.9.0.py
Ws | feat/x | guard-config | silent | git show main:tools/guard/guard.py > /tmp/g.py
Ws | feat/x | guard-config | silent | python3 tools/guard/guard.py hook pre
Ws | feat/x | guard-config | silent | pytest tools/guard
Ws | feat/x | guard-config | silent | ruff check tools/scan
Ws | feat/x | guard-config | silent | python3 -c "print(open('tools/guard/guard.py').read()[:10])"
Ws | feat/x | guard-config | silent | echo tools/guard/guard.py > list.txt
Ws | feat/x | guard-config | silent | git checkout main -- docs/x.md
Ws | feat/x | guard-config | silent | "cat > notes.txt <<'EOF'\ntools/guard/guard.py\nEOF"
Wl | feat/x | guard-config | silent | git switch main
Wl | feat/x | guard-config | silent | git stash pop
Wl | feat/x | guard-config | silent | patch -p1 < fix.diff
# --- D8: the owner's stored GitHub credentials
K1 | feat/x | secret-shell | deny | gh auth token
K1 | feat/x | secret-shell | deny | gh auth token --hostname github.com
K1 | feat/x | secret-shell | deny | gh auth status -t
K1 | feat/x | secret-shell | deny | gh auth status --show-token
K1 | feat/x | secret-shell | deny | sudo -u dev gh auth token
K1 | feat/x | secret-shell | deny | x=$(gh auth token)
K1 | feat/x | secret-shell | deny | git credential fill
K1 | feat/x | secret-shell | deny | git credential approve
K1 | feat/x | secret-shell | deny | "printf 'protocol=https\\nhost=github.com\\n' | git credential fill"
K1 | feat/x | secret-shell | deny | git credential-osxkeychain get
K1 | feat/x | secret-shell | deny | git credential-manager get
K1 | feat/x | secret-shell | deny | git credential-manager-core get
K1 | feat/x | secret-shell | deny | git credential-store get
K1 | feat/x | secret-shell | deny | git credential-cache get
K1 | feat/x | secret-shell | deny | git credential-libsecret get
K1 | feat/x | secret-shell | deny | git credential-wincred get
K1 | feat/x | secret-shell | deny | security find-generic-password -s github.com -w
K1 | feat/x | secret-shell | deny | security find-internet-password -s github.com -g
K1 | feat/x | secret-shell | deny | security find-internet-password -gs github.com
K1 | feat/x | secret-shell | deny | security dump-keychain
K1 | feat/x | secret-shell | deny | cat ~/.config/gh/hosts.yml
K1 | feat/x | secret-shell | deny | grep oauth_token ~/.config/gh/hosts.yml
K1 | feat/x | secret-shell | deny | cat ~/.git-credentials
K1 | feat/x | secret-shell | deny | cat $HOME/.git-credentials
K1 | feat/x | secret-shell | deny | unset GH_TOKEN
K1 | feat/x | secret-shell | deny | unset GITHUB_TOKEN; gh pr list
K1 | feat/x | secret-shell | deny | env -u GH_TOKEN gh pr list
K1 | feat/x | secret-shell | deny | env -u GITHUB_TOKEN git push origin feat/x
K1 | feat/x | secret-shell | deny | env --unset=GH_TOKEN gh api user
K1 | feat/x | secret-shell | deny | GH_TOKEN= gh api user
K1 | feat/x | secret-shell | deny | GH_TOKEN="" gh pr list
K1 | feat/x | secret-shell | deny | export GH_TOKEN=
K1 | feat/x | secret-shell | deny | env -i gh auth status
K1 | feat/x | secret-shell | deny | env -i git fetch
K1 | feat/x | secret-shell | deny | env -i HOME=/tmp gh api user
K1 | feat/x | secret-shell | deny | env -i bash -c 'gh api user'
K1 | feat/x | secret-shell | deny | bash -c 'gh auth token'
Ks | feat/x | shell | silent | gh auth status
Ks | feat/x | shell | silent | gh auth status -h github.com
Ks | feat/x | shell | silent | gh auth token --help
Ks | feat/x | shell | silent | git config --get credential.helper
Ks | feat/x | shell | silent | security list-keychains
Ks | feat/x | shell | silent | security find-generic-password -s x
Ks | feat/x | shell | silent | env -i PATH=/usr/bin python3 x.py
Ks | feat/x | shell | silent | ls ~/.config/gh
Ks | feat/x | shell | silent | gh pr list
# --- D9: the refs the guard reads
G1 | feat/x | git-guard | deny | git update-ref refs/remotes/origin/main abc123
G1 | feat/x | git-guard | deny | git update-ref -d refs/remotes/origin/main
G1 | feat/x | git-guard | deny | git -C sub update-ref refs/remotes/origin/main abc123
G1 | feat/x | git-guard | deny | bash -c 'git update-ref refs/remotes/origin/main abc123'
G1 | feat/x | git-guard | deny | "printf 'update refs/remotes/origin/main abc123\\n' | git update-ref --stdin"
G1 | feat/x | git-guard | deny | git replace abc123 def456
G1 | feat/x | git-guard | deny | git replace -f abc123 def456
G1 | feat/x | git-guard | deny | git replace -d abc123
G1 | feat/x | git-guard | deny | git replace --edit abc123
G1 | feat/x | git-guard | deny | git replace --graft abc123
G1 | feat/x | git-guard | deny | git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/other
G1 | feat/x | git-guard | deny | git symbolic-ref -d refs/remotes/origin/HEAD
G1 | feat/x | git-guard | deny | git push . abc123:refs/remotes/origin/main
G1 | feat/x | git-guard | deny | git push origin +HEAD:refs/remotes/origin/main
G1 | feat/x | git-guard | deny | git branch -d -r origin/main
G1 | feat/x | git-guard | deny | git branch -dr origin/main
G1 | feat/x | git-guard | deny | git branch --delete --remotes origin/main
G1 | feat/x | git-guard | deny | git branch -r -m origin/a origin/b
G2 | feat/x | git-guard | ask | git remote set-url origin https://example.org/x.git
G2 | feat/x | git-guard | ask | git remote set-url --push origin https://example.org/x.git
G2 | feat/x | git-guard | ask | git remote rename origin old
G2 | feat/x | git-guard | ask | git remote remove origin
G2 | feat/x | git-guard | ask | git remote rm origin
G2 | feat/x | git-guard | ask | git config remote.origin.url https://example.org/x.git
G2 | feat/x | git-guard | ask | git config remote.origin.pushurl https://example.org/x.git
G2 | feat/x | git-guard | ask | git config --add remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
G2 | feat/x | git-guard | ask | git config --unset remote.origin.url
G2 | feat/x | git-guard | ask | git config --remove-section remote.origin
G2 | feat/x | git-guard | ask | git fetch origin main:refs/remotes/origin/main
G2 | feat/x | git-guard | ask | git fetch origin +refs/heads/*:refs/remotes/origin/*
G2 | feat/x | git-guard | ask | git remote set-branches origin main
G2 | feat/x | git-guard | ask | git remote set-head origin -a
G2 | feat/x | git-guard | ask | git config url.https://example.org/.insteadOf https://github.com/
G2 | feat/x | git-guard | ask | git config --global url.x.pushInsteadOf y
Gs | feat/x | shell | silent | git fetch
Gs | feat/x | shell | silent | git fetch origin
Gs | feat/x | shell | silent | git fetch origin main
Gs | feat/x | shell | silent | git remote -v
Gs | feat/x | shell | silent | git remote get-url origin
Gs | feat/x | shell | silent | git remote add x https://example.org/x.git
Gs | feat/x | shell | silent | git replace
Gs | feat/x | shell | silent | git replace -l
Gs | feat/x | shell | silent | git replace --list
Gs | feat/x | shell | silent | git replace --format=short
Gs | feat/x | shell | silent | git symbolic-ref refs/remotes/origin/HEAD
Gs | feat/x | shell | silent | git symbolic-ref --short refs/remotes/origin/HEAD
Gs | feat/x | shell | silent | git config --get remote.origin.url
Gs | feat/x | shell | silent | git config remote.origin.url
Gs | feat/x | shell | silent | git update-ref refs/heads/feat abc123
Gs | feat/x | git-guard | silent | git branch -r
Gs | feat/x | git-guard | silent | git branch -d feat/old
Gs | feat/x | git-guard | silent | git push origin feat/x
Gs | feat/x | git-guard | silent | git config --get url.x.insteadof
Gl | feat/x | git-guard | silent | git fetch . abc123:refs/heads/other
Gl | feat/x | git-guard | silent | echo abc123 > .git/refs/remotes/origin/main
# --- D6: an approval counts as a person's
P1 | feat/x | tracker-guard | ask | gh pr review 3 --approve
P1 | feat/x | tracker-guard | ask | gh pr review 3 -a
P1 | feat/x | tracker-guard | ask | gh pr review --approve 3 -b lgtm
P1 | feat/x | tracker-guard | ask | gh -R o/r pr review 3 --approve
P1 | feat/x | tracker-guard | ask | bash -c 'gh pr review 3 --approve'
Ps | feat/x | shell | silent | gh pr review 3 --comment -b x
Ps | feat/x | shell | silent | gh pr review 3 --request-changes -b x
Ps | feat/x | shell | silent | gh pr view 3
"""  # noqa: E501 (a row holds its command as written)

# id | tool | rule | expected | tool input as JSON
TOOL_ROWS = r"""
# --- D3: cloud-launch, the tool forms
T1 | Agent | cloud-launch | deny | {"description": "d", "prompt": "p", "subagent_type": "general-purpose", "isolation": "remote"}
T1 | Agent | cloud-launch | deny | {"description": "d", "prompt": "p", "isolation": "REMOTE"}
T1 | Task | cloud-launch | deny | {"description": "d", "prompt": "p", "isolation": "remote"}
T1 | Skill | cloud-launch | deny | {"skill": "schedule"}
T1 | Skill | cloud-launch | deny | {"skill": "/schedule", "args": "daily at 9"}
T1 | Skill | cloud-launch | deny | {"skill": "SCHEDULE"}
T1 | Skill | cloud-launch | deny | {"skill": "some-plugin:schedule"}
T1 | Workflow | cloud-launch | deny | {"script": "export const meta = {name: 'x'}\nawait agent('go', { isolation: 'remote' })"}
T1 | Workflow | cloud-launch | deny | {"script": "await agent('go', {isolation:\"remote\"})"}
T1 | Workflow | cloud-launch | deny | {"script": "await agent('go', {isolation : `remote`})"}
T1 | Workflow | cloud-launch | deny | {"script": "await agent('go', {\"isolation\": \"remote\"})"}
T1 | Workflow | cloud-launch | deny | {"script": "await agent('go', {'isolation': 'Remote'})"}
T1 | RemoteTrigger | cloud-launch | deny | {"action": "list"}
T1 | RemoteTrigger | cloud-launch | deny | {"action": "run", "trigger_id": "t1"}
T1 | RemoteTrigger | cloud-launch | deny | {}
Ts | Agent | cloud-launch | silent | {"description": "d", "prompt": "p", "subagent_type": "Explore"}
Ts | Agent | cloud-launch | silent | {"description": "d", "prompt": "p", "isolation": "worktree"}
Ts | Skill | cloud-launch | silent | {"skill": "loop", "args": "5m /verify"}
Ts | Skill | cloud-launch | silent | {"skill": "verify"}
Ts | Skill | cloud-launch | silent | {"skill": "schedule-notes"}
Ts | Workflow | cloud-launch | silent | {"script": "await agent('go', { isolation: 'worktree' })"}
Ts | Workflow | cloud-launch | silent | {"script": "// isolation remote is denied by the guard\nawait agent('go')"}
Tl | Workflow | cloud-launch | silent | {"name": "review-panel"}
Ts | CronCreate | cloud-launch | silent | {"cron": "7 * * * *", "prompt": "check the build"}
Ts | ScheduleWakeup | cloud-launch | silent | {"delaySeconds": 600, "prompt": "/loop x", "reason": "r"}
Tc | Agent | cloud-launch | ask | {"description": "d", "prompt": "p", "isolation": 1}
Tc | Agent | cloud-launch | ask | {"description": "d", "prompt": "p", "isolation": null}
Tc | Agent | cloud-launch | ask | {"description": "d", "prompt": "p", "isolation": ["remote"]}
Tc | Skill | cloud-launch | ask | {"skill": 5}
Tc | Skill | cloud-launch | ask | {}
Tc | Workflow | cloud-launch | ask | {"script": 5}
Tc | Workflow | cloud-launch | ask | {"scriptPath": "/nonexistent-scratch/x.js"}
Tc | Workflow | cloud-launch | ask | {"scriptPath": 7}
# --- the host's answers to the first run: Monitor is judged as Bash, ExitWorktree remove asks, DesignSync asks
M1 | Monitor | delete-guard | ask | {"command": "rm -rf build", "description": "d"}
M1 | Monitor | git-guard | deny | {"command": "git push --force origin feat/x", "description": "d"}
Ms | Monitor | delete-guard | silent | {"command": "tail -f /tmp/build.log", "description": "d"}
M2 | ExitWorktree | delete-guard | ask | {"action": "remove"}
M2 | ExitWorktree | delete-guard | ask | {"action": "remove", "discard_changes": true}
Mc | ExitWorktree | delete-guard | ask | {"action": 5}
Ms | ExitWorktree | delete-guard | silent | {"action": "keep"}
M3 | DesignSync | cloud-launch | ask | {}
M3 | DesignSync | cloud-launch | ask | {"action": "push", "files": ["a.png"]}
# --- D5: the harness's GitHub tools, by what they do
H1 | mcp__github__get_me | github-tools | silent | {}
H1 | mcp__github__get_pull_request | github-tools | silent | {"owner": "o", "repo": "r", "pullNumber": 3}
H1 | mcp__github__list_issues | github-tools | silent | {"owner": "o", "repo": "r"}
H1 | mcp__github__search_code | github-tools | silent | {"query": "x"}
H1 | mcp__github__pull_request_read | github-tools | silent | {"method": "get", "owner": "o", "repo": "r", "pullNumber": 3}
H1 | mcp__github__issue_read | github-tools | silent | {"method": "get", "owner": "o", "repo": "r", "issue_number": 3}
H1 | mcp__github__get_file_contents | github-tools | silent | {"owner": "o", "repo": "r", "path": "README.md"}
H1 | mcp__github__get_file_contents | github-tools | ask | {"owner": "o", "repo": "r", "path": ".env"}
H2 | mcp__github__create_branch | github-tools | silent | {"owner": "o", "repo": "r", "branch": "feat/x"}
H2 | mcp__github__create_pull_request | github-tools | silent | {"owner": "o", "repo": "r", "title": "x", "head": "feat/x", "base": "main"}
H2 | mcp__github__update_pull_request | github-tools | silent | {"owner": "o", "repo": "r", "pullNumber": 3, "body": "x"}
H2 | mcp__github__update_pull_request_branch | github-tools | silent | {"owner": "o", "repo": "r", "pullNumber": 3}
H2 | mcp__github__request_copilot_review | github-tools | silent | {"owner": "o", "repo": "r", "pullNumber": 3}
H2 | mcp__github__create_pending_pull_request_review | github-tools | silent | {"owner": "o", "repo": "r", "pullNumber": 3}
H2 | mcp__github__add_comment_to_pending_review | github-tools | silent | {"owner": "o", "repo": "r", "pullNumber": 3, "body": "x"}
H2 | mcp__github__add_pull_request_review_comment_to_pending_review | github-tools | silent | {"pullNumber": 3, "body": "x"}
H2 | mcp__github__pull_request_review_write | github-tools | silent | {"method": "create", "pullNumber": 3, "event": "COMMENT", "body": "x"}
H2 | mcp__github__create_and_submit_pull_request_review | github-tools | silent | {"pullNumber": 3, "event": "REQUEST_CHANGES", "body": "x"}
H2 | mcp__github__submit_pending_pull_request_review | github-tools | silent | {"pullNumber": 3, "event": "COMMENT"}
H3 | mcp__github__merge_pull_request | github-tools | ask | {"owner": "o", "repo": "r", "pullNumber": 3}
H3 | mcp__github__merge_pull_request | github-tools | ask | {"owner": "o", "repo": "r", "pullNumber": "3", "merge_method": "squash"}
H3 | mcp__github__enable_pr_auto_merge | github-tools | ask | {"owner": "o", "repo": "r", "pullNumber": 3}
H3 | mcp__github__pull_request_review_write | github-tools | ask | {"method": "create", "pullNumber": 3, "event": "APPROVE"}
H3 | mcp__github__create_and_submit_pull_request_review | github-tools | ask | {"pullNumber": 3, "event": "approve"}
H3 | mcp__github__submit_pending_pull_request_review | github-tools | ask | {"pullNumber": 3, "event": "Approve"}
H4 | mcp__github__issue_write | github-tools | deny | {"method": "create", "owner": "o", "repo": "r", "title": "x"}
H4 | mcp__github__create_issue | github-tools | deny | {"owner": "o", "repo": "r", "title": "x"}
H4 | mcp__github__update_issue | github-tools | deny | {"owner": "o", "repo": "r", "issue_number": 3, "state": "closed"}
H4 | mcp__github__add_issue_comment | github-tools | deny | {"owner": "o", "repo": "r", "issue_number": 3, "body": "x"}
H4 | mcp__github__sub_issue_write | github-tools | deny | {"method": "add", "issue_number": 3, "sub_issue_id": 4}
H4 | mcp__github__assign_copilot_to_issue | github-tools | deny | {"owner": "o", "repo": "r", "issueNumber": 3}
H4 | mcp__github__label_write | github-tools | deny | {"method": "create", "name": "x"}
H4 | mcp__github__create_label | github-tools | deny | {"name": "x"}
H4 | mcp__github__update_label | github-tools | deny | {"name": "x", "new_name": "y"}
H4 | mcp__github__delete_label | github-tools | deny | {"name": "x"}
H5 | mcp__github__create_or_update_file | github-tools | silent | {"owner": "o", "repo": "r", "path": "src/a.py", "content": "x", "message": "m", "branch": "feat/x"}
H5 | mcp__github__create_or_update_file | github-tools | deny | {"owner": "o", "repo": "r", "path": "src/a.py", "content": "x", "message": "m"}
H5 | mcp__github__create_or_update_file | github-tools | deny | {"owner": "o", "repo": "r", "path": "src/a.py", "content": "x", "message": "m", "branch": "main"}
H5 | mcp__github__create_or_update_file | github-tools | deny | {"owner": "o", "repo": "r", "path": ".env", "content": "A=1", "message": "m", "branch": "feat/x"}
H5 | mcp__github__create_or_update_file | github-tools | ask | {"owner": "o", "repo": "r", "path": "tools/guard/guard.py", "content": "x", "message": "m", "branch": "feat/x"}
H5 | mcp__github__create_or_update_file | github-tools | ask | {"owner": "o", "repo": "r", "path": ".github/workflows/ci.yml", "content": "x", "message": "m", "branch": "feat/x"}
H5 | mcp__github__push_files | github-tools | silent | {"owner": "o", "repo": "r", "branch": "feat/x", "message": "m", "files": [{"path": "a.py", "content": "x"}]}
H5 | mcp__github__push_files | github-tools | ask | {"owner": "o", "repo": "r", "branch": "feat/x", "message": "m", "files": [{"path": "a.py", "content": "x"}, {"path": "tools/scan/latest_tag.py", "content": "x"}]}
H5 | mcp__github__push_files | github-tools | deny | {"owner": "o", "repo": "r", "branch": "main", "message": "m", "files": [{"path": "a.py", "content": "x"}]}
H5 | mcp__github__delete_file | github-tools | ask | {"owner": "o", "repo": "r", "path": "src/a.py", "message": "m", "branch": "feat/x"}
H5 | mcp__github__delete_file | github-tools | deny | {"owner": "o", "repo": "r", "path": "src/a.py", "message": "m", "branch": "main"}
H5 | mcp__github__delete_file | github-tools | deny | {"owner": "o", "repo": "r", "path": ".env", "message": "m", "branch": "feat/x"}
H6 | mcp__github__fork_repository | github-tools | ask | {"owner": "o", "repo": "r"}
H6 | mcp__github__create_repository | github-tools | ask | {"name": "x"}
H6 | mcp__github__run_workflow | github-tools | ask | {"owner": "o", "repo": "r", "workflow_id": "ci.yml", "ref": "main"}
H6 | mcp__github__dismiss_notification | github-tools | ask | {"threadID": "1", "state": "done"}
Hc | mcp__github__merge_pull_request | github-tools | ask | {"pullNumber": 3.5}
Hc | mcp__github__merge_pull_request | github-tools | ask | {"pullNumber": "3; rm -rf x"}
Hc | mcp__github__merge_pull_request | github-tools | ask | {"pullNumber": true}
Hc | mcp__github__push_files | github-tools | ask | {"branch": "feat/x", "files": "a.py"}
Hc | mcp__github__push_files | github-tools | ask | {"branch": "feat/x", "files": [{"content": "x"}]}
Hc | mcp__github__push_files | github-tools | ask | {"branch": "feat/x", "files": [5]}
Hc | mcp__github__create_or_update_file | github-tools | ask | {"content": "x", "branch": "feat/x"}
Hc | mcp__github__create_or_update_file | github-tools | ask | {"path": 5, "branch": "feat/x"}
Hc | mcp__github__create_or_update_file | github-tools | ask | {"path": "a.py", "branch": 5}
Hc | mcp__github__delete_file | github-tools | ask | {"branch": "feat/x"}
Hc | mcp__github__get_file_contents | github-tools | ask | {"owner": "o", "repo": "r"}
"""  # noqa: E501 (a row holds its input as written)

# what each op reports as its twin, in the reason (D5)
TWIN_REASONS = [
    ("mcp__github__merge_pull_request", {"pullNumber": 3}, "`gh pr merge 3`"),
    ("mcp__github__enable_pr_auto_merge", {"pullNumber": 3}, "`gh pr merge 3 --auto`"),
    ("mcp__github__pull_request_review_write", {"pullNumber": 3, "event": "APPROVE"}, "`gh pr review 3 --approve`"),
    ("mcp__github__add_issue_comment", {"issue_number": 3, "body": "x"}, "`gh issue comment 3`"),
    ("mcp__github__create_or_update_file", {"path": "src/a.py", "content": "x"}, "`git push origin HEAD:main`"),
]


def _rows(text: str) -> list:
    out = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        rid, where, rule, expected, rest = (p.strip() for p in line.split(" | ", 4))
        out.append((rid, where, rule, expected, rest))
    return out


SHELL_TABLE = _rows(SHELL_ROWS)
TOOL_TABLE = _rows(TOOL_ROWS)


def _shell_answers(guard, monkeypatch, where: str, rule: str, command: str) -> dict:
    branch, _, boundary = where.partition("@")
    if command.startswith('"'):
        command = json.loads(command)
    monkeypatch.setattr(guard, "current_branch", lambda cwd: branch)
    cfg = dict(guard.DEFAULTS, host_install="ask", boundary=boundary or "own")
    ev = guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                      "cwd": "/nonexistent-scratch"})
    names = [n for n in SHELL_RULES if n in guard.RULES] if rule == "shell" else [rule]
    return {name: (guard.RULES[name](ev, cfg) or ("silent",))[0] for name in names}


@pytest.mark.parametrize("rid, where, rule, expected, command", SHELL_TABLE,
                         ids=[f"{row[0]}-{n}" for n, row in enumerate(SHELL_TABLE)])
def test_shell_row(guard, monkeypatch, rid, where, rule, expected, command):
    got = _shell_answers(guard, monkeypatch, where, rule, command)
    assert {k: v for k, v in got.items() if v != expected} == {}, command


def _tool_event(tool: str, tool_input, copilot: bool = False) -> dict:
    if copilot:  # the VS Code shape: tool_name as Copilot names it, and its timestamp
        tool = tool.replace("mcp__github__", "github-mcp-server-")
        return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                "cwd": "/nonexistent-scratch", "timestamp": "2026-11-20T10:00:00.000Z", "session_id": "s"}
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "cwd": "/nonexistent-scratch", "transcript_path": "/t", "permission_mode": "default", "session_id": "s"}


def _tool_answer(guard, monkeypatch, tool: str, rule: str, text: str, copilot: bool = False):
    monkeypatch.setattr(guard, "current_branch", lambda cwd: "feat/x")
    ev = guard.Event(_tool_event(tool, json.loads(text), copilot))
    return ev, guard.RULES[rule](ev, dict(guard.DEFAULTS, host_install="ask"))


@pytest.mark.parametrize("rid, tool, rule, expected, text", TOOL_TABLE,
                         ids=[f"{row[0]}-{n}" for n, row in enumerate(TOOL_TABLE)])
def test_tool_row(guard, monkeypatch, rid, tool, rule, expected, text):
    _ev, got = _tool_answer(guard, monkeypatch, tool, rule, text)
    assert (got or ("silent",))[0] == expected, (tool, text, got)
    if got:
        assert got[1], "a reason is mandatory"


@pytest.mark.parametrize("rid, tool, rule, expected, text", [r for r in TOOL_TABLE if r[1].startswith("mcp__")],
                         ids=[f"{row[0]}-{n}" for n, row in enumerate(r for r in TOOL_TABLE
                                                                       if r[1].startswith("mcp__"))])
def test_a_copilot_github_tool_is_read_like_the_claude_one(guard, monkeypatch, rid, tool, rule, expected, text):
    """D4: in .github/hooks/guard.json every tool reaches the guard; `github-mcp-server-<op>` is read like
    `mcp__github__<op>` (unverified name form, fixtures only)."""
    ev, got = _tool_answer(guard, monkeypatch, tool, rule, text, copilot=True)
    assert ev.harness == "copilot" and ev.kind == "github"
    assert (got or ("silent",))[0] == expected, (tool, text, got)


@pytest.mark.parametrize("tool, tool_input, twin", TWIN_REASONS, ids=lambda x: str(x)[:40])
def test_the_reason_names_the_tool_and_its_twin(guard, monkeypatch, tool, tool_input, twin):
    _ev, got = _tool_answer(guard, monkeypatch, tool, "github-tools", json.dumps(tool_input))
    assert got is not None
    assert got[1].startswith(f"github-tools: {tool} is the same act as {twin}: "), got[1]


def test_an_unknown_github_tool_asks_with_the_named_reason(guard, monkeypatch):
    _ev, got = _tool_answer(guard, monkeypatch, "mcp__github__fork_repository", "github-tools", "{}")
    assert got == ("ask", "github-tools: mcp__github__fork_repository has no known twin and is not named as a read or "
                          "harmless; confirm this call.")


def test_github_tools_have_kind_github(guard):
    for tool in ("mcp__github__get_me", "mcp__github__merge_pull_request"):
        assert guard.Event(_tool_event(tool, {})).kind == "github"
    assert guard.Event(_tool_event("mcp__github__get_me", {}, copilot=True)).kind == "github"
    assert guard.Event(_tool_event("mcp__other__get_me", {})).kind == "other", "another server is no GitHub tool"
    for tool in ("Skill", "Workflow", "RemoteTrigger"):
        assert tool in guard.CLAUDE_TOOLS


def test_a_workflow_file_is_read(guard, monkeypatch, tmp_path):
    """D3: `scriptPath` is read; a file that names isolation remote is denied, one that does not stays silent."""
    remote, local = tmp_path / "remote.js", tmp_path / "local.js"
    remote.write_text("export const meta = {name: 'x'}\nawait agent('go', { isolation: 'remote' })\n")
    local.write_text("export const meta = {name: 'x'}\nawait agent('go', { isolation: 'worktree' })\n")
    for path, expected in ((remote, "deny"), (local, "silent")):
        _ev, got = _tool_answer(guard, monkeypatch, "Workflow", "cloud-launch", json.dumps({"scriptPath": str(path)}))
        assert (got or ("silent",))[0] == expected, path


def test_a_secret_path_through_get_file_contents_gets_secret_reads_answer(guard, monkeypatch):
    _ev, got = _tool_answer(guard, monkeypatch, "mcp__github__get_file_contents", "github-tools",
                            json.dumps({"path": "~/.git-credentials"}))
    assert got is not None and got[0] == "deny" and "stored GitHub credentials" in got[1], got


@pytest.mark.parametrize("path", ["~/.config/gh/hosts.yml", "~/.git-credentials", "/Users/dev/.config/GH/Hosts.YML"])
def test_the_read_tool_on_the_stored_login_is_denied(guard, path):
    """D8: the Read tool on the owner's stored GitHub login, through secret-read."""
    ev = guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": path},
                      "cwd": "/nonexistent-scratch"})
    got = guard.RULES["secret-read"](ev, dict(guard.DEFAULTS))
    assert got is not None and got[0] == "deny"
    assert "reads the owner's stored GitHub credentials; a session never does (plan rev 3, D6)." in got[1]


def test_the_credential_message(guard, monkeypatch):
    ev = guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "gh auth token"},
                      "cwd": "/nonexistent-scratch"})
    got = guard.RULES["secret-shell"](ev, dict(guard.DEFAULTS))
    assert got[0] == "deny" and got[1].startswith("secret-shell: ")
    assert got[1].endswith("reads the owner's stored GitHub credentials; a session never does (plan rev 3, D6).")


def test_a_shell_write_names_the_path_the_class_and_the_command(guard, monkeypatch):
    got = _shell_answers(guard, monkeypatch, "feat/x", "guard-config", "sed -i s/a/b/ tools/guard/guard.py")
    assert got == {"guard-config": "ask"}
    ev = guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                      "tool_input": {"command": "sed -i s/a/b/ tools/guard/guard.py"}, "cwd": "/nonexistent-scratch"})
    reason = guard.RULES["guard-config"](ev, dict(guard.DEFAULTS))[1]
    assert "tools/guard/guard.py" in reason and "the guard itself" in reason and "sed" in reason


@pytest.mark.parametrize("path, what", [
    (".github/workflows/ci.yml", "a CI workflow"), (".github/workflows/sub/x.yml", "a CI workflow"),
    ("tools/testguard/testguard.py", "the test guard"), ("tools/scan/latest_tag.py", "the tag scan"),
    ("tools/tracker/tracker.py", "the tracker"), ("tools/commit_msg.py", "the commit message gate"),
    ("TOOLS/Tracker/tracker.py", "the tracker"),
])
def test_the_wider_paths_of_guard_config(guard, path, what):
    """D7: the class names what the file enforces. The wording of the class is the rows' choice. Matched by path
    parts, as tools/guard is: a `tools/scan` below `docs/` asks too (the row first said silent; D7 settles it)."""
    assert guard.guard_config_class(os.path.join("/r", path)) == what
    for other in ("tools/commit_msg.py.bak", "docs/scan/x.md", ".github/workflow/ci.yml", "tools/scanner/x"):
        assert guard.guard_config_class(os.path.join("/r", other)) is None, other


# ----------------------------------------------------------------------------
# D2: KZ_BOUNDARY only tightens
# ----------------------------------------------------------------------------

def _policy(root, committed=None, local=None):
    os.makedirs(root / ".claude", exist_ok=True)
    os.makedirs(root / ".git", exist_ok=True)
    if committed is not None:
        (root / ".claude" / "guard.json").write_text(committed if isinstance(committed, str)
                                                     else json.dumps(committed))
    if local is not None:
        (root / ".claude" / "guard.local.json").write_text(json.dumps(local))
    return str(root)


@pytest.mark.parametrize("committed, env, expected, note", [
    ({"boundary": "own"}, "client", "client", False),          # tightening
    ({"boundary": "client"}, "own", "client", True),           # refused loosening
    ({"boundary": "client"}, "client", "client", False),
    ({"boundary": "own"}, "own", "own", False),
    (None, "own", "own", False),                               # no guard.json: the default stays own
    (None, "client", "client", False),
    ({"boundary": "own"}, "Client", "client", True),           # an unknown value counts as client
    ({"boundary": "own"}, "OWN", "client", True),
    ({"boundary": "own"}, "onw", "client", True),
    ({"boundary": "own"}, "strict", "client", True),
    ({"boundary": "own"}, None, "own", False),
    ({"boundary": "Own"}, None, "client", True),               # a committed unknown value counts as client
    ({"boundary": "CLIENT"}, None, "client", True),
    ({"boundary": "x"}, "own", "client", True),
    ({"boundary": 5}, None, "client", True),
])
def test_kz_boundary_only_tightens(guard, tmp_path, monkeypatch, capsys, committed, env, expected, note):
    monkeypatch.delenv("KZ_RULES_OFF", raising=False)
    if env is None:
        monkeypatch.delenv("KZ_BOUNDARY", raising=False)
    else:
        monkeypatch.setenv("KZ_BOUNDARY", env)
    cwd = _policy(tmp_path, committed)
    capsys.readouterr()
    assert guard.load_config(cwd)["boundary"] == expected
    err = capsys.readouterr().err
    assert ("boundary" in err) == note, err


def test_rules_off_needs_an_effective_own_boundary(guard, tmp_path, monkeypatch):
    """D2: a committed own and KZ_BOUNDARY=OWN (an unknown value, so client) leave the rule's ask in force."""
    monkeypatch.delenv("KZ_RULES_OFF", raising=False)
    monkeypatch.setenv("KZ_BOUNDARY", "OWN")
    cwd = _policy(tmp_path, {"boundary": "own"}, {"rules_off": ["delete-guard"]})
    final, rows = _hook(guard, monkeypatch, _bash(cwd, "rm -rf build"))
    assert final is not None and final[0] == "ask"
    assert [r["verdict"] for r in rows] == ["ask"]


# ----------------------------------------------------------------------------
# D1: the profile; in a cloud session every ask is a deny and rules_off is ignored
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (None, "host"), ("", "host"), ("0", "host"), ("false", "host"), ("FALSE", "host"), ("False", "host"),
    ("true", "cloud"), ("1", "cloud"), ("TRUE", "cloud"), ("yes", "cloud"),
])
def test_one_function_names_the_profile(guard, value, expected):
    assert guard.profile({} if value is None else {"CLAUDE_CODE_REMOTE": value}) == expected


def test_the_profile_table_has_one_entry_per_profile(guard):
    assert set(guard.PROFILES) == {"host", "cloud"}


def _bash(cwd, command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd, "session_id": "s1",
            "transcript_path": "/t", "tool_use_id": "toolu_1", "tool_input": {"command": command}}


def _tool(cwd, tool, tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": cwd, "session_id": "s1",
            "transcript_path": "/t", "tool_use_id": "toolu_1", "tool_input": tool_input}


def _hook(guard, monkeypatch, raw, target="pre"):
    """One event through run_hook: (the response, the decision log rows)."""
    seen = []
    monkeypatch.setattr(guard, "_read_event", lambda: json.loads(json.dumps(raw)))
    monkeypatch.setattr(guard, "respond", lambda final, event: seen.append(final) or 0)
    guard.run_hook(target, None)
    log = os.path.join(guard.telemetry_dir(guard.load_config(raw["cwd"])), "decisions.jsonl")
    rows = [json.loads(ln) for ln in open(log).read().splitlines()] if os.path.exists(log) else []
    return seen[-1], rows


# rule -> (event maker over the repo root, what to set up); every rule that can ask, and the guard's own asks
ASKS = {
    "delete-guard": lambda r: _bash(r, "rm -rf build"),
    "secret-write": lambda r: _tool(r, "Write", {"file_path": os.path.join(r, "infra", "prod.tfvars"), "content": "x"}),
    "secret-read": lambda r: _tool(r, "Read", {"file_path": os.path.join(r, ".env")}),
    "secret-shell": lambda r: _bash(r, "cat .env"),
    "git-guard": lambda r: _bash(r, "git config core.hooksPath /tmp/h"),
    "deploy-ask": lambda r: _bash(r, "terraform apply"),
    "scratch-md": lambda r: _tool(r, "Write", {"file_path": os.path.join(r, "notes.md"), "content": "x"}),
    "protected-branch": lambda r: _bash(r, "git update-ref --stdin"),
    "fan-out": lambda r: _tool(r, "Agent", {"description": "d", "prompt": "p", "subagent_type": "Explore"}),
    "guard-config": lambda r: _tool(r, "Edit", {"file_path": os.path.join(r, "tools", "guard", "guard.py"),
                                                "old_string": "a", "new_string": "b"}),
    "tracker-guard": lambda r: _bash(r, "gh pr merge 3"),
    "host-install": lambda r: _bash(r, "npm ci"),
    "cloud-launch": lambda r: _tool(r, "Skill", {"skill": 5}),
    "github-tools": lambda r: _tool(r, "mcp__github__fork_repository", {"owner": "o", "repo": "r"}),
}
SOURCES = ("guard.json", "guard.local.json", "KZ_RULES_OFF")


def _cloud_repo(guard, tmp_path, monkeypatch, rule, source):
    """An own repo whose rules_off names the rule through one source; host_install is `ask` in the committed file
    so host-install asks in the box and on the host alike."""
    monkeypatch.delenv("KZ_RULES_OFF", raising=False)
    monkeypatch.delenv("KZ_BOUNDARY", raising=False)
    monkeypatch.delenv("KZ_HOST_INSTALL", raising=False)
    committed = {"boundary": "own", "host_install": "ask"}
    local = None
    if source == "guard.json":
        committed["rules_off"] = [rule]
    elif source == "guard.local.json":
        local = {"rules_off": [rule]}
    else:
        monkeypatch.setenv("KZ_RULES_OFF", rule)
    root = _policy(tmp_path, committed, local)
    monkeypatch.setattr(guard, "current_branch", lambda cwd: "feat/x")
    monkeypatch.setattr(guard, "log_spawn", lambda ev, cfg: guard.FANOUT_FIRST)  # the sixth spawn
    return root


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("rule", sorted(ASKS))
def test_in_a_cloud_session_every_ask_is_a_deny_and_rules_off_is_ignored(guard, tmp_path, monkeypatch, rule, source):
    root = _cloud_repo(guard, tmp_path, monkeypatch, rule, source)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    final, rows = _hook(guard, monkeypatch, ASKS[rule](root))
    assert final is not None and final[0] == "deny", (rule, final)
    assert final[1].startswith(CLOUD_PREFIX + " "), final[1]
    assert [r["verdict"] for r in rows] == ["deny"], "no skipped line in a cloud session"
    assert rows[0]["rules"].get(rule) == "deny" and rows[0]["profile"] == "cloud"


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("rule", sorted(ASKS))
def test_on_the_host_the_same_rules_off_silences_the_ask(guard, tmp_path, monkeypatch, rule, source):
    """The control of the row above: host keeps 0.9.0's behaviour, a skipped line with the profile."""
    root = _cloud_repo(guard, tmp_path, monkeypatch, rule, source)
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    final, rows = _hook(guard, monkeypatch, ASKS[rule](root))
    assert final is None, (rule, final)
    assert [(r["verdict"], r["rules"], r["profile"]) for r in rows] == [("skipped", {rule: "skipped"}, "host")]


@pytest.mark.parametrize("rule", sorted(ASKS))
def test_in_a_cloud_session_each_ask_is_a_deny_with_its_own_reason(guard, tmp_path, monkeypatch, rule):
    root = _cloud_repo(guard, tmp_path / "x", monkeypatch, "egress-guard", "guard.json")  # rules_off names another
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    host, _rows = _hook(guard, monkeypatch, ASKS[rule](root))
    assert host is not None and host[0] == "ask", (rule, host)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "1")
    cloud, _rows = _hook(guard, monkeypatch, ASKS[rule](root))
    assert cloud == ("deny", CLOUD_PREFIX + " " + host[1])


def test_egress_in_a_client_repo_is_a_deny_in_a_cloud_session(guard, tmp_path, monkeypatch):
    root = _policy(tmp_path, {"boundary": "client"})
    monkeypatch.delenv("KZ_BOUNDARY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    final, _rows = _hook(guard, monkeypatch, _bash(root, "ollama run llama3"))
    assert final is not None and final[0] == "deny" and final[1].startswith(CLOUD_PREFIX)


@pytest.mark.parametrize("raw_of", [
    lambda r: _bash(r, "gh pr merge 3"),
    lambda r: _bash(r, "gh pr merge 3 --squash --auto"),
    lambda r: _tool(r, "mcp__github__merge_pull_request", {"owner": "o", "repo": "r", "pullNumber": 3}),
])
def test_a_merge_is_denied_in_a_cloud_session(guard, tmp_path, monkeypatch, raw_of):
    root = _policy(tmp_path, {"boundary": "own"})
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    final, _rows = _hook(guard, monkeypatch, raw_of(root))
    assert final is not None and final[0] == "deny"


def test_the_guards_own_asks_are_denies_in_a_cloud_session(guard, tmp_path, monkeypatch):
    root = _policy(tmp_path, {"boundary": "own"})
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    raw = _bash(root, "ls")
    raw["tool_input"] = "{not json"
    final, rows = _hook(guard, monkeypatch, raw)
    assert final[0] == "deny" and final[1].startswith(CLOUD_PREFIX) and rows[-1]["rules"]["unreadable-args"] == "deny"
    monkeypatch.setattr(guard, "_run_rules", lambda names, ev, cfg: ([], "budget"))
    final, rows = _hook(guard, monkeypatch, _bash(root, "ls"))
    assert final[0] == "deny" and final[1].startswith(CLOUD_PREFIX) and rows[-1]["rules"]["budget"] == "deny"


def test_a_deny_is_unchanged_in_a_cloud_session(guard, tmp_path, monkeypatch):
    root = _policy(tmp_path, {"boundary": "own"})
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    host, _ = _hook(guard, monkeypatch, _bash(root, "git push --force origin feat/x"))
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    cloud, _ = _hook(guard, monkeypatch, _bash(root, "git push --force origin feat/x"))
    assert host == cloud and cloud[0] == "deny" and not cloud[1].startswith(CLOUD_PREFIX)


def test_host_install_auto_stays_silent_in_a_cloud_session_and_ask_denies(guard, tmp_path, monkeypatch):
    """D1: the knob is not rules_off; `auto` silences host-install in a cloud session (the machine is disposable),
    an explicit `ask` then denies."""
    monkeypatch.delenv("KZ_HOST_INSTALL", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    root = _policy(tmp_path / "auto", {"boundary": "own", "host_install": "auto"})
    final, rows = _hook(guard, monkeypatch, _bash(root, "npm ci"))
    assert final is None and [(r["verdict"], r["profile"]) for r in rows] == [("skipped", "cloud")]
    root = _policy(tmp_path / "ask", {"boundary": "own", "host_install": "ask"})
    final, _rows = _hook(guard, monkeypatch, _bash(root, "npm ci"))
    assert final is not None and final[0] == "deny"


def test_fan_out_as_its_own_hook_target_goes_through_the_table(guard, tmp_path, monkeypatch):
    root = _policy(tmp_path, {"boundary": "own"}, {"rules_off": ["fan-out"]})
    monkeypatch.setattr(guard, "log_spawn", lambda ev, cfg: guard.FANOUT_FIRST)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    final, _rows = _hook(guard, monkeypatch, ASKS["fan-out"](root), target="fan-out")
    assert final is not None and final[0] == "deny"


def test_every_log_line_names_the_profile(guard, tmp_path, monkeypatch):
    root = _policy(tmp_path, {"boundary": "own"})
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    _hook(guard, monkeypatch, _bash(root, "rm -rf build"))
    _hook(guard, monkeypatch, _bash(root, "git push --force origin feat/x"))
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    _final, rows = _hook(guard, monkeypatch, _bash(root, "rm -rf build"))
    assert [(r["verdict"], r["profile"]) for r in rows] == [("ask", "host"), ("deny", "host"), ("deny", "cloud")]


# ----------------------------------------------------------------------------
# Crashes: broken input to every new path answers ask or deny through the real entry point
# ----------------------------------------------------------------------------

CRASH_INPUTS = [
    ("Agent", {"description": "d", "prompt": "p", "isolation": {"x": 1}}),
    ("Skill", {"skill": ["schedule"]}),
    ("Skill", {"skill": None}),
    ("Workflow", {"script": None}),
    ("Workflow", {"scriptPath": "/nonexistent-scratch/w.js"}),
    ("Workflow", {"scriptPath": ["x"]}),
    ("RemoteTrigger", {"action": 5}),
    ("mcp__github__merge_pull_request", {"pullNumber": [3]}),
    ("mcp__github__merge_pull_request", {"pullNumber": "-1"}),
    ("mcp__github__push_files", {"branch": "feat/x", "files": None}),
    ("mcp__github__push_files", {"branch": "feat/x", "files": [{"path": None}]}),
    ("mcp__github__push_files", {"branch": ["main"], "files": [{"path": "a"}]}),
    ("mcp__github__create_or_update_file", {"path": {"a": 1}}),
    ("mcp__github__delete_file", {"path": None, "branch": "feat/x"}),
    ("mcp__github__pull_request_review_write", {"pullNumber": 3, "event": 5}),
    ("mcp__github__get_file_contents", {"path": 5}),
    ("mcp__github__not_a_tool", "not an object"),
]


@pytest.mark.parametrize("tool, tool_input", CRASH_INPUTS, ids=lambda x: str(x)[:40])
def test_broken_input_to_a_new_path_asks_or_denies(guard_path, tmp_path, tool, tool_input):
    raw = _tool(str(tmp_path), tool, tool_input)
    env = {k: v for k, v in os.environ.items() if k not in ("KZ_RULES_OFF", "CLAUDE_CODE_REMOTE")}
    r = subprocess.run([sys.executable, guard_path, "hook", "pre", "--wrapper", "claude"], input=json.dumps(raw),
                       capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=30)
    assert "Traceback" not in r.stderr and r.returncode in (0, 2), r.stderr
    verdict = json.loads(r.stdout)["permissionDecision"] if r.stdout.strip() else "silent"
    assert verdict in ("ask", "deny"), (tool, tool_input, r.stdout)


def test_broken_input_answers_through_main_in_process(guard, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_tool(str(tmp_path), "Workflow", {"scriptPath": 7}))))
    code = guard.main(["hook", "pre", "--wrapper", "claude"])
    out = capsys.readouterr().out
    assert code == 0 and json.loads(out)["permissionDecision"] == "ask"


# ----------------------------------------------------------------------------
# D4 wiring and D12 version
# ----------------------------------------------------------------------------

def _settings():
    with open(os.path.join(REPO, ".claude", "settings.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _guard_matchers(settings, event, target):
    return [m["matcher"] for m in settings["hooks"].get(event, [])
            if any(f"guard.py hook {target}" in h["command"] for h in m["hooks"])]


def test_the_matchers_name_the_new_tools():
    """D4: the pre matcher and the two post matchers of the guard name Skill, Workflow, RemoteTrigger and the
    GitHub tools (the last part only if the probe of D11 shows the hook is called for them)."""
    s = _settings()
    for event, target in (("PreToolUse", "pre"), ("PostToolUse", "post"), ("PostToolUseFailure", "post")):
        (matcher,) = _guard_matchers(s, event, target)
        parts = matcher.split("|")
        for name in ("Skill", "Workflow", "RemoteTrigger", "DesignSync", "Monitor", "ExitWorktree", "mcp__github__.*"):
            assert name in parts, (event, matcher)


def test_the_version_is_0_10_0(guard):
    assert guard.VERSION == "0.10.0"
