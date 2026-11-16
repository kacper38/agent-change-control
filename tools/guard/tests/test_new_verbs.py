"""guard 0.7.0, step 2: verbs the token tables never had (deploy-ask, delete-guard). `both` rows are silent in
both rules; `named` rows are the ones the 2026-11-15 review found silent."""
import pytest

# (rule, expected, origin, command)
ROWS = [
    ("deploy-ask", "ask", "named", "docker image push x"),
    ("deploy-ask", "ask", "named", "docker buildx build --push ."),
    ("deploy-ask", "ask", "named", "kubectl label pod x a=b"),
    ("deploy-ask", "ask", "named", "kubectl annotate pod x a=b"),
    ("deploy-ask", "ask", "named", "kubectl set image deploy/web web=x"),
    ("deploy-ask", "ask", "named", "kubectl run x --image y"),
    ("deploy-ask", "ask", "named", "kubectl taint nodes n k=v:NoSchedule"),
    ("deploy-ask", "ask", "named", "terraform workspace delete x"),
    ("deploy-ask", "ask", "named", "terraform force-unlock 123"),
    ("deploy-ask", "ask", "named", "aws s3api delete-object --bucket b --key k"),
    ("deploy-ask", "ask", "named", "aws ecs update-service --cluster c --service s"),
    ("deploy-ask", "ask", "named", "aws lambda update-function-code --function-name f"),
    ("deploy-ask", "ask", "named", "gh run rerun 1"),
    ("deploy-ask", "ask", "named", "gh workflow disable ci.yml"),
    ("deploy-ask", "ask", "named", "argocd app sync web"),
    ("deploy-ask", "ask", "named", "flux reconcile kustomization web"),
    ("deploy-ask", "ask", "named", "qm start 100"),
    ("deploy-ask", "ask", "named", "qm migrate 100 node2"),
    ("deploy-ask", "ask", "named", "pct destroy 101"),
    ("deploy-ask", "ask", "named", "skopeo copy a b"),
    ("deploy-ask", "ask", "named", "crane push a b"),
    ("deploy-ask", "ask", "named", "podman push x"),
    ("deploy-ask", "ask", "named", "az webapp deploy --name x"),
    ("deploy-ask", "ask", "named", "az containerapp update --name x"),
    ("delete-guard", "ask", "named", "docker image rm x"),
    ("delete-guard", "ask", "named", "docker container rm x"),
    ("delete-guard", "ask", "named", "docker network rm x"),
    ("delete-guard", "ask", "named", "git checkout main -- path"),
    ("delete-guard", "ask", "named", "git switch --discard-changes main"),
    ("delete-guard", "ask", "named", "pipx uninstall x"),
    ("delete-guard", "ask", "named", "helm repo remove x"),
    ("deploy-ask", "ask", "neighbour", "kubectl expose deploy web --port 80"),
    ("deploy-ask", "ask", "neighbour", "kubectl autoscale deploy web --max 3"),
    ("deploy-ask", "ask", "neighbour", "terraform state replace-provider a b"),
    ("deploy-ask", "ask", "neighbour", "gh workflow enable ci.yml"),
    ("deploy-ask", "ask", "neighbour", "argocd app delete web"),
    ("deploy-ask", "ask", "neighbour", "flux resume kustomization web"),
    ("delete-guard", "ask", "neighbour", "helm plugin uninstall x"),
    ("deploy-ask", "ask", "family", "podman image push x"),
    ("deploy-ask", "ask", "family", "nerdctl push x"),
    ("deploy-ask", "ask", "family", "docker build --push -t x ."),
    ("deploy-ask", "ask", "family", "docker buildx bake --push"),
    ("deploy-ask", "ask", "family", "docker manifest push x"),
    ("deploy-ask", "ask", "family", "tofu workspace delete x"),
    ("deploy-ask", "ask", "family", "tofu force-unlock 123"),
    ("deploy-ask", "ask", "family", "aws s3api delete-bucket --bucket b"),
    ("deploy-ask", "ask", "family", "aws ec2 terminate-instances --instance-ids i-1"),
    ("deploy-ask", "ask", "family", "aws rds delete-db-instance --db-instance-identifier d"),
    ("deploy-ask", "ask", "family", "aws --profile prod ec2 delete-volume --volume-id v"),
    ("deploy-ask", "ask", "family", "aws lambda update-function-configuration --function-name f"),
    ("deploy-ask", "ask", "family", "gh run cancel 1"),
    ("deploy-ask", "ask", "family", "gh run delete 1"),
    ("deploy-ask", "ask", "family", "argocd app rollback web"),
    ("deploy-ask", "ask", "family", "argocd app set web -p a=b"),
    ("deploy-ask", "ask", "family", "argocd app create web --repo r --path p"),
    ("deploy-ask", "ask", "family", "argocd app patch web --patch x"),
    ("deploy-ask", "ask", "family", "flux delete kustomization web"),
    ("deploy-ask", "ask", "family", "flux create source git web --url u"),
    ("deploy-ask", "ask", "family", "flux bootstrap github --owner o"),
    ("deploy-ask", "ask", "family", "qm reboot 100"),
    ("deploy-ask", "ask", "family", "qm suspend 100"),
    ("deploy-ask", "ask", "family", "qm resume 100"),
    ("deploy-ask", "ask", "family", "qm clone 100 101"),
    ("deploy-ask", "ask", "family", "qm rollback 100 snap"),
    ("deploy-ask", "ask", "family", "qm create 102"),
    ("deploy-ask", "ask", "family", "qm set 100 --memory 2048"),
    ("deploy-ask", "ask", "family", "qm delsnapshot 100 snap"),
    ("deploy-ask", "ask", "family", "pct start 101"),
    ("deploy-ask", "ask", "family", "pct stop 101"),
    ("deploy-ask", "ask", "family", "pct shutdown 101"),
    ("deploy-ask", "ask", "family", "pct reboot 101"),
    ("deploy-ask", "ask", "family", "pct migrate 101 node2"),
    ("deploy-ask", "ask", "family", "pct clone 101 102"),
    ("deploy-ask", "ask", "family", "pct rollback 101 snap"),
    ("deploy-ask", "ask", "family", "pct create 103 tmpl"),
    ("deploy-ask", "ask", "family", "pct set 101 --memory 512"),
    ("deploy-ask", "ask", "family", "pct restore 101 backup"),
    ("deploy-ask", "ask", "family", "pct delsnapshot 101 snap"),
    ("deploy-ask", "ask", "family", "skopeo delete docker://x"),
    ("deploy-ask", "ask", "family", "skopeo sync --src docker --dest dir a b"),
    ("deploy-ask", "ask", "family", "crane copy a b"),
    ("deploy-ask", "ask", "family", "crane delete x"),
    ("deploy-ask", "ask", "family", "crane tag a b"),
    ("deploy-ask", "ask", "family", "az webapp up --name x"),
    ("deploy-ask", "ask", "family", "az containerapp up --name x"),
    ("deploy-ask", "ask", "family", "az webapp update --name x"),
    ("deploy-ask", "ask", "family", "az functionapp deploy --name x"),
    ("delete-guard", "ask", "family", "podman rm x"),
    ("delete-guard", "ask", "family", "podman rmi x"),
    ("delete-guard", "ask", "family", "podman system prune"),
    ("delete-guard", "ask", "family", "nerdctl rm x"),
    ("delete-guard", "ask", "family", "nerdctl rmi x"),
    ("delete-guard", "ask", "family", "docker network prune"),
    ("delete-guard", "ask", "family", "docker buildx rm b"),
    ("delete-guard", "ask", "family", "docker buildx prune"),
    ("delete-guard", "ask", "family", "docker context rm c"),
    ("delete-guard", "ask", "family", "git checkout ."),
    ("delete-guard", "ask", "family", "git checkout HEAD -- ."),
    ("delete-guard", "ask", "family", "git checkout feat -- src/a.py"),
    ("delete-guard", "ask", "family", "git -C sub checkout main -- path"),
    ("delete-guard", "ask", "family", "git switch -f main"),
    ("delete-guard", "ask", "family", "git switch --force main"),
    ("delete-guard", "ask", "family", "pipx uninstall-all"),
    ("delete-guard", "ask", "family", "uv pip uninstall x"),
    ("delete-guard", "ask", "family", "uv tool uninstall x"),
    ("delete-guard", "ask", "family", "helm repo rm x"),
    ("delete-guard", "ask", "family", "helm plugin remove x"),
    ("both", "silent", "silent", "docker image ls"),
    ("both", "silent", "silent", "docker images"),
    ("both", "silent", "silent", "docker container ls"),
    ("both", "silent", "silent", "docker network ls"),
    ("both", "silent", "silent", "docker buildx build ."),
    ("both", "silent", "silent", "docker buildx ls"),
    ("both", "silent", "silent", "docker build -t x ."),
    ("both", "silent", "silent", "docker context ls"),
    ("both", "silent", "silent", "podman ps"),
    ("both", "silent", "silent", "podman images"),
    ("both", "silent", "silent", "kubectl get pods"),
    ("both", "silent", "silent", "kubectl describe pod x"),
    ("both", "silent", "silent", "kubectl logs x"),
    ("both", "silent", "silent", "kubectl top pods"),
    ("both", "silent", "silent", "kubectl config set-context prod"),
    ("both", "silent", "silent", "kubectl label --help"),
    ("both", "silent", "silent", "kubectl run --help"),
    ("both", "silent", "silent", "terraform workspace list"),
    ("both", "silent", "silent", "terraform workspace select x"),
    ("both", "silent", "silent", "terraform workspace show"),
    ("both", "silent", "silent", "terraform force-unlock -help"),
    ("both", "silent", "silent", "terraform state list"),
    ("both", "silent", "silent", "aws s3api get-object --bucket b --key k out"),
    ("both", "silent", "silent", "aws s3api list-objects --bucket b"),
    ("both", "silent", "silent", "aws ecs describe-services --cluster c"),
    ("both", "silent", "silent", "aws lambda get-function --function-name f"),
    ("both", "silent", "silent", "aws ec2 describe-instances"),
    ("both", "silent", "silent", "aws --profile prod s3 ls"),
    ("both", "silent", "silent", "aws sts get-caller-identity"),
    ("both", "silent", "silent", "gh run view 1"),
    ("both", "silent", "silent", "gh run list"),
    ("both", "silent", "silent", "gh run watch 1"),
    ("both", "silent", "silent", "gh workflow list"),
    ("both", "silent", "silent", "gh workflow view ci.yml"),
    ("both", "silent", "silent", "gh pr view 3"),
    ("both", "silent", "silent", "argocd app get web"),
    ("both", "silent", "silent", "argocd app list"),
    ("both", "silent", "silent", "argocd app diff web"),
    ("both", "silent", "silent", "flux get kustomizations"),
    ("both", "silent", "silent", "flux logs"),
    ("both", "silent", "silent", "qm list"),
    ("both", "silent", "silent", "qm status 100"),
    ("both", "silent", "silent", "qm config 100"),
    ("both", "silent", "silent", "pct list"),
    ("both", "silent", "silent", "pct status 101"),
    ("both", "silent", "silent", "skopeo inspect docker://x"),
    ("both", "silent", "silent", "crane digest x"),
    ("both", "silent", "silent", "crane ls x"),
    ("both", "silent", "silent", "az webapp list"),
    ("both", "silent", "silent", "az webapp show --name x"),
    ("both", "silent", "silent", "az containerapp show --name x"),
    ("both", "silent", "silent", "az webapp deployment list-publishing-profiles --name x"),
    ("both", "silent", "silent", "az repos pr update --id 1 --description x"),
    ("both", "silent", "silent", "az repos pr create --title x"),
    ("both", "silent", "silent", "helm repo list"),
    ("both", "silent", "silent", "helm repo add x https://example.invalid/charts"),
    ("both", "silent", "silent", "helm repo update"),
    ("both", "silent", "silent", "helm plugin list"),
    ("both", "silent", "silent", "git checkout main"),
    ("both", "silent", "silent", "git checkout -b feat/x"),
    ("both", "silent", "silent", "git checkout feat/x"),
    ("both", "silent", "silent", "git checkout HEAD~1"),
    ("both", "silent", "silent", "git checkout main --"),
    ("both", "silent", "silent", "git switch main"),
    ("both", "silent", "silent", "git switch -c feat/x"),
    ("both", "silent", "silent", "pipx list"),
    ("both", "silent", "silent", "uv pip list"),
    ("both", "silent", "silent", "uv tool list"),
    ("both", "silent", "silent", 'echo "kubectl label pod x a=b"'),
    ("both", "silent", "silent", 'git commit -m "docs: argocd app sync runs in CI"'),
    ("both", "silent", "silent", 'grep -rn "qm start" docs/'),
]


def _ev(guard, command):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/work/repo",
                        "tool_input": {"command": command}})


@pytest.mark.parametrize("rule,expected,origin,command", ROWS, ids=[f"{r[2]}|{r[3]}" for r in ROWS])
def test_verb_row(guard, rule, expected, origin, command):
    rules = ["delete-guard", "deploy-ask"] if rule == "both" else [rule]
    got = {r: guard.RULES[r](_ev(guard, command), {}) for r in rules}
    if expected == "silent":
        assert not any(got.values()), f"{command!r}: {got}"
    else:
        assert all(d and d[0] == expected for d in got.values()), f"{command!r}: {got}"


def test_the_table_has_31_named_rows():
    assert sum(1 for r in ROWS if r[2] == "named") == 31


@pytest.mark.parametrize("command,label", [
    ("aws s3api delete-object --bucket b --key k", "aws deletes or terminates resources"),
    ("aws ecs update-service --cluster c --service s", "aws updates a service or function"),
    ("aws cloudformation delete-stack --stack-name x", "CloudFormation"),
    ("aws --profile prod s3 rm s3://b/k", "aws s3 deletes"),
    ("docker buildx build --push .", "pushes an image"),
])
def test_labels_say_what_changes(guard, command, label):
    assert guard.deploy_what(command) == label


@pytest.mark.parametrize("command", [
    "aws s3 cp delete-me.txt s3://b/", "aws --debug ec2 describe-instances", "docker build -t x . --pushy",
    "kubectl run --dry-run=client x --image y", "argocd app sync --help", "gh run rerun -h",
    "az webapp deploy --help", "skopeo copy --help",
])
def test_reads_and_probes_stay_silent(guard, command):
    assert guard.rule_deploy_ask(_ev(guard, command), {}) is None


@pytest.mark.parametrize("command", [
    "aws --debug ec2 delete-volume --volume-id v", "aws --profile prod --region eu ec2 terminate-instances",
    "aws ec2 --region eu-west-1 delete-volume --volume-id v", "sudo podman manifest push x",
    "timeout 60 docker buildx bake --push", "bash -c 'crane delete x'",
])
def test_new_rows_behind_options_and_wrappers_ask(guard, command):
    got = guard.rule_deploy_ask(_ev(guard, command), {})
    assert got and got[0] == "ask", command


@pytest.mark.parametrize("command", [
    "sudo git checkout . ", "bash -c 'git switch -f main'", "uv tool --quiet uninstall x", "pipx --verbose uninstall x",
])
def test_new_deletes_behind_options_and_wrappers_ask(guard, command):
    got = guard.rule_delete_guard(_ev(guard, command), {})
    assert got and got[0] == "ask", command
