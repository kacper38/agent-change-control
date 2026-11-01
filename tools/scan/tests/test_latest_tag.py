"""latest-tag scanner: floating image references in Dockerfiles, compose files and workflows (plan step 3.7)."""
import importlib.util
import io
import json
import pathlib
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def lt():
    spec = importlib.util.spec_from_file_location("latest_tag", HERE.parent / "latest_tag.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("ref,expected", [
    ("nginx", "none"), ("nginx:latest", "latest"), ("nginx:1.27", "tag"), ("localhost:5000/app", "none"),
    ("localhost:5000/app:1.0", "tag"), ("ghcr.io/o/r@sha256:abc", "digest"), ("nginx:latest@sha256:abc", "digest"),
    ("python:${PY}-slim", "tag"),
])
def test_tag_of(lt, ref, expected):
    assert lt.tag_of(ref) == expected


@pytest.mark.parametrize("path,kind", [
    ("Dockerfile", "dockerfile"), ("svc/Dockerfile.prod", "dockerfile"), ("api.Dockerfile", "dockerfile"),
    ("x/build.dockerfile", "dockerfile"), ("Containerfile", "dockerfile"), ("compose.yml", "yaml"),
    ("deploy/docker-compose.override.yaml", "yaml"), (".github/workflows/ci.yml", "yaml"),
    ("repo/.github/workflows/x.yaml", "yaml"), ("k8s/deploy.yaml", None), ("README.md", None),
    ("Dockerfile.md", "dockerfile"), ("tools/guard/tests/fixtures/x.json", None),
])
def test_kind_of(lt, path, kind):
    assert lt.kind_of(path) == kind


DOCKERFILE = """\
# syntax=docker/dockerfile:1
ARG BASE=python:3.12-slim
FROM --platform=$BUILDPLATFORM python:3.12-slim AS builder
FROM ${BASE} AS deps
FROM builder
FROM scratch
from nginx:latest
FROM python
FROM ghcr.io/o/app:1.2.3@sha256:0123
FROM Builder AS again
FROM nginx AS nginx
FROM nginx
"""


def test_scan_dockerfile(lt):
    found = lt.scan_text(DOCKERFILE, "dockerfile")
    assert [(n, r) for n, r, _ in found] == [(7, ":latest tag"), (8, "no tag (floats to :latest)"),
                                             (11, "no tag (floats to :latest)")]
    assert found[0][2] == "from nginx:latest"
    assert found[2][2] == "FROM nginx AS nginx", "aliasing an image to its own name does not make it a stage"


COMPOSE = """\
services:
  web:
    image: nginx:latest
  db:
    image: "postgres"
  app:
    image: ${REGISTRY}/app:${TAG}
  cache:
    image: redis:7.4 # pinned
  queue:
    image: 'rabbitmq:3.13@sha256:abc'
  tool:
    image: {{ .Values.image }}
"""
WORKFLOW = """\
jobs:
  test:
    runs-on: ubuntu-latest
    container:
      image: node:22
    services:
      pg:
        image: postgres
    steps:
      - uses: actions/checkout@v6
      - uses: docker://alpine
      - uses: "docker://ghcr.io/o/tool:1.0"
  short:
    container: ubuntu
  pinned:
    container: ubuntu:24.04
"""


def test_scan_yaml(lt):
    assert [(n, r) for n, r, _ in lt.scan_text(COMPOSE, "yaml")] == [(3, ":latest tag"),
                                                                     (5, "no tag (floats to :latest)")]
    assert [(n, r) for n, r, _ in lt.scan_text(WORKFLOW, "yaml")] == [(8, "no tag (floats to :latest)"),
                                                                      (11, "no tag (floats to :latest)"),
                                                                      (14, "no tag (floats to :latest)")]


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "Dockerfile").write_text(DOCKERFILE)
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "compose.yml").write_text(COMPOSE)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW)
    # not one of the kinds: scanned only when named
    (tmp_path / "k8s.yaml").write_text("spec:\n  containers:\n    - image: busybox\n")
    git(tmp_path, "add", ".")
    return tmp_path


def run(lt, argv, cwd):
    out, err = io.StringIO(), io.StringIO()
    code = lt.main(argv, out=out, err=err, stdin=io.StringIO("")) if cwd is None else None
    if cwd is not None:
        r = subprocess.run([__import__("sys").executable, str(HERE.parent / "latest_tag.py"), *argv], cwd=cwd,
                           capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr
    return code, out.getvalue(), err.getvalue()


def test_scan_repo_default_tree_and_named_paths(lt, repo):
    code, out, err = run(lt, ["scan"], repo)
    assert code == 1
    lines = out.splitlines()
    assert "Dockerfile:7: :latest tag: from nginx:latest" in lines
    assert "deploy/compose.yml:5: no tag (floats to :latest): image: \"postgres\"" in lines
    assert ".github/workflows/ci.yml:11: no tag (floats to :latest): - uses: docker://alpine" in lines
    assert not any(ln.startswith("k8s.yaml") for ln in lines)
    assert len(lines) == 8 and "8 finding(s) in 3 file(s)" in err
    code, out, err = run(lt, ["scan", "typo.yml", "deploy"], repo)
    assert code == 2 and out == "" and "cannot read typo.yml" in err, "a missing named path is not a green scan"
    code, out, err = run(lt, ["scan", "k8s.yaml"], repo)  # a named file is read whatever its name
    assert code == 1 and out.splitlines() == ["k8s.yaml:3: no tag (floats to :latest): - image: busybox"]
    code, out, _ = run(lt, ["scan", "deploy"], repo)
    assert code == 1 and all(ln.startswith("deploy/compose.yml") for ln in out.splitlines())


def test_scan_clean_tree_and_no_repo(lt, tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim@sha256:abc AS b\nFROM b\n")
    git(tmp_path, "add", ".")
    code, out, err = run(lt, ["scan"], tmp_path)
    assert (code, out) == (0, "") and "0 finding(s) in 1 file(s)" in err
    plain = tmp_path / "plain"
    plain.mkdir()
    code, out, err = run(lt, ["scan"], plain)
    assert code == 2 and "nothing to scan" in err
    assert run(lt, ["help"], plain)[0] == 0 and run(lt, ["bogus"], plain)[0] == 1


def hook(lt, payload):
    out = io.StringIO()
    code = lt.main(["hook"], stdin=io.StringIO(payload if isinstance(payload, str) else json.dumps(payload)), out=out)
    return code, out.getvalue()


def test_hook_feedback_in_both_shapes(lt, tmp_path):
    df = tmp_path / "Dockerfile"
    df.write_text("FROM nginx:latest\n")
    code, out = hook(lt, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Write",
                          "tool_input": {"file_path": str(df), "content": "FROM nginx:latest\n"}})
    data = json.loads(out)
    assert code == 0 and data["decision"] == "block"
    assert "Dockerfile:1: :latest tag: FROM nginx:latest" in data["reason"] and "How:" in data["reason"]
    cf = tmp_path / "compose.yaml"
    cf.write_text("services:\n  web:\n    image: nginx:latest\n")
    code, out = hook(lt, {"hook_event_name": "PostToolUse", "timestamp": "2026-10-29T10:00:00.000Z",
                          "tool_name": "create", "tool_input": {"path": str(cf), "file_text": "x"}})
    data = json.loads(out)
    assert code == 0 and set(data) == {"additionalContext"} and "image: nginx:latest" in data["additionalContext"]
    cli = {"hookEventName": "postToolUse", "sessionId": "c2", "timestamp": 1761732000000, "toolName": "create",
           "toolArgs": json.dumps({"path": str(df), "file_text": "x"})}  # Copilot CLI: toolArgs JSON-encoded
    code, out = hook(lt, cli)
    assert code == 0 and "FROM nginx:latest" in json.loads(out)["additionalContext"]


def test_hook_is_silent_when_nothing_applies(lt, tmp_path):
    df = tmp_path / "Dockerfile"
    df.write_text("FROM python:3.12-slim\n")
    assert hook(lt, {"tool_name": "Write", "tool_input": {"file_path": str(df)}}) == (0, "")
    md = tmp_path / "notes.md"
    md.write_text("image: nginx:latest\n")
    assert hook(lt, {"tool_name": "Write", "tool_input": {"file_path": str(md)}}) == (0, "")
    missing = str(tmp_path / "missing" / "Dockerfile")
    assert hook(lt, {"tool_name": "Write", "tool_input": {"file_path": missing}}) == (0, "")
    assert hook(lt, {"tool_name": "Bash", "tool_input": {"command": "cat Dockerfile"}}) == (0, "")
    assert hook(lt, "{{{") == (0, "") and hook(lt, "[1]") == (0, "")
    assert hook(lt, {"toolName": "create", "toolArgs": "not json", "timestamp": 1}) == (0, "")


@pytest.mark.parametrize("path,kind", [
    ("azure-pipelines.yml", "pipelines"), ("ci/azure-pipelines-label-lint.yml", "pipelines"),
    ("x/azure-pipelines.yaml", "pipelines"), ("pipelines/build.yml", None), ("azure-pipelines.md", None),
])
def test_kind_of_azure_pipelines(lt, path, kind):
    assert lt.kind_of(path) == kind


PIPELINES = """\
trigger: [main]
resources:
  containers:
  - container: linux
    image: ubuntu:24.04
  - container: tools
    image: ghcr.io/o/tools
  - image: python:latest
    container: py
pool:
  vmImage: ubuntu-latest
jobs:
- job: a
  container: linux
  services:
    cache: redis
  steps:
  - script: echo hi
    target:
      container: tools
- job: b
  container: node
- job: c
  container:
    image: mcr.microsoft.com/dotnet/sdk
- job: d
  container: ubuntu:24.04
- job: e
  container: $(image)
"""
PIPELINE_FINDINGS = [(7, "no tag (floats to :latest)"), (8, ":latest tag"), (22, "no tag (floats to :latest)"),
                     (25, "no tag (floats to :latest)")]


def test_scan_pipelines_judges_images_not_aliases(lt):
    found = lt.scan_text(PIPELINES, "pipelines")
    assert [(n, r) for n, r, _ in found] == PIPELINE_FINDINGS
    assert found[2][2] == "container: node", "a job container that names no resources.containers alias is an image"
    assert [n for n, _, _ in lt.scan_text(PIPELINES, "yaml")][:1] == [4], "the generic reader takes aliases for images"


def test_scan_pipelines_in_tree_by_name_and_hook(lt, tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "ci").mkdir()
    pipeline = tmp_path / "ci" / "azure-pipelines.yml"
    pipeline.write_text(PIPELINES)
    git(tmp_path, "add", ".")
    expected = [f"ci/azure-pipelines.yml:{n}: {r}" for n, r in PIPELINE_FINDINGS]
    for argv in (["scan"], ["scan", "ci/azure-pipelines.yml"], ["scan", "ci"]):
        code, out, err = run(lt, argv, tmp_path)
        assert code == 1 and [": ".join(ln.split(": ")[:2]) for ln in out.splitlines()] == expected, argv
        assert "4 finding(s) in 1 file(s)" in err
    code, out = hook(lt, {"tool_name": "Write", "tool_input": {"file_path": str(pipeline)}})
    assert code == 0 and "azure-pipelines.yml:8: :latest tag: - image: python:latest" in json.loads(out)["reason"]
