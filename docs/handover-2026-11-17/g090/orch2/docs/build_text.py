"""Fill a draft from a JSON object of values and from whole files, and say which placeholders are left.

usage: python3 -I build_text.py <draft> <values.json> <out> [NAME=<file> ...]

`@@NAME@@` in the draft is exchanged for the value of NAME in values.json, or for the text of the file given as
NAME=<file> (stripped at both ends, its own placeholders filled from values.json first). A placeholder without a
value stays and is listed; the exit code is 1 then.
"""
import json
import re
import sys


def fill(text, values):
    for name in sorted(set(re.findall(r"@@([A-Z0-9]+)@@", text)) & set(values)):
        text = text.replace(f"@@{name}@@", values[name])
    return text


def main(argv):
    draft, values_path, out = argv[:3]
    with open(values_path, encoding="utf-8") as fh:
        values = dict(json.load(fh))
    for pair in argv[3:]:
        name, _, path = pair.partition("=")
        with open(path, encoding="utf-8") as fh:
            values[name] = fill(fh.read().strip(), values)
    with open(draft, encoding="utf-8") as fh:
        text = fill(fh.read(), values)
    left = sorted(set(re.findall(r"@@([A-Z0-9]+)@@", text)))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"{out.rsplit('/', 1)[-1]}: {len(text)} chars | left {left}")
    return 1 if left else 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
