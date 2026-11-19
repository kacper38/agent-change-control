"""Fill the `@@NAME@@` placeholders of a draft from a JSON object and say which are left.

usage: python3 -I fill.py <draft> <values.json> <out>

values.json is {"NAME": "text", ...}. A placeholder without a value stays as it is and is listed; a value
without a placeholder is listed too. Nothing else in the draft changes.
"""
import json
import re
import sys


def main(argv):
    draft, values_path, out = argv
    with open(draft, encoding="utf-8") as fh:
        text = fh.read()
    with open(values_path, encoding="utf-8") as fh:
        values = json.load(fh)
    names = set(re.findall(r"@@([A-Z0-9]+)@@", text))
    for name in sorted(names & set(values)):
        text = text.replace(f"@@{name}@@", values[name])
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"filled {len(names & set(values))} | left {sorted(names - set(values))} | unused {sorted(set(values) - names)}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(sys.argv[1:])
