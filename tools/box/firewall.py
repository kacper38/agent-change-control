#!/usr/bin/env python3
"""firewall — the box's egress list (plan step 1.0a), set by the entrypoint as root before anything else runs.

  python3 firewall.py [--allowlist FILE]

The method is the vendor's dev-container firewall (iptables with an ipset, default drop, addresses resolved at
start), written anew for two reasons: the box allows only the model API and GitHub, where the vendor's list also
allows npm, error reporting, feature flags and an editor marketplace; and a copy would bring the vendor's
licence terms into this repository, which were not checked. Rules, in order: loopback; replies to connections
already open; DNS to any address (a named skeleton gap: DNS stays open); TCP 443 to the allowed set; everything
else is rejected, so a refused call fails at once instead of hanging. IPv6 is closed entirely when the kernel
has it. After the rules are in, the script checks itself: a host off the list must be unreachable and the first
host on the list reachable; any failure exits non-zero, and the entrypoint then starts no session.

Standard library only. Exit codes: 0 rules set and checked, 1 a rule or the self-check failed, 2 usage error.
"""
import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
SET = "box-allow"
GITHUB_META = "https://api.github.com/meta"
GITHUB_META_KEYS = ("web", "api", "git")
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


def github_ranges(meta: dict) -> set:
    """The IPv4 ranges GitHub publishes for its web, API and git front ends."""
    out = set()
    for key in GITHUB_META_KEYS:
        for cidr in meta.get(key) or ():
            net = ipaddress.ip_network(cidr, strict=False)
            if net.version == 4:
                out.add(str(net))
    return out


def rules(nets: list) -> list:
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
        ["iptables", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-j", "ACCEPT"],
        ["iptables", "-A", "OUTPUT", "-p", "tcp", "--dport", "53", "-j", "ACCEPT"],
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
    ns = ap.parse_args(argv)
    try:
        hosts = read_allowlist(ns.allowlist)
        nets = set()
        for host in hosts:
            found = resolve(host)
            if not found:
                raise RuntimeError(f"{host} does not resolve")
            nets |= {f"{ip}/32" for ip in found}
        with urllib.request.urlopen(GITHUB_META, timeout=15) as resp:  # read before the list is closed
            nets |= github_ranges(json.load(resp))
        for cmd in rules(sorted(nets)) + (ipv6_rules() if has_ipv6() else []):
            run(cmd)
        if reachable(*OFF_LIST_PROBE):
            raise RuntimeError(f"self-check: {OFF_LIST_PROBE[0]} is still reachable")
        if not reachable(hosts[0], 443, timeout=10):
            raise RuntimeError(f"self-check: {hosts[0]} is not reachable")
    except (OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write(f"firewall: {exc}\n")
        return 1
    sys.stderr.write(f"firewall: set, {len(nets)} allowed networks from {len(hosts)} names and GitHub's ranges\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
