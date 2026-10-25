#!/usr/bin/env python3
"""Run the framework tests plus every mod's tests (PERKONS_MODS, see tools/perkons/mods.py).

  run_tests.py [-v] [--fast] [--framework-only]
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, 'tests'), os.path.join(ROOT, 'tools'), ROOT):
    sys.path.insert(0, p)
from perkons.mods import add_to_path, mod_dirs  # noqa: E402

FAST = ['test_fwimage', 'test_patch']


def main():
    args = sys.argv[1:]
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    if '--fast' in args:
        suite.addTests(loader.loadTestsFromNames(FAST))
    else:
        suite.addTests(loader.discover(os.path.join(ROOT, 'tests'), top_level_dir=os.path.join(ROOT, 'tests')))
        if '--framework-only' not in args:
            for mod in mod_dirs():
                tests = os.path.join(mod, 'tests')
                if os.path.isdir(tests):
                    add_to_path(mod)
                    sys.path.insert(0, tests)
                    print(f'+ mod tests: {tests}')
                    suite.addTests(loader.discover(tests, top_level_dir=tests))
    result = unittest.TextTestRunner(verbosity=2 if '-v' in args else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
