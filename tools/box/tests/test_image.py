"""The image's inputs: pins, firewall rules, marker. Offline; nothing here starts a container."""
import datetime as _dt
import json
import re

import pytest


def dockerfile_args(box_dir) -> set:
    text = (box_dir / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"^ARG\s+\w+=", text, re.M), "an ARG with a default hides a missing pin"
    return set(re.findall(r"^ARG\s+(\w+)\s*$", text, re.M))


def test_every_build_argument_is_pinned_and_every_pin_is_used(box, box_dir):
    pins = box.read_pins()
    args = dockerfile_args(box_dir) - {"TARGETARCH"}  # set by the builder
    assert args == set(pins), f"unpinned: {sorted(args - set(pins))}, unused: {sorted(set(pins) - args)}"


def test_bases_are_pinned_by_digest_and_tools_by_exact_version(box):
    pins = box.read_pins()
    for key in ("NODE_IMAGE", "UV_IMAGE"):
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", pins[key]), key
    for key in ("PYTHON_39", "PYTHON_313", "PYTEST_39", "PYTEST_313", "RUFF", "GH", "CLAUDE_CODE", "NODE_VERSION"):
        assert re.fullmatch(r"\d+\.\d+\.\d+", pins[key]), key
    for key in ("GH_SHA256_ARM64", "GH_SHA256_AMD64"):
        assert re.fullmatch(r"[0-9a-f]{64}", pins[key]), key
    for item in pins["APT_PINS"].split():
        assert re.fullmatch(r"[a-z0-9.+-]+=\S+", item), item
    assert {i.split("=")[0] for i in pins["APT_PINS"].split()} >= {"git", "iptables", "ipset", "curl"}


def test_the_cli_pin_is_the_verified_version(box, box_dir):
    verified = json.loads((box_dir.parent / "orchestration" / "verified.json").read_text(encoding="utf-8"))
    assert box.read_pins()["CLAUDE_CODE"] == verified["cli_version"]


@pytest.mark.parametrize("text, fragment", [
    ("A=1\nA=2\n", "pinned twice"),
    ("lower=1\n", "not KEY=VALUE"),
    ("A = 1\n", "not KEY=VALUE"),
    ("A=\n", "not KEY=VALUE"),
])
def test_read_pins_refuses_a_bad_file(box, tmp_path, text, fragment):
    path = tmp_path / "pins.env"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(box.BoxError, match=fragment):
        box.read_pins(str(path))


def test_the_image_starts_as_root_only_for_its_entrypoint(box_dir):
    text = (box_dir / "Dockerfile").read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/usr/local/sbin/box-entrypoint"]' in text
    assert "HEALTHCHECK" in text and text.count("FROM ") >= 3
    entry = (box_dir / "entrypoint.sh").read_text(encoding="utf-8")
    drop = entry.strip().splitlines()[-1]
    assert drop.startswith("exec setpriv --reuid=node --regid=node")
    for flag in ("--inh-caps=-all", "--bounding-set=-all", "--no-new-privs"):
        assert flag in drop
    # the firewall and the marker come first, and each failure stops the start
    assert entry.index("firewall.py") < entry.index("marker.py") < entry.index("exec setpriv")
    assert entry.count("exit 70") == 3


def test_the_placeholder_managed_settings_deny_every_call(box_dir):
    data = json.loads((box_dir / "managed-settings.json").read_text(encoding="utf-8"))
    assert data["allowManagedHooksOnly"] is True
    (entry,) = data["hooks"]["PreToolUse"]
    assert entry["matcher"] == "*" and entry["hooks"][0]["command"].endswith("exit 2")


# --- firewall ---

def test_the_committed_allowlist_starts_with_the_model_api(firewall, box_dir):
    hosts = firewall.read_allowlist(str(box_dir / "allowlist"))
    assert hosts[0] == "api.anthropic.com"
    assert "github.com" in hosts and len(hosts) == len(set(hosts))


@pytest.mark.parametrize("line", ["evil.com;rm", "-x", ".lead", "a b", "host/path", "$(id)"])
def test_read_allowlist_refuses_what_is_not_a_host_name(firewall, tmp_path, line):
    path = tmp_path / "allowlist"
    path.write_text(f"ok.example\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a host name"):
        firewall.read_allowlist(str(path))


def test_read_allowlist_refuses_an_empty_list(firewall, tmp_path):
    path = tmp_path / "allowlist"
    path.write_text("# nothing\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="names no host"):
        firewall.read_allowlist(str(path))


def test_github_ranges_keep_ipv4_of_web_api_git_only(firewall):
    meta = {"web": ["140.82.112.0/20", "2a0a:a440::/29"], "api": ["192.30.252.0/22"], "git": ["140.82.112.0/20"],
            "actions": ["4.0.0.0/8"], "hooks": ["1.2.3.0/24"]}
    assert firewall.github_ranges(meta) == {"140.82.112.0/20", "192.30.252.0/22"}


def test_rules_allow_443_to_the_set_only_and_end_closed(firewall):
    cmds = [" ".join(c) for c in firewall.rules(["1.2.3.4/32", "5.6.7.0/24"])]
    assert "ipset add box-allow 1.2.3.4/32 -exist" in cmds and "ipset add box-allow 5.6.7.0/24 -exist" in cmds
    allow = next(i for i, c in enumerate(cmds) if "--dport 443" in c)
    reject = next(i for i, c in enumerate(cmds) if "-j REJECT" in c)
    assert "--match-set box-allow dst" in cmds[allow] and allow < reject
    assert cmds[-3:] == ["iptables -P INPUT DROP", "iptables -P FORWARD DROP", "iptables -P OUTPUT DROP"]
    accepts = [c for c in cmds if c.startswith("iptables -A OUTPUT") and c.endswith("-j ACCEPT")]
    # loopback, open connections, DNS twice, 443 to the set: nothing else leaves the box
    assert len(accepts) == 5 and all(("-o lo" in c or "ESTABLISHED" in c or "--dport 53" in c
                                      or "--match-set" in c) for c in accepts)


def test_ipv6_is_closed_entirely(firewall):
    cmds = [" ".join(c) for c in firewall.ipv6_rules()]
    assert "ip6tables -P OUTPUT DROP" in cmds and not any("--dport" in c for c in cmds)


def test_firewall_main_fails_closed_on_an_unresolvable_name(firewall, tmp_path, monkeypatch):
    path = tmp_path / "allowlist"
    path.write_text("does-not-resolve.invalid\n", encoding="utf-8")
    monkeypatch.setattr(firewall, "resolve", lambda host: set())
    ran = []
    monkeypatch.setattr(firewall, "run", ran.append)
    assert firewall.main(["--allowlist", str(path)]) == 1
    assert ran == []  # no rule is set from a partial list


# --- marker ---

ENV = {"BOX_NAME": "build-1", "BOX_SEAT": "seat-1", "BOX_IMAGE": "0123abc", "BOX_JUDGE": "8be59e6"}


def test_marker_records_the_fields_and_the_time(marker):
    now = _dt.datetime(2026, 11, 20, 9, 30, tzinfo=_dt.timezone.utc)
    data = marker.marker(ENV, now)
    assert data == {"schema": "agent-box/1", "name": "build-1", "seat": "seat-1", "image": "0123abc",
                    "judge": "8be59e6", "boundary": "own", "firewall": "set", "started": "2026-11-20T09:30:00Z"}


@pytest.mark.parametrize("key, value", [("BOX_NAME", ""), ("BOX_SEAT", 'a"b'), ("BOX_IMAGE", "x\ny"),
                                        ("BOX_JUDGE", "-flag"), ("BOX_NAME", "a" * 200), ("BOX_SEAT", "a b")])
def test_marker_refuses_a_value_that_is_not_a_plain_token(marker, key, value):
    with pytest.raises(ValueError, match=key):
        marker.marker({**ENV, key: value}, _dt.datetime.now(_dt.timezone.utc))


def test_marker_main_refuses_without_root(marker, tmp_path, monkeypatch):
    monkeypatch.setattr(marker.os, "geteuid", lambda: 1000)
    path = tmp_path / "box.json"
    assert marker.main(["--path", str(path)]) == 1
    assert not path.exists()
