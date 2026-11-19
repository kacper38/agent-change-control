"""Does this file system open a file under a name written with U+017F (long s) or U+212A (Kelvin sign)?

usage: python3 -I fs_fold.py <empty scratch folder>

Writes two small files into the scratch folder and asks the file system for them under other spellings.
Prints, per spelling, whether the file is found, and what str.lower() and str.casefold() make of the name.
"""
import os
import sys


def main(argv):
    folder = argv[0]
    os.makedirs(folder, exist_ok=True)
    for name in ("settings.json", "hooks.txt"):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write("x\n")
    for plain, other, label in (("settings.json", "ſettings.json", "U+017F for s"),
                                ("settings.json", "SETTINGS.JSON", "capitals"),
                                ("hooks.txt", "hooKs.txt", "U+212A for k"),
                                ("hooks.txt", "hookſ.txt", "U+017F for the last s")):
        found = os.path.exists(os.path.join(folder, other))
        print(f"{label:22} found: {'yes' if found else 'no '} | lower() gives the plain name: "
              f"{'yes' if other.lower() == plain else 'no '} | casefold() gives it: "
              f"{'yes' if other.casefold() == plain else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
