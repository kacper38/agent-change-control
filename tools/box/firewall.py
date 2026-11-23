#!/usr/bin/env python3
"""firewall — the box's egress list (plan step 1.0a), set by the entrypoint as root before anything else runs.

  python3 firewall.py [--allowlist FILE]

The method is the vendor's dev-container firewall (iptables with an ipset, default drop, addresses resolved at
start), written anew for two reasons: the box allows only the model API and GitHub, where the vendor's list also
allows npm, error reporting, feature flags and an editor marketplace; and a copy would bring the vendor's
licence terms into this repository, which were not checked. Rules, in order: loopback; replies to connections
already open; port 53 to the nameservers of /etc/resolv.conf only (a named skeleton gap: names resolve freely,
so a lookup can still carry data out through that resolver); TCP 443 to the allowed set; everything
else is rejected, so a refused call fails at once instead of hanging. IPv6 is closed entirely when the kernel
has it. GitHub's ranges are read from its API before the rules go in; when GH_TOKEN is set (bin/box sets it from
the Keychain entry agent-box-github), that one request carries it, so box starts do not share the unauthenticated
limit of 60 calls an hour; the doctor starts without it. After the rules are in, the script checks itself: a host
off the list must be unreachable and the first host on the list reachable; any failure exits non-zero, and the
entrypoint then starts no session.

Standard library only. Exit codes: 0 rules set and checked, 1 a rule or the self-check failed, 2 usage error.
"""
import argparse
import datetime as _dt
import ipaddress
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
SET = "box-allow"
GITHUB_META = "https://api.github.com/meta"
GITHUB_META_KEYS = ("web", "api", "git")
GITHUB_TOKEN_ENV = "GH_TOKEN"  # set by bin/box from the Keychain entry agent-box-github; absent for the doctor
PLAIN_TOKEN = re.compile(r"[A-Za-z0-9_]{1,255}")
OFF_LIST_PROBE = ("example.com", 443)  # must fail once the rules are in


def read_allowlist(path: str) -> list:
    """Host names, one per line; `#` starts a comment. A name with anything but letters, digits, dots and dashes
    is refused: the names come from a committed file, and a typo must fail the start, not widen the list."""
    hosts = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if not all(c.isalnum() or c in ".-" for c in line) or line.startswith(("-", ".")):
                raise ValueError(f"not a host name in {path}: {line!r}")
            hosts.append(line.lower())
    if not hosts:
        raise ValueError(f"{path} names no host")
    return hosts


def resolve(host: str) -> set:
    """IPv4 addresses of host now; an empty set when it does not resolve."""
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        return set()
    return {info[4][0] for info in infos}


def meta_request(token: str) -> urllib.request.Request:
    """The request for GitHub's ranges. Unauthenticated, a box start shares GitHub's limit of 60 calls an hour
    with every other start from the same address; with the box's token it draws on that token's own limit. The
    token goes in a header urllib does not carry across a redirect, so it reaches this address and no other host.
    A token that is not a plain token is refused here, before http.client would put its text into an error."""
    req = urllib.request.Request(GITHUB_META)
    if token:
        if not PLAIN_TOKEN.fullmatch(token):
            raise ValueError(f"{GITHUB_TOKEN_ENV} is set but is not a plain token (letters, digits, underscores); "
                             f"its text is not shown")
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def token_words(with_token: bool) -> str:
    return "with the box's GitHub token" if with_token else "without a token"


def refusal(exc: urllib.error.HTTPError, with_token: bool, now: float) -> str:
    """What a refused fetch of the ranges says: the code, whether the token went with it, and for 403 and 429 the
    rate limit and its reset as GitHub's headers give them. Only header values made of digits are shown."""
    msg = f"GitHub refused the fetch of its ranges: HTTP {exc.code} from {GITHUB_META}, {token_words(with_token)}"
    if exc.code not in (403, 429):
        return msg
    hdrs = exc.headers

    def number(name: str):
        value = (hdrs.get(name) if hdrs is not None else None) or ""
        return int(value) if value.isascii() and value.isdigit() else None

    left, limit, reset, retry = (number(n) for n in ("x-ratelimit-remaining", "x-ratelimit-limit",
                                                       "x-ratelimit-reset", "retry-after"))
    parts = []
    if left is not None and limit is not None:
        parts.append(f"rate limit {'used up' if left == 0 else 'not used up'}: {left} of {limit} calls left")
    if reset is not None:
        at = _dt.datetime.fromtimestamp(reset, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts.append(f"it resets at {at} (in {max(0, math.ceil((reset - now) / 60))} min)")
    if retry is not None:
        parts.append(f"GitHub asks for a retry after {retry} s")
    return msg + "; " + ("; ".join(parts) if parts else "the answer names no rate limit and no reset time")


def github_ranges(meta: dict) -> set:
    """The IPv4 ranges GitHub publishes for its web, API and git front ends."""
    out = set()
    for key in GITHUB_META_KEYS:
        for cidr in meta.get(key) or ():
            net = ipaddress.ip_network(cidr, strict=False)
            if net.version == 4:
                out.add(str(net))
    return out


def nameservers(text: str) -> list:
    """The IPv4 nameservers of a resolv.conf, in order. Port 53 is open to these alone, so DNS is the only thing
    that leaves on it; one on loopback (Docker's embedded resolver) is covered by the loopback rule."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            try:
                addr = ipaddress.ip_address(parts[1])
            except ValueError:
                continue
            if addr.version == 4 and str(addr) not in out:
                out.append(str(addr))
    return out


def rules(nets: list, resolvers: list) -> list:
    """The commands that set the egress list, in order, as argv lists. Pure, so the tests read it."""
    cmds = [["ipset", "create", SET, "hash:net", "-exist"], ["ipset", "flush", SET]]
    cmds += [["ipset", "add", SET, net, "-exist"] for net in sorted(nets)]
    for chain in ("INPUT", "OUTPUT", "FORWARD"):
        cmds.append(["iptables", "-F", chain])
    cmds += [
        ["iptables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT"],
        ["iptables", "-A", "OUTPUT", "-o", "lo", "-j", "ACCEPT"],
        ["iptables", "-A", "INPUT", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
        ["iptables", "-A", "OUTPUT", "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
    ]
    for ns in resolvers:
        for proto in ("udp", "tcp"):
            cmds.append(["iptables", "-A", "OUTPUT", "-p", proto, "-d", f"{ns}/32", "--dport", "53", "-j", "ACCEPT"])
    cmds += [
        ["iptables", "-A", "OUTPUT", "-p", "tcp", "--dport", "443", "-m", "set", "--match-set", SET, "dst",
         "-j", "ACCEPT"],
        ["iptables", "-A", "OUTPUT", "-j", "REJECT", "--reject-with", "icmp-admin-prohibited"],
        ["iptables", "-P", "INPUT", "DROP"],
        ["iptables", "-P", "FORWARD", "DROP"],
        ["iptables", "-P", "OUTPUT", "DROP"],
    ]
    return cmds


def ipv6_rules() -> list:
    return [["ip6tables", "-F", "OUTPUT"], ["ip6tables", "-A", "OUTPUT", "-o", "lo", "-j", "ACCEPT"],
            ["ip6tables", "-P", "INPUT", "DROP"], ["ip6tables", "-P", "FORWARD", "DROP"],
            ["ip6tables", "-P", "OUTPUT", "DROP"]]


def has_ipv6() -> bool:
    try:
        with open("/proc/net/if_inet6", encoding="ascii") as fh:
            return bool(fh.read().strip())
    except OSError:
        return False


def reachable(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(cmd: list) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: exit {r.returncode}: {r.stderr.strip()[:300]}")


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="firewall")
    ap.add_argument("--allowlist", default=os.path.join(HERE, "allowlist"))
    ap.add_argument("--resolv-conf", default="/etc/resolv.conf")
    ns = ap.parse_args(argv)
    try:
        hosts = read_allowlist(ns.allowlist)
        nets = set()
        for host in hosts:
            found = resolve(host)
            if not found:
                raise RuntimeError(f"{host} does not resolve")
            nets |= {f"{ip}/32" for ip in found}
        token = os.environ.get(GITHUB_TOKEN_ENV, "")
        try:
            with urllib.request.urlopen(meta_request(token), timeout=15) as resp:  # read before the list is closed
                nets |= github_ranges(json.load(resp))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(refusal(exc, bool(token), time.time())) from exc
        with open(ns.resolv_conf, encoding="utf-8") as fh:
            resolvers = nameservers(fh.read())
        if not resolvers:
            raise RuntimeError(f"{ns.resolv_conf} names no IPv4 nameserver")
        for cmd in rules(sorted(nets), resolvers) + (ipv6_rules() if has_ipv6() else []):
            run(cmd)
        if reachable(*OFF_LIST_PROBE):
            raise RuntimeError(f"self-check: {OFF_LIST_PROBE[0]} is still reachable")
        if not reachable(hosts[0], 443, timeout=10):
            raise RuntimeError(f"self-check: {hosts[0]} is not reachable")
    except (OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write(f"firewall: {exc}\n")
        return 1
    sys.stderr.write(f"firewall: set, {len(nets)} allowed networks from {len(hosts)} names and GitHub's ranges "
                     f"(fetched {token_words(bool(token))})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
