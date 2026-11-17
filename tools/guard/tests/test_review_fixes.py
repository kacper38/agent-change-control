"""guard 0.7.0, the review's rule findings: each row names the branch the host is on, a rule, the verdict expected
of it and a command. `shell` means all eight shell rules stay silent."""
import pytest

SHELL = ["delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
         "tracker-guard", "host-install"]

# (id, branch, rule, expected, command)
ROWS = [
    # P1: `coproc NAME { …; }`: a name stands only in front of a compound command, so it is no command word
    ("P1", "feat/x", "delete-guard", "ask", "coproc p { rm -f x; }"),
    ("P1", "feat/x", "delete-guard", "ask", "coproc { rm -f x; }"),
    ("P1", "feat/x", "delete-guard", "ask", "coproc rm -f x"),
    ("P1", "feat/x", "delete-guard", "ask", "coproc p ( rm -f x )"),
    ("P1", "feat/x", "delete-guard", "ask", "coproc my_job { rm -f x; }"),
    ("P1", "feat/x", "delete-guard", "ask", "sudo coproc p { rm -f x; }"),
    ("P1", "feat/x", "git-guard", "deny", "coproc p { git push -f origin feat/x; }"),
    ("P1", "feat/x", "git-guard", "deny", "coproc p { git commit --no-verify -m x; }"),
    ("P1", "feat/x", "tracker-guard", "deny", "coproc p { gh issue close 3; }"),
    ("P1", "feat/x", "secret-shell", "ask", "coproc p { cat .env; }"),
    ("P1", "feat/x", "host-install", "ask", "coproc p { pip install requests; }"),
    ("P1", "feat/x", "deploy-ask", "ask", "coproc p { terraform apply; }"),
    ("P1", "main", "protected-branch", "deny", "coproc p { git commit -m x; }"),
    ("P1", "main", "git-guard", "deny", "coproc p { git push; }"),
    ("P1", "feat/x", "shell", "silent", "coproc p { ls; }"),
    ("P1", "feat/x", "shell", "silent", "coproc { sleep 5; }"),
    ("P1", "feat/x", "shell", "silent", "coproc sleep 5"),
    ("P1", "feat/x", "shell", "silent", "coproc rm_watch { tail -f log; }"),
    # A5: fd and fdfind run a command per match after -x, -X, --exec, --exec-batch
    ("A5", "feat/x", "delete-guard", "ask", "fd -e pyc -x rm"),
    ("A5", "feat/x", "delete-guard", "ask", "fd -e pyc -X rm -f"),
    ("A5", "feat/x", "delete-guard", "ask", "fd -e pyc --exec rm"),
    ("A5", "feat/x", "delete-guard", "ask", "fd -e pyc --exec-batch rm"),
    ("A5", "feat/x", "delete-guard", "ask", "fdfind -e pyc -x rm"),
    ("A5", "feat/x", "delete-guard", "ask", "fd -H -e orig . src -x rm -v"),
    ("A5", "feat/x", "delete-guard", "ask", "/usr/bin/fd -e pyc -x rm"),
    ("A5", "feat/x", "git-guard", "deny", "fd -e patch -x git push --force"),
    ("A5", "feat/x", "delete-guard", "silent", "fd -e py -x wc -l"),
    ("A5", "feat/x", "delete-guard", "silent", "fd -e py"),
    ("A5", "feat/x", "delete-guard", "silent", "fd pattern src"),
    ("A5", "feat/x", "delete-guard", "silent", "fd -e py -X ruff check"),
    ("A5", "feat/x", "delete-guard", "silent", "fd -x"),
    # A3: more runners (nix-shell, nix develop|shell, npx, npm exec) and containers (kubectl debug, oc rsh|debug)
    ("A3", "feat/x", "delete-guard", "ask", 'nix-shell --run "rm -rf build"'),
    ("A3", "feat/x", "delete-guard", "ask", 'nix-shell -p hello --run "rm -rf build"'),
    ("A3", "feat/x", "delete-guard", "ask", 'nix-shell --command "rm -rf build"'),
    ("A3", "feat/x", "delete-guard", "ask", 'nix-shell shell.nix --pure --run "rm -rf build"'),
    ("A3", "feat/x", "delete-guard", "ask", "nix-shell --run 'rm -rf build' shell.nix"),
    ("A3", "feat/x", "delete-guard", "ask", "nix develop -c rm -rf build"),
    ("A3", "feat/x", "delete-guard", "ask", "nix develop --command rm -rf build"),
    ("A3", "feat/x", "delete-guard", "ask", "nix develop .#ci -c rm -rf build"),
    ("A3", "feat/x", "delete-guard", "ask", "nix shell nixpkgs#jq -c rm -rf build"),
    ("A3", "feat/x", "delete-guard", "ask", "nix shell nixpkgs#jq --command rm -rf build"),
    ("A3", "feat/x", "delete-guard", "ask", "nix shell nixpkgs#jq nixpkgs#yq -c rm -rf build"),
    ("A3", "feat/x", "delete-guard", "ask", 'npx -c "rm -rf build"'),
    ("A3", "feat/x", "delete-guard", "ask", 'npx --call "rm -rf build"'),
    ("A3", "feat/x", "delete-guard", "ask", 'npm exec -c "rm -rf build"'),
    ("A3", "feat/x", "delete-guard", "ask", 'npm exec --call "rm -rf build"'),
    ("A3", "feat/x", "delete-guard", "ask", "kubectl debug web-0 -it --image=busybox -- rm -rf /data"),
    ("A3", "feat/x", "delete-guard", "ask", "oc rsh web-0 rm -rf /data"),
    ("A3", "feat/x", "delete-guard", "ask", "oc debug deploy/web -- rm -rf /data"),
    ("A3", "feat/x", "delete-guard", "ask", "oc exec web-0 -- rm -rf /data"),
    ("A3", "feat/x", "git-guard", "deny", 'nix-shell --run "git push --force"'),
    ("A3", "feat/x", "git-guard", "deny", "nix develop -c git push --force"),
    ("A3", "feat/x", "git-guard", "deny", "nix shell nixpkgs#git -c git push --force"),
    ("A3", "feat/x", "git-guard", "deny", 'npx -c "git push --force"'),
    ("A3", "feat/x", "git-guard", "deny", 'npm exec -c "git push --force"'),
    ("A3", "feat/x", "git-guard", "deny", "kubectl debug web-0 -it --image=busybox -- git push --force"),
    ("A3", "feat/x", "git-guard", "deny", "oc rsh web-0 git push --force"),
    ("A3", "feat/x", "host-install", "ask", 'nix-shell --run "pip install x"'),
    ("A3", "feat/x", "host-install", "ask", "nix develop -c pip install x"),
    ("A3", "feat/x", "host-install", "ask", "nix shell nixpkgs#python3 -c pip install x"),
    ("A3", "feat/x", "host-install", "ask", 'npx -c "pip install x"'),
    ("A3", "feat/x", "host-install", "silent", "kubectl debug web-0 -it --image=busybox -- pip install x"),
    ("A3", "feat/x", "host-install", "silent", "oc rsh web-0 pip install x"),
    ("A3", "feat/x", "host-install", "silent", "oc debug deploy/web -- pip install x"),
    ("A3", "main", "protected-branch", "deny", "nix develop -c git commit -m x"),
    ("A3", "main", "protected-branch", "deny", "nix-shell --run 'git commit -m x'"),
    ("A3", "main", "protected-branch", "silent", "oc rsh web-0 git commit -m x"),
    ("A3", "main", "protected-branch", "silent", "kubectl debug web-0 -it --image=busybox -- git commit -m x"),
    ("A3", "feat/x", "delete-guard", "silent", 'nix-shell --run "ls"'),
    ("A3", "feat/x", "delete-guard", "silent", 'nix-shell -p hello --run "ls"'),
    ("A3", "feat/x", "delete-guard", "silent", "nix develop -c ls"),
    ("A3", "feat/x", "delete-guard", "silent", "nix shell nixpkgs#jq -c jq . a.json"),
    ("A3", "feat/x", "delete-guard", "silent", "nix build .#rm"),
    ("A3", "feat/x", "delete-guard", "silent", 'npx -c "ls"'),
    ("A3", "feat/x", "delete-guard", "silent", "oc rsh web-0 ls"),
    ("A3", "feat/x", "delete-guard", "silent", "kubectl debug web-0 -it --image=busybox -- ls"),
    ("A3", "feat/x", "git-guard", "silent", 'nix-shell --run "git status"'),
    ("A3", "feat/x", "git-guard", "silent", "oc rsh web-0 git status"),
    ("A3", "feat/x", "deploy-ask", "ask", "kubectl debug web-0 -it --image=busybox"),
    ("A3", "feat/x", "deploy-ask", "ask", "kubectl debug node/n1 -it --image=busybox"),
    ("A3", "feat/x", "deploy-ask", "silent", "kubectl debug --help"),
]


def _ev(guard, command):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/work/repo",
                        "tool_input": {"command": command}})


@pytest.mark.parametrize("rid,branch,rule,expected,command", ROWS,
                         ids=[f"{r[0]}|{r[1]}|{r[2]}|{r[4][:60]}" for r in ROWS])
def test_review_row(guard, monkeypatch, rid, branch, rule, expected, command):
    monkeypatch.setattr(guard, "current_branch", lambda cwd: branch)
    cfg = {**guard.DEFAULTS, "host_install": "ask"}
    got = {}
    for name in (SHELL if rule == "shell" else [rule]):
        d = guard.RULES[name](_ev(guard, command), cfg)
        got[name] = d[0] if d else "silent"
    assert all(v == expected for v in got.values()), f"{rid} {command!r}: {got}"
