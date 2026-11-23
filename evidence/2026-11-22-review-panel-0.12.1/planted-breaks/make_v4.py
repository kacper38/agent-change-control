"""Planted breaks of review round 3 (item #69): round 2's panel list with its %G breaks moved to the new line, plus
the modifier break; round 2's install list unchanged (its fourth kit is the new row). usage: python3 -I make_v4.py
<mut folder>. Writes panel_mutants_v4.json."""
import json
import pathlib
import sys

mut = pathlib.Path(sys.argv[1])
moved = {
    "no-percent-G": ["return SIGNATURE.test(a) || (", "return ("],
    "percent-g-any-case": ["new RegExp('%[-+ ]?G')", "new RegExp('%[-+ ]?G', 'i')"],
}
panel = [[n, *moved.get(n, [o, new])] for n, o, new in json.loads((mut / "panel_mutants_v3.json").read_text())]
panel += [
    ["signature-no-modifier", "new RegExp('%[-+ ]?G')", "new RegExp('%G')"],
    ["signature-no-space", "new RegExp('%[-+ ]?G')", "new RegExp('%[-+]?G')"],
]
(mut / "panel_mutants_v4.json").write_text(json.dumps(panel, indent=1) + "\n")
print("panel_mutants_v4.json", len(panel))
