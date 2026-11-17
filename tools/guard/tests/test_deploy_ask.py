"""deploy-ask reads each command: the token reader, the subcommand walk, the per-call dry run, the
fail-closed path, and a frozen copy of the 0.6.0 rule as an oracle (the new rule asks wherever it asked)."""
import itertools
import re
import shlex
import time

import pytest


def _ev(guard, command, cwd="/work/repo"):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd,
                        "tool_input": {"command": command}})


def _deploy(guard, command):
    return guard.rule_deploy_ask(_ev(guard, command), {})


# ----------------------------------------------------------------------------
# The reader
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("command,expected", [
    ("terraform apply", ("terraform", "apply")),
    ("cd infra && terraform apply", ("terraform", "apply")),
    ("bash -c 'terraform apply'", ("terraform", "apply")),
    ("bash -lc \"kubectl apply -f k8s/\"", ("kubectl", "apply", "-f", "k8s/")),
    ("eval \"helm upgrade web ./chart\"", ("helm", "upgrade", "web", "./chart")),
    ("echo \"$(terraform apply -auto-approve)\"", ("terraform", "apply", "-auto-approve")),
    ("echo \"`pulumi up`\"", ("pulumi", "up")),
    ("echo $(terraform apply)", ("terraform", "apply")),
    ("ssh pve \"qm stop 100\"", ("qm", "stop", "100")),
    ("ssh -p 2222 pve 'sh -c \"qm stop 100\"'", ("qm", "stop", "100")),
    ("sudo -u deploy bash -c 'eval \"terraform destroy\"'", ("terraform", "destroy")),
])
def test_reader_yields_every_nested_simple_command(guard, command, expected):
    assert expected in guard.nested_commands(command)


def test_reader_keeps_a_quoted_mention_as_one_token(guard):
    got = guard.nested_commands("git commit -m \"note: terraform apply ran\"")
    assert got == (("git", "commit", "-m", "note: terraform apply ran"),)


def test_reader_unbalanced_quote_falls_back_to_raw_tokens(guard):
    got = guard.nested_commands("ls; terraform apply \"oops")
    assert ("ls",) in got and ("terraform", "apply", "oops") in got
    assert _deploy(guard, "ls; terraform apply \"oops")[0] == "ask"


@pytest.mark.parametrize("command,expected", [
    ("(terraform apply -auto-approve)\necho it's done", ("terraform", "apply", "-auto-approve")),
    ("echo $(terraform apply x.yml)\necho it's", ("terraform", "apply", "x.yml")),
    ("`kubectl delete ns x` y\necho 'oops", ("kubectl", "delete", "ns", "x")),
    ("\\terraform apply $'a\\'b'", ("terraform", "apply")),
])
def test_reader_fallback_reads_through_brackets_and_backslashes(guard, command, expected):
    got = guard.nested_commands(command)
    assert any(t[: len(expected)] == expected for t in got), got


@pytest.mark.parametrize("command,script", [
    ("bash -c -e 'terraform apply'", "terraform apply"),
    ("bash -c -- 'terraform apply'", "terraform apply"),
    ("bash --rcfile x -c 'terraform apply'", "terraform apply"),
    ("bash -O extglob -c 'terraform apply'", "terraform apply"),
    ("bash -c -o pipefail 'terraform apply'", "terraform apply"),
    ("bash -ce 'terraform apply'", "terraform apply"),
    ("su - deploy -c 'terraform apply'", "terraform apply"),
    ("$SHELL -c 'terraform apply'", "terraform apply"),
    ("${SHELL} -c 'terraform apply'", "terraform apply"),
    ("fish -c 'terraform apply'", "terraform apply"),
    ("script -qc 'terraform apply' /dev/null", "terraform apply"),
    ("flock /tmp/tf.lock -c 'terraform apply'", "terraform apply"),
    ("bash --command 'terraform apply'", "terraform apply"),
    ("bash <<< 'terraform apply'", "terraform apply"),
    ("bash <<<'terraform apply'", "terraform apply"),
    ("env -S 'terraform apply'", "terraform apply"),
    ("env --split-string 'terraform apply'", "terraform apply"),
    ("env --split-string='terraform apply'", "terraform apply"),
    ("watch -n 60 'date; terraform apply'", "terraform apply"),
    ("eval -- 'terraform apply'", "terraform apply"),
])
def test_reader_finds_the_script_a_shell_runs(guard, command, script):
    assert tuple(script.split()) in guard.nested_commands(command), command


def test_reader_drops_redirections_before_reading(guard):
    assert ("rm", "-rf", "build") in guard.nested_commands("2>/dev/null rm -rf build")
    assert ("rm", "-rf", "build") in guard.nested_commands("> log rm -rf build")
    assert ("bash",) in guard.nested_commands("bash <<< 'rm -rf build'")


@pytest.mark.parametrize("command,expected", [
    ("sudo -u bob rm x", {"sudo", "bob", "rm"}),
    ("sudo grep -rn rm /etc", {"sudo", "grep"}),
    ("timeout 10 grep -rn shred .", {"timeout", "grep"}),
    ("timeout -k 5 10 rm x", {"timeout", "10", "rm"}),
    ("ssh -p 22 host rm -rf /data", {"ssh", "host", "rm"}),
    ("ssh host cat /var/log/rm", {"ssh", "cat"}),
    ("watch -n 5 ls rm", {"watch", "5", "ls"}),
    # rm may be the value of -c3, so x may be the command: the walk cannot tell (fail closed)
    ("nohup nice -n 10 ionice -c3 rm x", {"nohup", "nice", "10", "ionice", "rm", "x"}),
    ("ssh host sudo rm x", {"ssh", "sudo", "rm"}),
    ("sudo -- rm x", {"sudo", "rm"}),
    ("env -i PATH=/bin rm x", {"env", "rm"}),
    ("time -p rm x", {"time", "rm", "x"}),
    ("/usr/bin/time rm x", {"/usr/bin/time", "rm"}),
    ("function f { rm x", {"rm"}),
    ("A=1 ! rm x", {"rm"}),
    ("find . -name x -exec grep -n unlink {} +", {"find", "grep"}),
    ("find . -execdir sudo rm {} +", {"find", "sudo", "rm"}),
    ("find . -type d -name trash", {"find"}),
    ("command -v rm", {"command"}),
    ("grep -rn rm .", {"grep"}),
])
def test_command_words_are_found(guard, command, expected):
    toks = command.split()
    assert {toks[i] for i in guard.command_word_indexes(toks)} == expected


def test_more_than_64_command_words_are_not_read(guard):
    assert len(guard.command_word_indexes(("nice",) * 64)) == 64
    with pytest.raises(guard.CommandNotRead):
        guard.command_word_indexes(("nice",) * 65)


def test_a_command_not_read_is_memoised_and_still_raises(guard, monkeypatch):
    command = _nest("echo memo", guard._HI_MAX_DEPTH + 1)
    with pytest.raises(guard.CommandNotRead):
        guard.nested_commands(command)
    reads = []
    real = guard._nc_read
    monkeypatch.setattr(guard, "_nc_read", lambda *a: reads.append(a) or real(*a))
    with pytest.raises(guard.CommandNotRead):
        guard.nested_commands(command)
    assert reads == [], "the second rule must not read the line again"


def test_reader_memoises_an_immutable_result(guard):
    command = "cd infra && terraform -chdir=x apply"
    first = guard.nested_commands(command)
    assert isinstance(first, tuple) and all(isinstance(t, tuple) for t in first)
    snapshot = [list(t) for t in first]
    _deploy(guard, command)
    guard.rule_delete_guard(_ev(guard, command), {})
    again = guard.nested_commands(command)
    assert again is first, "two rules of one hook run share one read"
    assert [list(t) for t in again] == snapshot


def _nest(command, depth):
    for _ in range(depth):
        command = "bash -c " + shlex.quote(command)
    return command


def test_nesting_is_read_to_the_limit_and_a_deeper_nest_asks(guard):
    limit = guard._HI_MAX_DEPTH
    for depth in range(1, limit + 1):
        assert _deploy(guard, _nest("terraform apply", depth)) == (
            "ask", guard.DEPLOY_MSG.format(what="terraform/tofu changes state")), depth
    too_deep = ("ask", guard.DEPLOY_MSG.format(what=guard._HI_NOT_READ))
    assert _deploy(guard, _nest("echo hi", limit + 1)) == too_deep
    assert _deploy(guard, "eval " * (limit + 1) + "echo hi") == too_deep
    assert _deploy(guard, "eval " * 5_000 + "echo hi") == too_deep
    assert _deploy(guard, _nest("echo hi", limit)) is None
    with pytest.raises(guard.CommandNotRead):
        guard.nested_commands(_nest("echo hi", limit + 1))


def test_too_many_tools_in_one_simple_command_asks(guard):
    cap = guard._MAX_TOOL_WORDS
    assert cap == 32
    too_many = ("ask", guard.DEPLOY_MSG.format(what=guard._TOO_MANY_TOOLS))
    assert _deploy(guard, "which " + "terraform " * cap) is None
    assert _deploy(guard, "which " + "terraform " * (cap + 1)) == too_many
    assert _deploy(guard, "terraform " * 10_000) == too_many
    assert _deploy(guard, "which terraform; " * 1_000) is None, "the cap counts per simple command"
    assert guard.rule_delete_guard(_ev(guard, "echo " + "git x " * (cap + 1)), {}) == (
        "ask", guard.DELETE_MSG.format(what=guard._TOO_MANY_TOOLS))


def test_a_crash_in_the_reader_asks(guard, monkeypatch):
    def boom(command):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(guard, "nested_commands", boom)
    assert _deploy(guard, "ls") == (
        "ask", guard.DEPLOY_MSG.format(what="the command could not be read (RuntimeError)"))
    assert guard.rule_delete_guard(_ev(guard, "ls"), {}) == (
        "ask", guard.DELETE_MSG.format(what="the command could not be read (RuntimeError)"))


@pytest.mark.parametrize("command", [
    "", "'", "\"", "\\", "$(", "`", "((((", "))))", "a" * 50_000, "terraform " * 10_000,
    "ssh h " + "'x y' " * 2_000, "bash -c " * 3_000, "echo eval " * 2_000, "command eval " * 2_000,
    "sudo " * 5_000 + "terraform apply",
])
def test_odd_input_never_raises(guard, command):
    for rule in (guard.rule_deploy_ask, guard.rule_delete_guard):
        got = rule(_ev(guard, command), {})
        assert got is None or got[0] == "ask"


# point 3 of the fix brief: these took up to 5.4 s at the first build (the hook's timeout is 5 s)
SLOW_INPUTS = [
    "sh -o " * 16500 + "\nrm -rf build", "zsh -o " * 14000, "sh " * 33000, "bash " * 20000, "\"$(echo " * 4000,
    "sudo -a " * 12000 + "rm x",
]


@pytest.mark.parametrize("command", SLOW_INPUTS, ids=lambda c: c[:8])
def test_long_lines_are_read_in_linear_time(guard, command):
    guard._nc_cached.cache_clear()
    ev = _ev(guard, command)
    start = time.perf_counter()
    got = [guard.rule_deploy_ask(ev, {}), guard.rule_delete_guard(ev, {})]
    took = time.perf_counter() - start
    assert all(g is None or g[0] == "ask" for g in got), got
    assert took < 1.5, f"{took:.2f} s: a slow hook fails open"


# ----------------------------------------------------------------------------
# Forms the fix pass still missed: found by a held-out check after it (inputs the engineer never saw)
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("command,script", [
    ("bash<<<'terraform apply'", "terraform apply"),  # a here-string needs no space in front
    ("bash<<< 'terraform apply'", "terraform apply"),
    ("env -S'terraform apply'", "terraform apply"),  # nor does env's split string
    ("bash -c '-x; terraform apply'", "terraform apply"),  # a script may start with a dash
    ("parallel 'kubectl delete pod {}' ::: a b", "kubectl delete pod {}"),
    ("tmux send-keys -t ops 'terraform apply' Enter", "terraform apply"),
    ("trap 'terraform destroy -auto-approve' EXIT", "terraform destroy -auto-approve"),
])
def test_reader_finds_the_scripts_of_the_held_out_forms(guard, command, script):
    assert tuple(script.split()) in guard.nested_commands(command), command


@pytest.mark.parametrize("command,expected", [
    ("time { rm x", {"time", "rm"}),  # a shell word behind a wrapper is not the command
    ("coproc { rm x", {"coproc", "rm"}),
    ("time if rm x", {"time", "rm"}),
    ("script -q /dev/null rm x", {"script", "rm", "x"}),  # BSD script: the file, then the command
    ("script /dev/null ls rm", {"script", "ls"}),
])
def test_command_words_of_the_held_out_forms(guard, command, expected):
    toks = command.split()
    assert {toks[i] for i in guard.command_word_indexes(toks)} == expected


@pytest.mark.parametrize("command", [
    "bash<<<'terraform apply'", "env -S'terraform apply'", "bash -c '-x; terraform apply'",
    "parallel 'kubectl delete pod {}' ::: a b", "tmux new-session -d 'terraform apply'",
    "trap 'helm uninstall web' EXIT",
])
def test_held_out_forms_ask(guard, command):
    got = _deploy(guard, command)
    assert got is not None and got[0] == "ask", command


@pytest.mark.parametrize("command", [
    "trap cleanup EXIT", "parallel echo ::: a b", "tmux send-keys 'terraform plan' Enter",
    "bash -c '-x; terraform plan'", "env LC_ALL=C sort -S10M apply.txt", "cat<<<'terraform apply'",
])
def test_held_out_forms_stay_silent_without_a_deploy(guard, command):
    assert _deploy(guard, command) is None, command


# ----------------------------------------------------------------------------
# The subcommand walk
# ----------------------------------------------------------------------------

KUBECTL = (frozenset({"apply", "delete"}), {})
DOCKER = (frozenset({"rm"}), {"compose": frozenset({"down"})})
AWS = (frozenset(), {"s3": frozenset({"rm"})})


@pytest.mark.parametrize("args,table,expected", [
    ("--context prod apply -f x", KUBECTL, "apply"),
    ("-n prod get pods", KUBECTL, None),
    ("get rollout x", KUBECTL, None),
    ("-n prod -- apply", KUBECTL, None),
    ("--context=prod apply", KUBECTL, "apply"),
    ("--context=prod x apply", KUBECTL, None),
    ("compose -f x.yml down", DOCKER, "compose down"),
    ("compose -f x.yml up -d", DOCKER, None),
    ("--context prod rm c1", DOCKER, "rm"),
    ("run --rm alpine rm x", DOCKER, None),
    ("--profile prod s3 rm s3://b/k", AWS, "s3 rm"),
    ("--profile prod s3 ls", AWS, None),
    ("apply >out.log 2>1", KUBECTL, "apply"),
    ("> out.log apply", KUBECTL, "apply"),
    ("2> err.log apply", KUBECTL, "apply"),
    ("-h apply", KUBECTL, None),
    ("--help delete", KUBECTL, None),
    ("-help apply", KUBECTL, None),
    ("--context prod -h apply", KUBECTL, None),
    ("--help compose down", DOCKER, None),
    ("apply -h", KUBECTL, "apply"),
])
def test_subcommand_walk(guard, args, table, expected):
    verbs, pairs = table
    assert guard.subcommand_hit(args.split(), verbs, pairs) == expected


# ----------------------------------------------------------------------------
# Dry run per tool call, and the words that no longer exempt
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "terraform apply plan", "gh workflow run lint", "kubectl apply -f plan", "ansible-playbook site.yml --diff",
    "kubectl apply -f k8s/ --dry-run=none", "kubectl apply -f k8s/ --dry-run=false", "kubectl apply --dry-run=0",
    "kubectl apply --dry-run=", "helm upgrade web ./chart --set mode=template", "kubectl apply -f diff/",
    "terraform plan -out p && terraform apply p", "kubectl diff -f x.yaml; kubectl apply -f x.yaml",
    "ansible-playbook site.yml && kubectl apply -f x --dry-run=client",
    "kubectl apply -f x.yaml --dry-run=client --dry-run=none", "helm upgrade web ./chart --dry-run --dry-run=none",
    "kubectl apply -f x.yaml --dry-run=f", "kubectl apply -f x.yaml --dry-run=nonsense",
    "az group delete --name validate --yes", "az deployment group create -g rg -n validate -f main.bicep",
])
def test_these_are_no_dry_run(guard, command):
    assert _deploy(guard, command)[0] == "ask", command


@pytest.mark.parametrize("command", [
    "kubectl apply -f x.yaml --dry-run", "kubectl apply -f x.yaml --dry-run=client",
    "kubectl apply -f x.yaml --dry-run=server", "kubectl apply -f x.yaml --dry-run=TRUE",
    "kubectl apply -f x.yaml --dry-run=none --dry-run=client", "helm upgrade web ./chart --dry-run",
    "ansible-playbook site.yml --check", "az deployment group validate -g rg -f main.bicep",
    "terraform plan", "kubectl diff -f x.yaml", "helm template web ./chart",
    "aws s3 sync . s3://b", "az repos pr create --title x", "az pipelines runs list",
    "terraform -help apply", "helm --help install", "kubectl -h delete",
])
def test_dry_runs_and_reads_stay_silent(guard, command):
    assert _deploy(guard, command) is None, command


# where the first build of 0.6.1 was silent and the 0.6.0 text pass asks: the text pass is back (fix brief, 1)
@pytest.mark.parametrize("command", [
    "git commit -m \"x; terraform apply now\"", "ansible-playbook --version",
    "az --debug repos pr create --title create",
])
def test_the_0_6_0_text_pass_asks_again(guard, command):
    assert _deploy(guard, command)[0] == "ask", command


def test_labels_are_those_of_0_6_0(guard):
    cases = {
        "terraform -chdir=infra apply": "terraform/tofu changes state",
        "kubectl --context prod apply -f k8s/": "kubectl changes the cluster",
        "helm -n prod uninstall web": "helm changes a release",
        "docker-compose push": "pushes an image",
        "gh workflow run lint": "triggers a workflow or release",
        "az pipelines run --name ci -o none": "triggers a pipeline run",
        "az --only-show-errors group delete -n rg": "az changes resources",
        "aws --profile prod cloudformation deploy --stack-name x": "CloudFormation",
        "aws --profile prod s3 sync . s3://b --delete": "aws s3 deletes",
        "hcloud server create --name x": "hcloud server lifecycle",
        "ssh pve \"qm stop 100\"": "Proxmox changes a guest",
        "npx cdk deploy": "pulumi/cdk deploys",
        "uv run --offline ansible-playbook site.yml": "ansible-playbook changes hosts",
        "flux suspend kustomization apps": "flux changes reconciliation",
    }
    for command, label in cases.items():
        assert _deploy(guard, command) == ("ask", guard.DEPLOY_MSG.format(what=label)), command


# ----------------------------------------------------------------------------
# Frozen oracle: the 0.6.0 rule, copied verbatim (do not edit when the rule changes)
# ----------------------------------------------------------------------------

_OLD_SEP_RE = re.compile(r"\|\||&&|[;|]|\n")
_OLD_DEPLOY_PATTERNS = [
    (
        r"(terraform|tofu)\s+(apply|destroy|import|taint|untaint|state\s+(rm|mv|push))",
        "terraform/tofu changes state",
    ),
    (
        r"kubectl\s+(apply|create|delete|rollout|drain|cordon|uncordon|scale|patch|replace|edit|exec)",
        "kubectl changes the cluster",
    ),
    (r"helm\s+(install|upgrade|uninstall|delete|rollback)", "helm changes a release"),
    (r"docker\s+push|docker\s+compose\s+push", "pushes an image"),
    (r"gh\s+workflow\s+run|gh\s+release\s+(create|delete|edit|upload)", "triggers a workflow or release"),
    (r"az\s+pipelines\s+(run|build\s+queue)", "triggers a pipeline run"),
    # `az repos pr create` opens a PR (pr-prep's job), it changes no environment
    (r"az\s+deployment|az\s+(?!repos\s+pr\s+create(\s|$))\S+(\s+\S+)*\s+(delete|create)", "az changes resources"),
    (
        r"aws\s+cloudformation\s+(deploy|create-stack|update-stack|delete-stack|execute-change-set)",
        "CloudFormation",
    ),
    (r"aws\s+s3\s+(rm|rb)|aws\s+s3\s+sync\s.*--delete", "aws s3 deletes"),
    (r"hcloud\s+server\s+(create|delete|rebuild|poweroff|reset|shutdown)", "hcloud server lifecycle"),
    (r"pvesh\s+(create|set|delete)|qm\s+(destroy|stop|shutdown|reset)", "Proxmox changes a guest"),
    (r"pulumi\s+(up|destroy)|cdk\s+(deploy|destroy)", "pulumi/cdk deploys"),
    (r"ansible-playbook", "ansible-playbook changes hosts"),
    (r"flux\s+(uninstall|suspend)", "flux changes reconciliation"),
]
_OLD_DEPLOY_RES = [
    (re.compile(r"(^|[;&|(`]|\$\()\s*(sudo\s+)?(" + p + r")(\s|$)", re.MULTILINE), label)
    for p, label in _OLD_DEPLOY_PATTERNS
]
_OLD_DRY_RE = re.compile(r"--dry-run|--check(\s|$)|\s--diff(\s|$)|\s(plan|validate|template|lint|diff)(\s|$)")


def _old_rule(guard, command):
    for part in _OLD_SEP_RE.split(guard.strip_heredocs(command)):
        if _OLD_DRY_RE.search(part):
            continue
        for rx, label in _OLD_DEPLOY_RES:
            if rx.search(" " + part.strip()) or rx.search(part):
                return "ask", guard.DEPLOY_MSG.format(what=label)
    return None


def _alternatives(head, words):
    return [f"{head} {w}" for w in words.split(",")]


# every alternative of every 0.6.0 pattern, written out
BASES = [
    *_alternatives("terraform", "apply,destroy,import,taint,untaint,state rm,state mv,state push"),
    *_alternatives("tofu", "apply,destroy,import,taint,untaint,state rm,state mv,state push"),
    *_alternatives("kubectl", "apply,create,delete,rollout,drain,cordon,uncordon,scale,patch,replace,edit,exec"),
    *_alternatives("helm", "install,upgrade,uninstall,delete,rollback"),
    "docker push", "docker compose push",
    "gh workflow run", *_alternatives("gh release", "create,delete,edit,upload"),
    "az pipelines run", "az pipelines build queue",
    "az deployment", "az deployment group create", "az group delete", "az vm create", "az storage account delete",
    *_alternatives("aws cloudformation", "deploy,create-stack,update-stack,delete-stack,execute-change-set"),
    "aws s3 rm", "aws s3 rb", "aws s3 sync . s3://b --delete",
    *_alternatives("hcloud server", "create,delete,rebuild,poweroff,reset,shutdown"),
    *_alternatives("pvesh", "create,set,delete"), *_alternatives("qm", "destroy,stop,shutdown,reset"),
    "pulumi up", "pulumi destroy", "cdk deploy", "cdk destroy",
    "ansible-playbook",
    "flux uninstall", "flux suspend",
]
TAILS = ["", " x.yml", " -f k8s/ --wait", " --name web 2>&1", " > out.log", " web ./chart", " plan"]
CONTEXTS = [
    "{}", "cd infra && {}", "ls; {}", "echo \"$({})\"", "echo $({})", "sudo {}", "({})", "echo `{}`",
    "true || {}", "{} | tee log", "make build\n{}", "git commit -m \"note\n{}\"",
    # the call inside a string another command runs, and inside a line with an unbalanced quote
    "su -c 'cd x; {}'", "$SHELL -c 'cd x && {}'", "bash -c -e 'cd x && {}'", "watch 'date; {}'",
    "bash <<< 'cd x && {}'", "echo 'cd x && {}' | bash", "tmux send-keys -t ops 'cd x && {}' Enter",
    "({})\necho it's", "echo $({})\necho it's", "`{}`\necho it's",
]


def _corpus():
    for base, tail, ctx in itertools.product(BASES, TAILS, CONTEXTS):
        yield ctx, base + tail, ctx.format(base + tail)


def test_oracle_bases_are_what_0_6_0_matched(guard):
    for base in BASES:
        assert _old_rule(guard, base) is not None, base


def test_oracle_new_rule_asks_wherever_0_6_0_asked(guard):
    total = old_asks = 0
    for _ctx, _call, command in _corpus():
        total += 1
        old = _old_rule(guard, command)
        if old is None:
            continue
        old_asks += 1
        new = _deploy(guard, command)
        assert new is not None, f"0.6.0 asked, 0.6.1 does not: {command!r}"
        assert new == old, f"label changed for {command!r}"
    assert total == len(BASES) * len(TAILS) * len(CONTEXTS) and old_asks > 9_000, (total, old_asks)


# ----------------------------------------------------------------------------
# The two reviews of the first build: every input with the verdict the guard must give (copied from the review
# file, cands-guard-review.txt of 2026-11-16). Format: <rule> <ask|none> <command>; "ML:" holds \n for a newline.
# ----------------------------------------------------------------------------

REVIEW = r"""
deploy-ask	ask	su -c 'cd infra; terraform apply -auto-approve'
deploy-ask	ask	watch -n 60 'date; kubectl rollout restart deploy/web -n prod'
deploy-ask	ask	$SHELL -c 'cd infra && terraform apply -auto-approve'
deploy-ask	ask	script -qc 'cd infra && terraform apply -auto-approve' /dev/null
deploy-ask	ask	tmux send-keys -t ops 'cd infra && terraform destroy -auto-approve' Enter
deploy-ask	ask	env -S 'x=1 && terraform apply -auto-approve'
deploy-ask	ask	fish -c 'cd infra; terraform apply -auto-approve'
deploy-ask	ask	flock /tmp/tf.lock -c 'cd infra && terraform apply -auto-approve'
deploy-ask	ask	bash <<< 'cd infra && terraform apply -auto-approve'
deploy-ask	ask	echo 'cd infra && terraform apply -auto-approve' | bash
deploy-ask	ask	make deploy ARGS='; terraform apply -auto-approve'
deploy-ask	ask	bash -c -e 'cd infra && terraform apply -auto-approve'
deploy-ask	ask	bash -O extglob -c 'cd infra && terraform apply -auto-approve'
deploy-ask	ask	git commit -m "x; terraform apply now"
deploy-ask	none	git commit -m "x; terraform apply"
deploy-ask	ask	su -c 'terraform apply -auto-approve'
deploy-ask	ask	su - deploy -c 'terraform apply -auto-approve'
deploy-ask	ask	$SHELL -c 'terraform apply'
deploy-ask	ask	${SHELL} -c 'terraform apply'
deploy-ask	ask	bash -c -e 'terraform apply'
deploy-ask	ask	bash -c -- 'terraform apply'
deploy-ask	ask	bash --rcfile x -c 'terraform apply'
deploy-ask	ask	bash -O extglob -c 'terraform apply'
deploy-ask	ask	bash -c -o pipefail 'terraform apply'
deploy-ask	ask	bash -ce 'terraform apply'
deploy-ask	ask	bash <<< 'terraform apply'
deploy-ask	ask	fish -c 'terraform apply'
deploy-ask	ask	script -qc 'terraform apply' /dev/null
deploy-ask	ask	flock /tmp/tf.lock -c 'terraform apply'
deploy-ask	ask	watch 'kubectl delete ns x'
deploy-ask	ask	env -S 'terraform apply'
deploy-ask	ask	env --split-string='terraform apply'
deploy-ask	ask	kubectl apply -f x.yaml --dry-run=client --dry-run=none
deploy-ask	ask	helm upgrade web ./chart --dry-run --dry-run=none
deploy-ask	ask	kubectl apply -f x.yaml --dry-run=f
deploy-ask	ask	kubectl apply -f x.yaml --dry-run=false
deploy-ask	ask	kubectl apply -f x.yaml --dry-run=
deploy-ask	ask	az group delete --name validate --yes
deploy-ask	ask	az deployment group create -g rg -n validate -f main.bicep
deploy-ask	ask	\terraform apply $'a\'b'
deploy-ask	ask	ML:(terraform apply -auto-approve)\necho it's done
deploy-ask	ask	ML:echo $(terraform apply x.yml)\necho it's
deploy-ask	ask	ML:`kubectl delete ns x` y\necho 'oops
deploy-ask	ask	ML:(helm uninstall web )\necho "oops
deploy-ask	ask	terraform apply plan
deploy-ask	ask	timeout 600 terraform apply -auto-approve
deploy-ask	ask	AWS_PROFILE=prod terraform apply
deploy-ask	none	terraform -help apply
deploy-ask	none	helm --help install
deploy-ask	none	kubectl --help apply
deploy-ask	none	gh --help workflow run
deploy-ask	none	kubectl apply -f x.yaml --dry-run=none --dry-run=client
deploy-ask	none	kubectl apply -f x.yaml --dry-run=server
deploy-ask	none	helm upgrade web ./chart --dry-run
deploy-ask	none	az deployment group validate -g rg -f main.bicep
deploy-ask	none	terraform plan -out tf.plan
deploy-ask	none	git commit -m "note: terraform apply ran"
deploy-ask	none	grep -rn "terraform apply" docs
delete-guard	ask	bash -c -- 'rm -rf build'
delete-guard	ask	bash -O extglob -c 'rm -rf build'
delete-guard	ask	bash --rcfile x -c 'rm -rf build'
delete-guard	ask	bash -c -o pipefail 'rm -rf build'
delete-guard	ask	$SHELL -c 'rm -rf build'
delete-guard	ask	su -c 'rm -rf build'
delete-guard	ask	env -S 'rm -rf build'
delete-guard	ask	bash <<< 'rm -rf build'
delete-guard	ask	ssh host rm -rf /data
delete-guard	ask	ssh host sudo rm -rf /data
delete-guard	ask	ssh -p 22 host rm -rf /data
delete-guard	ask	ssh -t host 'rm -rf /data'
delete-guard	ask	time -p rm -rf build
delete-guard	ask	/usr/bin/time rm -rf build
delete-guard	ask	2>/dev/null rm -rf build
delete-guard	ask	> log rm -rf build
delete-guard	ask	function f { rm -rf build; }; f
delete-guard	ask	coproc rm -rf build
delete-guard	ask	eval -- "rm -rf build"
delete-guard	ask	eval -- rm -rf build
delete-guard	ask	\rm -rf build $'a\'b'
delete-guard	ask	setsid rm -rf build
delete-guard	ask	flock /tmp/l rm -rf build
delete-guard	ask	flock -n /tmp/l rm -rf build
delete-guard	ask	chroot / rm -rf build
delete-guard	ask	strace rm -rf build
delete-guard	ask	timeout 5 rm -rf build
delete-guard	ask	timeout -s KILL 10 rm -rf build
delete-guard	ask	timeout -k 5 10 rm -rf build
delete-guard	ask	sudo -u bob rm -rf x
delete-guard	ask	sudo -u bob -g staff rm -rf x
delete-guard	ask	sudo -- rm -rf x
delete-guard	ask	nice -n 5 rm x
delete-guard	ask	nohup nice -n 10 ionice -c3 rm -rf x
delete-guard	ask	env -i PATH=/bin rm x
delete-guard	ask	xargs -n 1 rm
delete-guard	ask	xargs -I {} rm {}
delete-guard	ask	parallel -j4 rm {} ::: a b
delete-guard	ask	find . -name '*.tmp' -exec sudo rm {} \;
delete-guard	ask	find . -name '*.tmp' -execdir rm {} +
delete-guard	ask	watch rm -rf x
delete-guard	ask	command -p rm x
delete-guard	ask	exec -a name rm x
delete-guard	none	kubectl -h delete
delete-guard	none	find . -name "*.py" -exec grep -n unlink {} +
delete-guard	none	sudo grep -rn rm /etc/sudoers.d
delete-guard	none	timeout 10 grep -rn shred .
delete-guard	none	find . -type d -name trash
delete-guard	none	find . -path ./rm -prune -o -print
delete-guard	none	watch -n 5 ls rm
delete-guard	none	ssh host cat /var/log/rm
delete-guard	none	time grep -rn rm .
delete-guard	none	sudo -u bob grep -rn unlink src
delete-guard	none	nice -n 5 grep -c shred notes.txt
"""


def _review_cases():
    for line in REVIEW.strip().splitlines():
        rule, verdict, command = line.split(None, 2)
        if command.startswith("ML:"):
            command = command[3:].replace("\\n", "\n")
        yield rule, verdict, command


def test_review_file_is_copied_whole():
    assert len(list(_review_cases())) == 112


@pytest.mark.parametrize("rule,verdict,command", list(_review_cases()), ids=lambda x: str(x)[:48])
def test_review_inputs(guard, rule, verdict, command):
    got = guard.RULES[rule](_ev(guard, command), {})
    if verdict == "ask":
        assert got is not None and got[0] == "ask", command
    else:
        assert got is None, (command, got)


def test_any_error_in_either_rule_asks(guard, monkeypatch):
    def boom(*_a):
        raise KeyError("synthetic")
    monkeypatch.setattr(guard, "strip_heredocs", boom)
    assert _deploy(guard, "ls") == ("ask", guard.DEPLOY_MSG.format(what="the command could not be read (KeyError)"))
    assert guard.rule_delete_guard(_ev(guard, "ls"), {}) == (
        "ask", guard.DELETE_MSG.format(what="the command could not be read (KeyError)"))
