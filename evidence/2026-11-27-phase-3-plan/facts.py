#!/usr/bin/env python3
"""Read-only facts for the Phase 3 plan (docs/PLAN-2026-11-phase-3.md, item #114).

  python3 evidence/2026-11-27-phase-3-plan/facts.py <checkout> > facts-<date>.txt

Standard library only. It writes nothing into the checkout: the guard's telemetry and Claude folder are pointed at
a temporary folder, and the working directory is that folder. It prints, for the checkout given:
  1. Python lines per tool, tests apart;
  2. which test files start the command line and which load a module in-process (a text search, not a parse);
  3. the fixture corpus by harness and verdict;
  4. every pattern the guard compiles, at import and while each rule judges each fixture event, and what each
     pattern uses that the Rust `regex` crate lacks or reads differently;
  5. the hook's time against interpreter start (medians of 30 runs; these depend on the machine).
Gate G0 of the plan runs it again after Phase 2 and compares.
"""
import ast
import collections
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

try:  # Python 3.11 and later
    import re._parser as sre_parse
except ImportError:  # Python 3.9 and 3.10
    import sre_parse

W = pathlib.Path(sys.argv[1]).resolve()
G = W / "tools" / "guard"
FIX = G / "tests" / "fixtures"

print("python", sys.version.split()[0])
print("head", subprocess.run(["git", "-C", str(W), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
print("guard.py last changed in", subprocess.run(
    ["git", "-C", str(W), "log", "-1", "--format=%H", "--", "tools/guard/guard.py"],
    capture_output=True, text=True).stdout.strip())


def lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


# ---- 1. sizes
per_tool = collections.Counter()
tests = collections.Counter()
test_files = []
for p in sorted((W / "tools").rglob("*.py")):
    parts = p.relative_to(W).parts
    tool = parts[1] if len(parts) > 2 else "(top)"
    if "tests" in parts:
        tests[tool] += lines(p)
        if p.name.startswith("test_"):
            test_files.append(p)
    else:
        per_tool[tool] += lines(p)
print("\n== non-test python lines per tool:", dict(per_tool), "total", sum(per_tool.values()))
print("== test python lines per tool:", dict(tests), "total", sum(tests.values()))

# ---- 2. test files: who starts the command line, who loads in-process (a text search)
IN_PROCESS = re.compile(r"spec_from_file_location|importlib|\bguard\b\s*[,)]")
kinds = collections.Counter()
guard_kinds = collections.Counter()
for p in test_files:
    text = p.read_text(encoding="utf-8", errors="replace")
    spawns, loads = "subprocess" in text, bool(IN_PROCESS.search(text))
    kind = "both" if spawns and loads else "spawn" if spawns else "in-process" if loads else "neither"
    kinds[kind] += 1
    if "guard" in p.parts:
        guard_kinds[kind] += 1
print(f"\n== test files: {len(test_files)};", dict(kinds))
print("== guard test files:", dict(guard_kinds), "of", sum(guard_kinds.values()))

# ---- 3. fixtures
n = collections.Counter()
keys = collections.Counter()
for p in FIX.rglob("*"):
    if not p.is_file():
        continue
    rel = p.relative_to(FIX).parts
    n["files"] += 1
    if rel[0].startswith("_"):
        n[rel[0]] += 1
    elif len(rel) == 4:
        n[f"case:{rel[1]}:{rel[2]}"] += 1
        n["cases"] += 1
    else:
        n["other"] += 1
    if p.suffix == ".json":
        try:
            raw = json.loads(p.read_text())
        except ValueError:
            continue
        if isinstance(raw, dict) and isinstance(raw.get("_fixture"), dict):
            for key in raw["_fixture"]:
                keys["_fixture." + key] += 1
print("\n== fixtures:", dict(sorted(n.items())))
print("== rule folders:", len([d for d in FIX.iterdir() if d.is_dir() and not d.name.startswith("_")]))
print("== _fixture keys:", dict(keys))

# ---- 4. every pattern the guard compiles: at import, then with each rule run on each fixture event
seen = {}  # the guard's own patterns: compiled by a call that stands in guard.py
others = {}  # compiled by the standard library on the guard's behalf (shlex, pathlib's globbing, ...)
_compile = re._compile
RE_FILE = os.path.dirname(re.__file__)
GUARD_FILE = str(G / "guard.py")


def _recording(pattern, flags):
    if isinstance(pattern, str):
        frame = sys._getframe(1)
        while frame is not None and frame.f_code.co_filename.startswith(RE_FILE):  # re.compile, re.search, ...
            frame = frame.f_back
        by_guard = frame is not None and frame.f_code.co_filename == GUARD_FILE
        (seen if by_guard else others)[(pattern, int(flags))] = True
    return _compile(pattern, flags)


re._compile = _recording
tmp = tempfile.mkdtemp(prefix="facts-")
os.environ["KZ_TELEMETRY_DIR"] = os.path.join(tmp, "telemetry")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(tmp, "claude-config")
for name in ("KZ_RULES_OFF", "KZ_BOUNDARY", "CLAUDE_CODE_REMOTE", "CLAUDE_PROJECT_DIR"):
    os.environ.pop(name, None)
os.chdir(tmp)
spec = importlib.util.spec_from_file_location("guard", G / "guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
at_import = len(seen)
ran = unreadable = 0
for rule_dir in sorted(d for d in FIX.iterdir() if d.is_dir() and not d.name.startswith("_")):
    for p in sorted(rule_dir.rglob("*.json")):
        try:
            raw = json.loads(p.read_text())
            ev = guard.Event(raw)
            cfg = {**guard.load_config(os.getcwd()), **raw.get("_fixture", {}).get("config", {})}
        except Exception:  # counted and printed: an event this script cannot build
            unreadable += 1
            continue
        for rule in guard.RULES.values():  # every rule on every event reaches more patterns than the rule named
            try:
                rule(ev, cfg)
            except Exception:  # a rule that needs a real tree: its patterns are compiled before it fails
                pass
        ran += 1
re._compile = _compile
print(f"\n== the guard's own patterns: {at_import} compiled at import, {len(seen)} after {ran} fixture events",
      f"({unreadable} unreadable); compiled by other modules meanwhile, not counted: {len(others)}")


def walk(tree, found):
    for op, av in tree:
        name = str(op)
        if name in ("ASSERT", "ASSERT_NOT"):
            direction, sub = av
            found["look" + ("ahead" if direction > 0 else "behind") + ("" if name == "ASSERT" else "_neg")] += 1
            walk(sub, found)
        elif name == "GROUPREF":
            found["backref"] += 1
        elif name == "GROUPREF_EXISTS":
            found["conditional"] += 1
            for sub in av[1:]:
                if sub is not None:
                    walk(sub, found)
        elif name == "AT":
            found["at:" + str(av)] += 1
        elif name == "CATEGORY":
            found["cat:" + str(av)] += 1
        elif name == "IN":
            for op2, av2 in av:
                if str(op2) == "CATEGORY":
                    found["cat:" + str(av2)] += 1
        elif name == "ATOMIC_GROUP":
            found["atomic_group"] += 1
            walk(av, found)
        elif name == "SUBPATTERN":
            walk(av[3], found)
        elif name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
            if name != "MAX_REPEAT":
                found["lazy" if name == "MIN_REPEAT" else "possessive"] += 1
            walk(av[2], found)
        elif name == "BRANCH":
            for sub in av[1]:
                walk(sub, found)


HARD = ("lookahead", "lookahead_neg", "lookbehind", "lookbehind_neg", "backref", "conditional")
uses = collections.Counter()
flag_count = collections.Counter()
hard = []
for pattern, flags in seen:
    tree = sre_parse.parse(pattern, flags)
    found = collections.Counter()
    walk(tree, found)
    for key in found:
        uses[key] += 1  # patterns that use it, not occurrences
    for flag in ("IGNORECASE", "MULTILINE", "DOTALL", "VERBOSE", "ASCII"):
        if (flags | tree.state.flags) & getattr(re, flag):
            flag_count[flag] += 1
    if any(key in found for key in HARD):
        hard.append((pattern, flags, {key: found[key] for key in HARD if key in found}))
print("== patterns that use a feature:", dict(sorted(uses.items())))
print("== patterns per flag:", dict(flag_count))
print(f"== patterns with lookaround, a backreference or a conditional: {len(hard)}")
for pattern, flags, found in sorted(hard):
    print("   ", found, "| flags", flags, "|", pattern[:150].replace("\n", "\\n"))

source = (G / "guard.py").read_text()
parsed = ast.parse(source)
functions = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(parsed))
classes = sum(isinstance(node, ast.ClassDef) for node in ast.walk(parsed))
print(f"\n== guard.py: {lines(G / 'guard.py')} lines, {functions} functions, {classes} classes,",
      f"{len(guard.RULES)} rules: {list(guard.RULES)}")
print("== version:", guard.VERSION, "| subprocess.run calls:", len(re.findall(r"subprocess\.run\(", source)),
      "| environment names read:", sorted(set(re.findall(r"environ(?:\.get)?[\[(]\s*\"([A-Z_0-9]+)\"", source))))

# ---- 5. the hook's time on one Bash event, against interpreter start (machine-dependent)
case = sorted((FIX / "git-guard" / "claude" / "allow").glob("*.json"))[0]
event = case.read_bytes()


def bench(argv, stdin, runs=30):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run(argv, input=stdin, capture_output=True)
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    return f"{times[len(times) // 2]:.1f} {times[0]:.1f} {times[-1]:.1f}"


py = sys.executable
print("\n== timing in ms (median, fastest, slowest) over 30 runs; event", case.name)
print("   python3 -c pass          :", bench([py, "-c", "pass"], b""))
print("   guard.py version         :", bench([py, str(G / "guard.py"), "version"], b""))
print("   guard.py hook pre claude :", bench([py, str(G / "guard.py"), "hook", "pre", "--wrapper", "claude"], event))
print("   /bin/sh -c :             :", bench(["/bin/sh", "-c", ":"], b""))
