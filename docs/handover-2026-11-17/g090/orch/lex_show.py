"""Show how a guard's lexer splits lines into simple commands, and which reports it calls quiet.

usage: python3 -I lex_show.py <guard.py> <file with one line per command>

Loads the guard as a module and calls _hi_lex and _quiet_reports on each line. Nothing is run.
"""
import importlib.util
import json
import sys


def main(argv):
    spec = importlib.util.spec_from_file_location("guard_shown", argv[0])
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    with open(argv[1], encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            shown = line
            if line.startswith('"'):  # a JSON string, for a command with line breaks (as probe.py reads it)
                line = json.loads(line)
            cmds = guard._hi_lex(guard._hi_prepare(line)[0])
            quiet = guard._quiet_reports(line)
            print(shown)
            if cmds is None:
                print("    lexer gives up")
            else:
                print("    " + " ".join(f"[{sep!r} {' '.join(toks)!r}]" for sep, toks in cmds))
            print(f"    quiet reports: {list(quiet)!r}"[:230])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
