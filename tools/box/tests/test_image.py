"""The image's inputs: pins, firewall rules, marker. Offline; nothing here starts a container."""
import datetime as _dt
import http.client
import http.server
import io
import json
import re
import threading
import urllib.error
import urllib.request

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
    cmds = [" ".join(c) for c in firewall.rules(["1.2.3.4/32", "5.6.7.0/24"], ["0.250.250.200"])]
    assert "ipset add box-allow 1.2.3.4/32 -exist" in cmds and "ipset add box-allow 5.6.7.0/24 -exist" in cmds
    allow = next(i for i, c in enumerate(cmds) if "--dport 443" in c)
    reject = next(i for i, c in enumerate(cmds) if "-j REJECT" in c)
    assert "--match-set box-allow dst" in cmds[allow] and allow < reject
    assert cmds[-3:] == ["iptables -P INPUT DROP", "iptables -P FORWARD DROP", "iptables -P OUTPUT DROP"]
    accepts = [c for c in cmds if c.startswith("iptables -A OUTPUT") and c.endswith("-j ACCEPT")]
    # loopback, open connections, DNS twice to the resolver, 443 to the set: nothing else leaves the box
    assert len(accepts) == 5 and all(("-o lo" in c or "ESTABLISHED" in c or "--match-set" in c
                                      or ("--dport 53" in c and "-d 0.250.250.200/32" in c)) for c in accepts)
    assert not [c for c in cmds if "--dport 53" in c and " -d " not in c], "port 53 must name its address"


def test_nameservers_keep_ipv4_in_order(firewall):
    text = ("# comment\nnameserver 0.250.250.200\nnameserver ::1\nnameserver 10.0.0.2\nnameserver bad\n"
            "nameserver 0.250.250.200\nsearch x\n")
    assert firewall.nameservers(text) == ["0.250.250.200", "10.0.0.2"]
    assert firewall.nameservers("search x\n") == []


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


# --- firewall: the box's GitHub token on the fetch of GitHub's ranges (#83) ---

TOKEN = "tok_" + "a1b2" * 10  # the form of a plain token, not a real token's prefix
RESET = 1795289760  # 2026-11-21T19:36:00Z


def refused(code: int, headers: dict) -> urllib.error.HTTPError:
    hdrs = http.client.HTTPMessage()
    for key, value in headers.items():
        hdrs[key] = value
    return urllib.error.HTTPError("https://api.github.com/meta", code, "refused", hdrs, io.BytesIO(b"{}"))


def start(firewall, tmp_path, monkeypatch, opener, token=None):
    """firewall.main with the network faked: one name that resolves, the given urlopen, the rules recorded."""
    allow = tmp_path / "allowlist"
    allow.write_text("api.anthropic.com\n", encoding="utf-8")
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 10.0.0.2\n", encoding="utf-8")
    if token is None:
        monkeypatch.delenv("GH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GH_TOKEN", token)
    monkeypatch.setattr(firewall, "resolve", lambda host: {"1.2.3.4"})
    monkeypatch.setattr(firewall, "has_ipv6", lambda: False)
    monkeypatch.setattr(firewall, "reachable", lambda host, port, timeout=5.0: host != firewall.OFF_LIST_PROBE[0])
    monkeypatch.setattr(firewall.urllib.request, "urlopen", opener)
    ran = []
    monkeypatch.setattr(firewall, "run", ran.append)
    return firewall.main(["--allowlist", str(allow), "--resolv-conf", str(resolv)]), ran


def meta_opener(sent: list):
    def opener(req, timeout=None):
        sent.append(req)
        return io.BytesIO(json.dumps({"web": ["140.82.112.0/20"], "api": [], "git": []}).encode())
    return opener


def test_the_token_goes_in_a_header_that_no_redirect_carries(firewall):
    req = firewall.meta_request(TOKEN)
    assert req.full_url == "https://api.github.com/meta"
    assert req.unredirected_hdrs == {"Authorization": f"Bearer {TOKEN}"}
    assert req.headers == {}


def test_without_a_token_the_request_has_no_header(firewall):
    assert firewall.meta_request("").header_items() == []


def test_a_redirect_does_not_carry_the_token_to_its_target(firewall, monkeypatch):
    seen = {}

    class Quiet(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

    class Target(Quiet):
        def do_GET(self):
            seen["target"] = self.headers.get("Authorization")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

    servers = [http.server.HTTPServer(("127.0.0.1", 0), Target)]

    class Redirect(Quiet):
        def do_GET(self):
            seen["first"] = self.headers.get("Authorization")
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{servers[0].server_port}/meta")
            self.end_headers()

    servers.append(http.server.HTTPServer(("127.0.0.1", 0), Redirect))
    for srv in servers:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(firewall, "GITHUB_META", f"http://127.0.0.1:{servers[1].server_port}/meta")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # no proxy from the environment
        with opener.open(firewall.meta_request(TOKEN), timeout=10) as resp:
            assert resp.status == 200
    finally:
        for srv in servers:
            srv.shutdown()
            srv.server_close()
    assert seen == {"first": f"Bearer {TOKEN}", "target": None}


def test_main_sends_the_token_and_never_prints_it(firewall, tmp_path, monkeypatch, capsys):
    sent = []
    code, ran = start(firewall, tmp_path, monkeypatch, meta_opener(sent), TOKEN)
    err = capsys.readouterr().err
    assert code == 0 and ran
    assert [req.unredirected_hdrs.get("Authorization") for req in sent] == [f"Bearer {TOKEN}"]
    assert "with the box's GitHub token" in err and TOKEN not in err


@pytest.mark.parametrize("token", [None, ""])
def test_main_without_a_token_fetches_as_before(firewall, tmp_path, monkeypatch, capsys, token):
    sent = []
    code, ran = start(firewall, tmp_path, monkeypatch, meta_opener(sent), token)
    assert code == 0 and ran
    assert [req.header_items() for req in sent] == [[]]
    assert "without a token" in capsys.readouterr().err


@pytest.mark.parametrize("token", ["secret_part\nX-Injected: 1", "secret_part\r", "secret_part value",
                                   "secret_part;x", " secret_part"])
def test_a_token_that_is_not_plain_stops_the_start_without_its_text(firewall, tmp_path, monkeypatch, capsys, token):
    sent = []
    code, ran = start(firewall, tmp_path, monkeypatch, meta_opener(sent), token)
    err = capsys.readouterr().err
    assert code == 1 and sent == [] and ran == []
    assert "GH_TOKEN" in err and "secret_part" not in err


@pytest.mark.parametrize("code", [403, 429])
def test_a_used_up_rate_limit_names_the_limit_and_its_reset(firewall, code):
    exc = refused(code, {"x-ratelimit-limit": "60", "x-ratelimit-remaining": "0", "x-ratelimit-reset": str(RESET)})
    msg = firewall.refusal(exc, False, RESET - 45 * 60)
    assert f"HTTP {code} from https://api.github.com/meta, without a token" in msg
    assert "rate limit used up: 0 of 60 calls left" in msg
    assert "resets at 2026-11-21T19:36:00Z (in 45 min)" in msg


def test_a_refusal_with_calls_left_says_the_limit_is_not_the_cause(firewall):
    exc = refused(403, {"x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4990", "x-ratelimit-reset": str(RESET)})
    assert "rate limit not used up: 4990 of 5000 calls left" in firewall.refusal(exc, True, RESET)


def test_a_secondary_limit_names_its_retry_time(firewall):
    msg = firewall.refusal(refused(429, {"retry-after": "60"}), True, RESET)
    assert "with the box's GitHub token" in msg and "GitHub asks for a retry after 60 s" in msg


def test_a_refusal_without_rate_limit_headers_says_so(firewall):
    assert "the answer names no rate limit and no reset time" in firewall.refusal(refused(403, {}), False, RESET)


def test_header_values_that_are_not_numbers_are_not_printed(firewall):
    exc = refused(403, {"x-ratelimit-remaining": "\x1b[2J", "x-ratelimit-limit": "60", "x-ratelimit-reset": "soon",
                        "retry-after": "-1"})
    msg = firewall.refusal(exc, False, RESET)
    assert "\x1b" not in msg and "soon" not in msg and "-1" not in msg
    assert "the answer names no rate limit and no reset time" in msg


def test_other_refusals_name_the_code_and_the_token_only(firewall):
    msg = firewall.refusal(refused(401, {"x-ratelimit-remaining": "0"}), True, RESET)
    assert msg == ("GitHub refused the fetch of its ranges: HTTP 401 from https://api.github.com/meta, "
                   "with the box's GitHub token")


def test_main_stops_on_a_rate_limit_with_the_message_and_no_token_text(firewall, tmp_path, monkeypatch, capsys):
    def opener(req, timeout=None):
        raise refused(403, {"x-ratelimit-limit": "60", "x-ratelimit-remaining": "0", "x-ratelimit-reset": str(RESET)})
    code, ran = start(firewall, tmp_path, monkeypatch, opener, TOKEN)
    err = capsys.readouterr().err
    assert code == 1 and ran == []
    assert "rate limit used up" in err and "resets at 2026-11-21T19:36:00Z" in err
    assert "HTTP Error 403" not in err and TOKEN not in err


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


# --- doctor ---

def test_doctor_wants_the_pinned_versions(box, box_dir):
    import importlib.util
    spec = importlib.util.spec_from_file_location("box_doctor", box_dir / "doctor.py")
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    pins = doctor.read_pins(str(box_dir / "pins.env"))
    assert pins == box.read_pins()
    wanted = doctor.wanted_versions(pins)
    assert set(wanted) == set(doctor.VERSION_ARGV)
    assert wanted["git"] == "2.47.3" and wanted["claude"] == pins["CLAUDE_CODE"]
    assert doctor.first_version("gh version 2.92.0 (2026-04-28)") == "2.92.0"
    assert doctor.first_version("v24.22.3") == "24.22.3"
    assert doctor.first_version("No module named pytest").startswith("<none")
