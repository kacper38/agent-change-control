"""Does the quote reading of the quiet check (`_quiet_mask`) agree with the lexer's (`_hi_lex`)?

usage: python3 -u -I mask_fuzz.py <guard.py> [--samples N] [--seed S] [--show K]

Random strings over quotes, backslashes, `$`, brackets, the lexer's separators, blanks and a few letters are
prepared (`_hi_prepare`), then lexed twice: as they are, and after `_quiet_mask`. Wherever the mask gives a text
and the lexer reads the plain text, three things must hold:
  1. the masked text lexes to the same separators and, with the mask taken off, to the same words;
  2. no word of the masked text holds an unmasked separator character: one quoted for the lexer went unmasked;
  3. no word of the masked text holds an unmasked blank: the same for whitespace.
A string for which one fails is printed (as JSON) with the two readings. Nothing is run; strings are only lexed.
"""
import importlib.util
import json
import random
import re
import sys

ALPHABET = ["'", '"', "\\", "$", "(", ")", "{", "}", "[", "]", "`", ";", "|", "&", "\n", " ", " ", "a", "b",
            "fi", "#", "<", ">", "_", "=", "-", "''", '""', " { ", " } ", " fi "]


def load(path):
    spec = importlib.util.spec_from_file_location("guard_mask_fuzz", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    files, samples, seed, show = [], 200000, 1, 10
    it = iter(argv)
    for a in it:
        if a == "--samples":
            samples = int(next(it))
        elif a == "--seed":
            seed = int(next(it))
        elif a == "--show":
            show = int(next(it))
        else:
            files.append(a)
    g = load(files[0])
    rng = random.Random(seed)
    punct = set(g._HI_PUNCT)
    done = masked_ok = unreadable = no_mask = quirk = 0
    bad = []
    while done < samples:
        text = "".join(rng.choice(ALPHABET) for _ in range(rng.randrange(1, 22)))
        done += 1
        prepared = g._hi_prepare(text)[0]
        plain = g._hi_lex(prepared)
        masked = g._quiet_mask(prepared)
        if masked is None:
            no_mask += 1
            continue
        got = g._hi_lex(masked)
        if plain is None or got is None:
            if (plain is None) != (got is None):
                bad.append(("one reading fails, the other does not", text, plain, got))
            unreadable += 1
            continue
        masked_ok += 1
        back = [(sep, [g._quiet_unmask(t) for t in toks]) for sep, toks in got]
        # the lexer takes a word that is all separator characters for a separator, also a quoted or escaped one
        # (`\;`, `'|'`); the masked reading keeps such a word a word, as the shell does: these strings differ
        # by that alone and are counted, not compared
        if any(t and all(c in punct for c in t) for _sep, toks in back for t in toks):
            quirk += 1
        elif back != plain:
            bad.append(("the words differ", text, plain, back))
            continue
        for _sep, toks in got:
            for t in toks:
                if any(c in punct for c in t):
                    bad.append(("a quoted separator went unmasked", text, plain, got))
                elif any(c in " \t" for c in t):
                    bad.append(("a quoted blank went unmasked", text, plain, got))
        # 4. a word of the masked text that is exactly `{`, `}` or `fi` stands bare in the prepared text: between
        #    blanks, separators or the ends, with no quote or backslash at its side
        for word in ("{", "}", "fi"):
            exact = sum(t == word for _sep, toks in got for t in toks)
            bare = len(re.findall(r"(?<![^\s;&|()`])" + re.escape(word) + r"(?![^\s;&|()`])", prepared))
            if exact > bare:
                bad.append((f"a quoted `{word}` reads as a bare one", text, plain, got))
    print(f"strings {done} | masked and lexed {masked_ok} | of them with a quoted word of separator characters "
          f"{quirk} | the mask gave up {no_mask} | not lexed {unreadable} | FAILURES {len(bad)}")
    for why, text, a, b in bad[:show]:
        print(f"  {why}: {json.dumps(text)}\n     plain  {a}\n     masked {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
