#!/usr/bin/env python3
"""caps_pairs.py with the reference overlay laid over the guard first: shows what the decided design reaches
on the pair check, and which weaker pairs are left for reasons outside the design (shell words, names that
no table holds). Same arguments as caps_pairs.py. Strings only; nothing runs.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv):
    pairs = load(os.path.join(HERE, "caps_pairs.py"), "caps_pairs_helper")
    ref = load(os.path.join(HERE, "ref_fold.py"), "ref_fold_helper")
    real_load = pairs.load

    def load_with_overlay(path, name):
        mod = real_load(path, name)
        if name == "expect_helper":  # the guard is loaded through expect.load: wrap that
            inner = mod.load

            def guard_with_overlay(p):
                g = inner(p)
                ref.overlay(g)
                return g

            mod.load = guard_with_overlay
        return mod

    pairs.load = load_with_overlay
    return pairs.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
