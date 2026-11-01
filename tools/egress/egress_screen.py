#!/usr/bin/env python3
"""egress_screen — the last check before material leaves the machine (plan step 3.2).

Standard library only. Items are files or stdin. Each item is `send` or `held:<reason>`:
secret patterns (the fleet gate's set plus a few), gitleaks when installed, client markers
from `.claude/guard.json`, a size cap, and the client boundary (`KZ_BOUNDARY=client` or
`boundary` in guard.json holds everything whose target is not an agreed endpoint).
Held items are listed and counted, never dropped silently; exit 3 when anything is held.

  egress_screen.py --target claude [--pass] [--max-bytes N] [FILE ...]
With --pass the content of the items is written to stdout only when nothing is held
(all or nothing), and the report goes to stderr. Without --pass the report is stdout.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Optional

DEFAULT_MAX_BYTES = 200_000
DEFAULT_ALLOWED_TARGETS = ["claude", "copilot"]
SECRET_RES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}")),
    # current format: 84 chars, `AZDO` at [76:80]; the legacy 52-char base32 PAT is left out (false positives)
    ("azure-devops-pat", re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{76}AZDO[A-Za-z0-9_-]{4}(?![A-Za-z0-9_-])")),
    # a PAT travels base64-encoded in a Basic header (`:PAT` -> 116 chars); any long Basic credential is held
    ("basic-auth-header", re.compile(r"(?i)\bbasic\s+[A-Za-z0-9+/]{40,}={0,2}")),
    ("aws-key", re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    ("openai-anthropic-key", re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("huggingface-token", re.compile(r"hf_[A-Za-z0-9]{30,}")),
    ("npm-token", re.compile(r"npm_[A-Za-z0-9]{36}")),
    ("gitlab-token", re.compile(r"glpat-[A-Za-z0-9_-]{20}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("age-secret-key", re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{20,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("azure-account-key", re.compile(r"AccountKey=[A-Za-z0-9+/=]{40,}")),
    ("connection-string", re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/]+:[^@\s]+@")),
    ("assignment", re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|client[_-]?secret|password|passwd|auth[_-]?token)"
                              r"\s*[:=]\s*['\"]?(?!<|\$\{|\$[A-Z_]|\*\*\*|xxx|<redacted>)[A-Za-z0-9_\-/+=]{16,}")),
]
GITLEAKS_EXIT = 9


class Item:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self.data = data
        self.reasons: list = []

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")


def load_config(start: str) -> dict:
    """boundary, client_markers, egress_allowed_targets from the nearest .claude/guard.json, then env."""
    cfg: dict = {"boundary": "own", "client_markers": [], "egress_allowed_targets": DEFAULT_ALLOWED_TARGETS,
                 "config_error": ""}
    d = os.path.abspath(start)
    while True:
        candidate = os.path.join(d, ".claude", "guard.json")
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    raise ValueError("top level is not an object")
                for k, typ in (("boundary", str), ("client_markers", list), ("egress_allowed_targets", list)):
                    if k in data:
                        ok = isinstance(data[k], typ) and (typ is not list or all(isinstance(x, str) for x in data[k]))
                        if not ok:
                            raise ValueError(f"{k} must be a {typ.__name__}" + (" of strings" if typ is list else ""))
                        cfg[k] = data[k]
            except (OSError, ValueError) as exc:  # a broken policy file holds everything; it never means "no policy"
                cfg["config_error"] = f"{candidate}: {exc.__class__.__name__}"
                cfg["boundary"] = "client"
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    env = (os.environ.get("KZ_BOUNDARY") or "").strip()
    if env == "client":
        cfg["boundary"] = "client"  # the environment can tighten the boundary, never loosen a repo's `client`
    return cfg


def secret_hits(text: str) -> list:
    return [name for name, rx in SECRET_RES if rx.search(text)]


def gitleaks_hit(data: bytes) -> Optional[bool]:
    """True = leak, False = clean, None = gitleaks absent or failed (own patterns still apply)."""
    exe = shutil.which("gitleaks")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "stdin", "--no-banner", "--redact", "--exit-code", str(GITLEAKS_EXIT)],
                           input=data, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == GITLEAKS_EXIT:
        return True
    if r.returncode == 0:
        return False
    return None


def screen_item(item: Item, target: str, cfg: dict, max_bytes: int, use_gitleaks: bool = True) -> list:
    reasons = []
    if cfg.get("config_error"):
        reasons.append(f"config:{cfg['config_error']}")
    if len(item.data) > max_bytes:
        reasons.append(f"size:{len(item.data)}>{max_bytes}")
    for name in secret_hits(item.text):
        reasons.append(f"secret:{name}")
    if use_gitleaks and not reasons and gitleaks_hit(item.data):
        reasons.append("secret:gitleaks")
    for marker in cfg.get("client_markers") or []:
        try:
            if re.search(marker, item.text, re.IGNORECASE):
                reasons.append(f"client-marker:{marker}")
        except re.error:
            if marker.lower() in item.text.lower():
                reasons.append(f"client-marker:{marker}")
    if str(cfg.get("boundary") or "own") == "client" and target not in (cfg.get("egress_allowed_targets") or []):
        reasons.append(f"boundary:client->{target}")
    item.reasons = reasons
    return reasons


def screen_text(text: str, target: str, cfg: dict, max_bytes: int = DEFAULT_MAX_BYTES) -> list:
    """Reasons to hold a single string; empty means send."""
    return screen_item(Item("text", text.encode("utf-8")), target, cfg, max_bytes)


def main(argv: list, stdin=None, stdout=None, stderr=None) -> int:
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    ap = argparse.ArgumentParser(prog="egress_screen", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="where the material goes: claude, copilot, gemini, ...")
    ap.add_argument("--pass", dest="pass_through", action="store_true", help="emit content on stdout when all sent")
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--no-gitleaks", action="store_true")
    ap.add_argument("files", nargs="*")
    ns = ap.parse_args(argv)
    cfg = load_config(os.getcwd())
    items = []
    if ns.files:
        for f in ns.files:
            try:
                with open(f, "rb") as fh:
                    items.append(Item(f, fh.read()))
            except OSError as exc:
                items.append(Item(f, b""))
                items[-1].reasons = [f"unreadable:{exc.__class__.__name__}"]
    else:
        raw = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read().encode("utf-8")
        items.append(Item("stdin", raw))
    report = stderr if ns.pass_through else stdout
    held = 0
    for it in items:
        if not it.reasons:
            screen_item(it, ns.target, cfg, ns.max_bytes, use_gitleaks=not ns.no_gitleaks)
        if it.reasons:
            held += 1
            report.write(f"held:{','.join(it.reasons)}\t{it.name}\n")
        else:
            report.write(f"send\t{it.name}\n")
    stderr.write(f"egress: {len(items) - held} sent, {held} held (target {ns.target})\n")
    if held:
        return 3
    if ns.pass_through:
        out = stdout.buffer if hasattr(stdout, "buffer") else None
        for it in items:
            if out is not None:
                out.write(it.data)
            else:
                stdout.write(it.text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
