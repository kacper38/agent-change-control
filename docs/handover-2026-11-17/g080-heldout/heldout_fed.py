#!/usr/bin/env python3
"""Held-out check for guard 0.8.0: a script fed to a shell, in forms the engineer has not seen.

Each cell is one form with `{}` replaced by one payload; the payload's rule decides.
  fed      the fed form must give at least the verdict the same guard gives for the reference form
           (`bash -c '{}'`, `ssh build '{}'`, `docker exec web sh -c '{}'`); so a rule that judges this
           machine only stays silent where its reference is silent.
  data     the body or the echo is data: every rule must answer as the old guard does (no new ask).
  limit    not readable from the line by design: reported, nothing required.
Every cell, whatever its kind: no rule may answer weaker than the old guard.
Commands are strings handed to rule functions; nothing runs.

usage: python3 -I heldout_fed.py <old guard.py> <new guard.py> [--cells]
"""
import collections
import importlib.util
import json
import sys

RULES = ["delete-guard", "secret-shell", "git-guard", "deploy-ask", "egress-guard", "protected-branch",
         "tracker-guard", "host-install"]
RANK = {"silent": 0, "ask": 1, "deny": 2}

# (rule, branch, boundary, payload); no quote characters in a payload
PAYLOADS = [
    ("delete-guard", "feat/x", "own", "rm -rf build"),
    ("delete-guard", "feat/x", "own", "git branch -D old"),
    ("git-guard", "feat/x", "own", "git commit --no-verify -m x"),
    ("git-guard", "feat/x", "own", "git push --force origin feat"),
    ("git-guard", "feat/x", "own", "git push origin feat:main"),
    ("secret-shell", "feat/x", "own", "cat .env"),
    ("secret-shell", "feat/x", "own", "git add .env"),
    ("deploy-ask", "feat/x", "own", "terraform apply -auto-approve"),
    ("deploy-ask", "feat/x", "own", "kubectl apply -f k8s/"),
    ("host-install", "feat/x", "own", "npm install -g x"),
    ("host-install", "feat/x", "own", "pip install requests"),
    ("tracker-guard", "feat/x", "own", "gh issue close 3"),
    ("protected-branch", "main", "own", "git commit -m x"),
    ("egress-guard", "feat/x", "client", "codex exec hi"),
]

LOCAL_REF = "bash -c '{}'"
SSH_REF = "ssh build '{}'"
DOCKER_REF = "docker exec web sh -c '{}'"

FED = [  # (name, form, reference)
    ("bash <<'EOF'", "bash <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("bash <<EOF", "bash <<EOF\n{}\nEOF", LOCAL_REF),
    ("bash -s <<'EOF'", "bash -s <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("sh <<-'EOF' tabs", "sh <<-'EOF'\n\t{}\n\tEOF", LOCAL_REF),
    ("bash -s -- a b", "bash -s -- a b <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("sudo bash", "sudo bash <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("sudo -u root sh -s <<'X'", "sudo -u root sh -s <<'X'\n{}\nX", LOCAL_REF),
    ("env FOO=1 bash", "env FOO=1 bash <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("bash -eu", "bash -eu <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("bash -o pipefail", "bash -o pipefail <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("zsh -s", "zsh -s <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("timeout 60 bash", "timeout 60 bash <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("/bin/bash", "/bin/bash <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("bash <<'EOF' 2>&1 | tee", "bash <<'EOF' 2>&1 | tee log.txt\n{}\nEOF", LOCAL_REF),
    ("body of three lines", "bash <<'EOF'\nset -e\necho start\n{}\necho done\nEOF", LOCAL_REF),
    ("cat <<'EOF' | bash", "cat <<'EOF' | bash\n{}\nEOF", LOCAL_REF),
    ("cat <<'EOF' | sudo sh -s", "cat <<'EOF' | sudo sh -s\n{}\nEOF", LOCAL_REF),
    ("echo ok && bash <<", "echo ok && bash <<'EOF'\n{}\nEOF", LOCAL_REF),
    ("bash << … then a line", "bash <<'EOF'\n{}\nEOF\necho after", LOCAL_REF),
    ("echo '…' | bash", "echo '{}' | bash", LOCAL_REF),
    ("echo \"…\" | sh", "echo \"{}\" | sh", LOCAL_REF),
    ("printf '…\\n' | bash", "printf '{}\\n' | bash", LOCAL_REF),
    ("printf '%s\\n' '…' | bash", "printf '%s\\n' '{}' | bash", LOCAL_REF),
    ("echo '…' | sudo bash", "echo '{}' | sudo bash", LOCAL_REF),
    ("echo '…' | bash -s", "echo '{}' | bash -s", LOCAL_REF),
    ("echo '…' | bash -s -- a", "echo '{}' | bash -s -- a", LOCAL_REF),
    ("echo '…' | zsh", "echo '{}' | zsh", LOCAL_REF),
    ("echo -e '…' | bash", "echo -e '{}' | bash", LOCAL_REF),
    ("echo '…' | /bin/sh", "echo '{}' | /bin/sh", LOCAL_REF),
    ("two lines by printf", "printf 'echo start\\n{}\\n' | bash", LOCAL_REF),
    ("ssh bash -s <<", "ssh build bash -s <<'EOF'\n{}\nEOF", SSH_REF),
    ("ssh 'bash -s' <<", "ssh build 'bash -s' <<'EOF'\n{}\nEOF", SSH_REF),
    ("ssh host <<", "ssh build <<'EOF'\n{}\nEOF", SSH_REF),
    ("ssh -T -p 2222 host <<", "ssh -T -p 2222 build <<'EOF'\n{}\nEOF", SSH_REF),
    ("echo | ssh bash", "echo '{}' | ssh build bash", SSH_REF),
    ("echo | ssh host", "echo '{}' | ssh build", SSH_REF),
    ("cat << | ssh bash", "cat <<'EOF' | ssh build bash\n{}\nEOF", SSH_REF),
    ("docker exec -i sh <<", "docker exec -i web sh <<'EOF'\n{}\nEOF", DOCKER_REF),
    ("echo | docker exec -i sh", "echo '{}' | docker exec -i web sh", DOCKER_REF),
    ("kubectl exec -i -- sh <<", "kubectl exec -i pod -- sh <<'EOF'\n{}\nEOF", DOCKER_REF),
]

DATA = [
    ("cat << > file", "cat <<'EOF' > notes.txt\n{}\nEOF"),
    ("cat <<", "cat <<'EOF'\n{}\nEOF"),
    ("cat > file <<", "cat > run.sh <<'EOF'\n{}\nEOF"),
    ("tee file <<", "tee run.sh <<'EOF'\n{}\nEOF"),
    ("git commit -F - <<", "git commit -F - <<'EOF'\n{}\nEOF"),
    ("python3 - << prints it", "python3 - <<'EOF'\nprint('''{}''')\nEOF"),
    ("mysql <<", "mysql db <<'EOF'\n{}\nEOF"),
    ("ssh cat <<", "ssh build cat <<'EOF'\n{}\nEOF"),
    ("bash -c 'cat' <<", "bash -c 'cat' <<'EOF'\n{}\nEOF"),
    ("bash script.sh <<", "bash script.sh <<'EOF'\n{}\nEOF"),
    ("echo | tee", "echo '{}' | tee plan.txt"),
    ("echo | grep", "echo '{}' | grep x"),
    ("echo > file", "echo '{}' > run.sh"),
    ("echo | pbcopy", "echo '{}' | pbcopy"),
    ("echo | wc -l", "echo '{}' | wc -l"),
    ("echo | ssh cat", "echo '{}' | ssh build cat"),
    ("echo | bash -c 'cat'", "echo '{}' | bash -c 'cat'"),
    ("echo | bash script.sh", "echo '{}' | bash script.sh"),
    ("echo; bash", "echo '{}'; bash"),
    ("echo || bash", "echo '{}' || bash"),
    ("echo && bash", "echo '{}' && bash"),
    ("echo alone", "echo '{}'"),
]

LIMIT = [
    ("echo | tee | bash", "echo '{}' | tee /dev/stderr | bash"),
    ("echo | cat | sh", "echo '{}' | cat | sh"),
    ("{ echo; } | bash", "{ echo '{}'; } | bash"),
    ("(echo) | bash", "(echo '{}') | bash"),
    ("bash < <(echo)", "bash < <(echo '{}')"),
    ("bash <(echo)", "bash <(echo '{}')"),
    ("echo > file; bash file", "echo '{}' > /tmp/x.sh; bash /tmp/x.sh"),
    ("variable | bash", "C='{}'; echo \"$C\" | bash"),
    ("echo | base64 | base64 -d | bash", "echo '{}' | base64 | base64 -d | bash"),
    ("echo | sed | bash", "echo '{}' | sed s/a/a/ | bash"),
    ("echo | su - user", "echo '{}' | su - deploy"),
    ("echo | docker run -i sh", "echo '{}' | docker run -i --rm img sh"),
]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def answers(g, branch, boundary, command):
    cfg = dict(g.DEFAULTS)
    cfg["host_install"] = "ask"
    cfg["boundary"] = boundary
    g.current_branch = lambda cwd, b=branch: b
    ev = g.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
                  "cwd": "/nonexistent-scratch"})
    got = {}
    for r in RULES:
        try:
            d = g.RULES[r](ev, cfg)
        except Exception as exc:  # a crash is a finding
            got[r] = "CRASH:" + type(exc).__name__
            continue
        got[r] = d[0] if d else "silent"
    return got


def rank(v):
    return RANK.get(v, 3)  # a crash sorts above everything and is printed


def main(argv):
    old, new = load(argv[1], "guard_old"), load(argv[2], "guard_new")
    show = "--cells" in argv
    count = collections.Counter()
    bad = []
    for rule, branch, boundary, payload in PAYLOADS:
        for kind, forms in (("fed", FED), ("data", [(n, f, None) for n, f in DATA]),
                            ("limit", [(n, f, None) for n, f in LIMIT])):
            for name, form, ref in forms:
                cmd = form.replace("{}", payload)
                o, n = answers(old, branch, boundary, cmd), answers(new, branch, boundary, cmd)
                count[kind, "cells"] += 1
                weaker = [r for r in RULES if rank(n[r]) < rank(o[r])]
                crash = [r for r in RULES if n[r].startswith("CRASH")]
                if weaker or crash:
                    count[kind, "weaker or crash"] += 1
                    bad.append((kind, "WEAKER/CRASH", name, rule, payload, {r: (o[r], n[r]) for r in weaker + crash}))
                if kind == "fed":
                    want = answers(new, branch, boundary, ref.replace("{}", payload))[rule]
                    if rank(n[rule]) < rank(want):
                        count[kind, "below the reference"] += 1
                        bad.append((kind, "BELOW", name, rule, payload, {"got": n[rule], "reference": want}))
                    elif rank(n[rule]) > rank(o[rule]):
                        count[kind, "newly read"] += 1
                    if show:
                        print(f"  {name:28} {rule:17} {payload:32} old {o[rule]:6} new {n[rule]:6} ref {want}")
                elif kind == "data":
                    diff = {r: (o[r], n[r]) for r in RULES if n[r] != o[r]}
                    if diff:
                        count[kind, "changed"] += 1
                        bad.append((kind, "CHANGED", name, rule, payload, diff))
                else:
                    count[kind, "asks or denies for the payload's rule"] += n[rule] != "silent"
    for kind, what, name, rule, payload, detail in sorted(bad, key=lambda b: b[:5])[:400]:
        print(f"{what:13} [{kind}] {name:28} {rule:17} {payload:30} {json.dumps(detail)}")
    print(f"guards: old {old.VERSION} | new {new.VERSION}")
    print(f"payloads {len(PAYLOADS)} | fed forms {len(FED)} | data forms {len(DATA)} | limit forms {len(LIMIT)}")
    for (kind, what), v in sorted(count.items()):
        print(f"{kind:6} {what:40} {v}")
    required_bad = sum(1 for b in bad if b[0] != "limit" or b[1] == "WEAKER/CRASH")
    return 1 if required_bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
