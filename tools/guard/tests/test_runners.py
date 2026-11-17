"""guard 0.7.0, step 3: commands behind runners (`uv run`, `mise exec`, `direnv exec DIR`, busybox) and inside
containers (`docker exec web`, `kubectl exec pod --`). A delete, a deploy, a forced push, a tracker bypass and a
secret file are judged there too; an install or a commit inside a container is not this machine's (silent)."""
import pytest

# (rule, expected, command); `delete-and-deploy` rows are silent in both of those rules
ROWS = [
    ("delete-guard", "ask", "uv run --offline rm -rf build"),
    ("delete-guard", "ask", "uv run rm -rf build"),
    ("delete-guard", "ask", "poetry run rm -rf build"),
    ("delete-guard", "ask", "pdm run rm -rf build"),
    ("delete-guard", "ask", "pipenv run rm -rf build"),
    ("delete-guard", "ask", "hatch run rm -rf build"),
    ("delete-guard", "ask", "conda run -n env rm -rf build"),
    ("delete-guard", "ask", "mise exec node@20 -- rm -rf build"),
    ("delete-guard", "ask", "mise x -- rm -rf build"),
    ("delete-guard", "ask", "asdf exec rm -rf build"),
    ("delete-guard", "ask", "bundle exec rm -rf build"),
    ("delete-guard", "ask", "npm exec -- rm -rf build"),
    ("delete-guard", "ask", "pnpm exec rm -rf build"),
    ("delete-guard", "ask", "yarn exec rm -rf build"),
    ("delete-guard", "ask", "direnv exec . rm -rf build"),
    ("delete-guard", "ask", "busybox rm -rf x"),
    ("delete-guard", "ask", "toybox rm -rf x"),
    ("delete-guard", "ask", 'docker run --rm -v "$PWD":/w alpine rm -rf /w/x'),
    ("delete-guard", "ask", "docker run --rm alpine rm -rf /w/x"),
    ("delete-guard", "ask", "docker exec web rm -rf /data"),
    ("delete-guard", "ask", "docker exec -it web rm -rf /data"),
    ("delete-guard", "ask", "docker container exec web rm -rf /data"),
    ("delete-guard", "ask", "docker compose exec web rm -rf /data"),
    ("delete-guard", "ask", "docker compose -f x.yml run --rm web rm -rf /data"),
    ("delete-guard", "ask", "docker-compose exec web rm -rf /data"),
    ("delete-guard", "ask", "podman run --rm alpine rm -rf /w/x"),
    ("delete-guard", "ask", "podman exec web rm -rf /data"),
    ("delete-guard", "ask", "nerdctl exec web rm -rf /data"),
    ("delete-guard", "ask", "kubectl exec web-0 -- rm -rf /data"),
    ("delete-guard", "ask", "kubectl exec -it web-0 -c app -- rm -rf /data"),
    ("delete-guard", "ask", "kubectl run tmp --image=alpine --rm -it -- rm -rf /data"),
    ("delete-guard", "ask", "devcontainer exec --workspace-folder . rm -rf build"),
    ("delete-guard", "ask", "sudo docker exec web rm -rf /data"),
    ("delete-guard", "ask", "timeout 60 docker exec web rm -rf /data"),
    ("delete-guard", "ask", "docker exec web sh -c 'rm -rf /data'"),
    ("delete-guard", "ask", "docker exec web git clean -fdx"),
    ("delete-guard", "ask", "uv run --offline git clean -fdx"),
    ("git-guard", "deny", "uv run --offline git push --force origin feat"),
    ("git-guard", "deny", "docker exec dev git push origin main"),
    ("git-guard", "deny", "poetry run git commit --no-verify -m x"),
    ("git-guard", "deny", "kubectl exec dev -- git push --force origin feat"),
    ("tracker-guard", "deny", "uv run --offline python3 tools/tracker/tracker.py owner done 3"),
    ("tracker-guard", "deny", "docker run --rm ghcr.io/cli/cli gh issue close 3"),
    ("secret-shell", "ask", "docker exec web cat .env"),
    ("secret-shell", "deny", "docker exec web cp x .env"),
    ("secret-shell", "deny", "uv run --offline cp x .env"),
    ("protected-branch", "deny", "uv run --offline git commit -m x"),
    ("protected-branch", "deny", "busybox sh -c 'git commit -m x'"),
    ("protected-branch", "silent", "docker exec dev git commit -m x"),
    ("protected-branch", "silent", "kubectl exec dev -- git commit -m x"),
    ("protected-branch", "silent", "ssh host 'git commit -m x'"),
    ("protected-branch", "silent", "devcontainer exec git commit -m x"),
    ("host-install", "ask", "uv run --offline npm install"),
    ("host-install", "ask", "poetry run pip install x"),
    ("host-install", "ask", "busybox sh -c 'npm install'"),
    ("host-install", "ask", "mise exec node@20 -- npm install"),
    ("host-install", "ask", "direnv exec . npm install"),
    ("host-install", "ask", "conda run -n env pip install x"),
    ("host-install", "silent", 'docker run --rm -v "$PWD":/w node:20 npm ci'),
    ("host-install", "silent", "docker exec web pip install x"),
    ("host-install", "silent", "docker compose run --rm web npm install"),
    ("host-install", "silent", "kubectl exec web-0 -- npm install"),
    ("host-install", "silent", "podman run --rm python:3.12 pip install x"),
    ("host-install", "silent", "ssh host 'npm install'"),
    ("host-install", "silent", "devcontainer exec npm install"),
    ("host-install", "silent", "docker run --rm alpine sh -c 'apk add curl'"),
    ("host-install", "silent", "sudo docker exec web sh -c 'npm install'"),
    ("host-install", "silent", "docker exec web bash <<< 'npm install'"),
    ("delete-and-deploy", "silent", "docker run --rm alpine ls"),
    ("delete-and-deploy", "silent", 'docker run --rm -v "$PWD":/w node:20 npm ci'),
    ("delete-and-deploy", "silent", "docker run --rm -it alpine sh"),
    ("delete-and-deploy", "silent", "docker exec web ls /data"),
    ("delete-and-deploy", "silent", "docker exec -it web bash"),
    ("delete-and-deploy", "silent", "docker compose -f x.yml up -d"),
    ("delete-and-deploy", "silent", "docker compose exec web ls"),
    ("delete-and-deploy", "silent",
     "uv run --offline --no-project --with pytest --python 3.13 python -m pytest -q -p no:cacheprovider -o addopts= "
     "tools/guard/tests"),
    ("delete-and-deploy", "silent", "uv run --offline ruff check tools"),
    ("delete-and-deploy", "silent", "poetry run pytest"),
    ("delete-and-deploy", "silent", "npm exec -- eslint ."),
    ("delete-and-deploy", "silent", "busybox ls"),
    ("delete-and-deploy", "silent", "direnv exec . make test"),
    ("delete-and-deploy", "silent", "conda run -n env python -m pytest"),
]


def _ev(guard, command):
    return guard.Event({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/work/repo",
                        "tool_input": {"command": command}})


@pytest.fixture
def on_main(guard, monkeypatch):
    monkeypatch.setattr(guard, "current_branch", lambda cwd: "main")


@pytest.mark.parametrize("rule,expected,command", ROWS, ids=[f"{r[0]}|{r[2][:60]}" for r in ROWS])
def test_runner_row(guard, on_main, rule, expected, command):
    rules = ["delete-guard", "deploy-ask"] if rule == "delete-and-deploy" else [rule]
    got = {r: guard.RULES[r](_ev(guard, command), dict(guard.DEFAULTS)) for r in rules}
    if expected == "silent":
        assert not any(got.values()), f"{command!r}: {got}"
    else:
        assert all(d and d[0] == expected for d in got.values()), f"{command!r}: {got}"


def _words(guard, command):
    (toks,) = guard.nested_commands(command)
    return [toks[i] for i in sorted(guard.command_word_indexes(toks))]


@pytest.mark.parametrize("command,words", [
    # `--rm` may take a value as far as the reader knows, so `web` may be it and `/d` may be the command
    ("docker --context x compose -f a.yml run --rm web rm -rf /d", ["docker", "rm", "/d"]),
    ("uv --quiet run rm -rf build", ["uv", "rm"]),
    ("mise exec node@20 -- rm -rf build", ["mise", "node@20", "rm"]),
    ("kubectl exec -it web-0 -c app -- rm -rf /d", ["kubectl", "app", "rm"]),
    ("podman-compose run web rm -rf /d", ["podman-compose", "rm"]),
    ("docker compose -f x.yml up -d", ["docker"]),
    ("uv lock --check", ["uv"]),
])
def test_runner_and_container_command_words(guard, command, words):
    assert _words(guard, command) == words


def test_the_local_reading_stops_at_every_container_tool(guard):
    for command in ("podman-compose exec web npm install", "nerdctl run --rm img npm ci", "oc exec pod -- npm ci"):
        assert guard.rule_host_install(_ev(guard, command), {}) is None, command
    assert guard.rule_host_install(_ev(guard, "uv run --offline npm install"), {})[0] == "ask"


def test_known_limit_a_value_less_option_may_hide_the_image(guard):
    # the reader cannot know that --rm takes no value: `echo` may be the image, so `rm` may be the command
    got = guard.rule_delete_guard(_ev(guard, "docker run --rm alpine echo rm -rf x"), {})
    assert got and got[0] == "ask"
