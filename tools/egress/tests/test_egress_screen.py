"""egress screen: held means listed and counted, never dropped; exit 3 when anything is held."""
import io
import os
import stat

import pytest

OWN = {"boundary": "own", "client_markers": [], "egress_allowed_targets": ["claude", "copilot"]}
CLIENT = {**OWN, "boundary": "client"}
PLANTED = "token = ghp_" + "A1" * 18 + "\n"


@pytest.fixture(autouse=True)
def _no_gitleaks(monkeypatch, egress):
    monkeypatch.setattr(egress.shutil, "which", lambda name: None)


@pytest.mark.parametrize("text,name", [
    (PLANTED, "github-token"),
    ("-----BEGIN " + "OPENSSH PRIVATE KEY-----\nabc", "private-key"),
    ("aws_access_key_id = AKIA" + "Q" * 16, "aws-key"),
    ("key: sk-ant-" + "a" * 24, "openai-anthropic-key"),
    ("eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "d0zjgNryP4J3jVmNHl0w5N", "jwt"),
    ("DefaultEndpointsProtocol=https;AccountKey=" + "B" * 44 + ";", "azure-account-key"),
    ("DATABASE_URL=postgres://" + "app:s3cr3t@" + "db.internal:5432/app", "connection-string"),
    ("api_key = '" + "Zx9kQ2" * 4 + "'", "assignment"),
])
def test_secret_patterns(egress, text, name):
    assert name in egress.secret_hits(text)


@pytest.mark.parametrize("text", [
    "API_KEY=${API_KEY}", "password: <redacted>", "token = $TOKEN", "the api key is stored in the vault",
    "git diff --stat", "AKIAI is a prefix mentioned in docs", "PRIVATE KEY material never enters the repo",
])
def test_clean_text(egress, text):
    assert egress.secret_hits(text) == []


ADO_PAT = "Ab3x" * 19 + "AZDO" + "Q7rT"  # synthetic, built at runtime: 84 chars, AZDO at [76:80]


def test_ado_pat_current_format_only(egress):
    assert len(ADO_PAT) == 84 and ADO_PAT[76:80] == "AZDO"
    assert egress.secret_hits(f"AZURE_DEVOPS_EXT_PAT={ADO_PAT}\n") == ["azure-devops-pat"]
    assert egress.secret_hits("https://u:" + ADO_PAT + "@dev.azure.com/o") == ["azure-devops-pat"]
    legacy = "abcdefghijklmnopqrstuvwxyz234567" + "abcdefghijklmnopqrst"  # 52-char base32: left out on purpose
    assert len(legacy) == 52 and egress.secret_hits(legacy) == []
    assert egress.secret_hits(ADO_PAT[:76] + "AZDX" + ADO_PAT[80:]) == []
    assert egress.secret_hits("x" + ADO_PAT) == [], "an 85-char run is not the token shape"


def test_planted_token_is_held_exit_3(egress, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    code = egress.main(["--target", "claude"], stdin=io.StringIO(PLANTED), stdout=out, stderr=err)
    assert code == 3 and out.getvalue().startswith("held:secret:github-token\tstdin") and "1 held" in err.getvalue()


def test_client_boundary_holds_other_vendors_only(egress, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KZ_BOUNDARY", "client")
    out, err = io.StringIO(), io.StringIO()
    code = egress.main(["--target", "gemini"], stdin=io.StringIO("plain text"), stdout=out, stderr=err)
    assert code == 3 and "held:boundary:client->gemini" in out.getvalue()
    out = io.StringIO()
    code = egress.main(["--target", "claude"], stdin=io.StringIO("plain text"), stdout=out, stderr=io.StringIO())
    assert code == 0 and out.getvalue() == "send\tstdin\n"


def test_markers_size_and_config_file(egress, tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "guard.json").write_text('{"client_markers": ["acme-?pharma", "\\\\.corp\\\\b"]}')
    monkeypatch.chdir(tmp_path)
    cfg = egress.load_config(str(tmp_path))
    assert egress.screen_text("see AcmePharma SOP-12", "claude", cfg) == ["client-marker:acme-?pharma"]
    assert egress.screen_text("host db.corp:5432", "claude", cfg) == ["client-marker:\\.corp\\b"]
    assert egress.screen_text("x" * 50, "claude", cfg, max_bytes=10) == ["size:50>10"]
    assert egress.screen_text("fine", "claude", cfg) == []


def test_pass_mode_is_all_or_nothing(egress, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    good, bad = tmp_path / "good.txt", tmp_path / "bad.txt"
    good.write_text("safe content\n")
    bad.write_text(PLANTED)
    out, err = io.StringIO(), io.StringIO()
    code = egress.main(["--target", "claude", "--pass", str(good), str(bad)], stdout=out, stderr=err)
    assert code == 3 and out.getvalue() == "", "a partially held batch emits nothing"
    assert "held:secret:github-token" in err.getvalue() and "1 sent, 1 held" in err.getvalue()
    out, err = io.StringIO(), io.StringIO()
    code = egress.main(["--target", "claude", "--pass", str(good)], stdout=out, stderr=err)
    assert code == 0 and out.getvalue() == "safe content\n" and "send\t" in err.getvalue()


def test_unreadable_file_is_held_not_dropped(egress, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = io.StringIO()
    code = egress.main(["--target", "claude", str(tmp_path / "missing.txt")], stdout=out, stderr=io.StringIO())
    assert code == 3 and out.getvalue().startswith("held:unreadable:FileNotFoundError")


def test_gitleaks_used_when_present(egress, tmp_path, monkeypatch):
    fake = tmp_path / "gitleaks"
    fake.write_text("#!/bin/sh\nexit 9\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(egress.shutil, "which", lambda name: str(fake))
    assert egress.screen_text("looks clean to my regexes", "claude", OWN) == ["secret:gitleaks"]
    fake.write_text("#!/bin/sh\nexit 0\n")
    assert egress.screen_text("looks clean to my regexes", "claude", OWN) == []
    fake.write_text("#!/bin/sh\nexit 1\n")
    assert egress.screen_text("tool error falls back to own patterns", "claude", OWN) == []
    assert os.path.exists(str(fake))


def test_malformed_config_holds_everything(egress, tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "guard.json").write_text("{not json")
    monkeypatch.chdir(tmp_path)
    cfg = egress.load_config(str(tmp_path))
    reasons = egress.screen_text("plain", "claude", cfg)
    assert any(r.startswith("config:") and "JSONDecodeError" in r for r in reasons)
    assert "boundary:client->claude" not in reasons, "claude is an allowed target; the config error alone holds"
    assert "boundary:client->gemini" in egress.screen_text("plain", "gemini", cfg)


def test_env_boundary_only_tightens(egress, tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "guard.json").write_text('{"boundary": "client"}')
    monkeypatch.setenv("KZ_BOUNDARY", "own")
    assert egress.load_config(str(tmp_path))["boundary"] == "client"
    (tmp_path / ".claude" / "guard.json").write_text('{"boundary": "own"}')
    monkeypatch.setenv("KZ_BOUNDARY", "client")
    assert egress.load_config(str(tmp_path))["boundary"] == "client"
    monkeypatch.delenv("KZ_BOUNDARY")
    assert egress.load_config(str(tmp_path))["boundary"] == "own"


@pytest.mark.parametrize("text", ['["client"]', '{"boundary": 1}', '{"egress_allowed_targets": "copilot"}',
                                  '{"client_markers": "acme"}', '{"client_markers": [1]}'])
def test_wrong_shape_config_is_a_config_error(egress, tmp_path, text):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "guard.json").write_text(text)
    cfg = egress.load_config(str(tmp_path))
    assert cfg["config_error"] and cfg["boundary"] == "client"
    assert any(r.startswith("config:") for r in egress.screen_text("plain", "claude", cfg))

