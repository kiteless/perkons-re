#!/usr/bin/env python3
"""Run the framework tests plus every mod's tests (PERKONS_MODS, see tools/perkons/mods.py).

  run_tests.py [-v] [--fast] [--framework-only] [-j N] [--serial]

Test modules run in parallel worker processes (-j, default: the CPU count, at most 8),
the largest first; patched images are shared between them through the build cache
(.cache/builds/, see tests/fixtures.py). --serial runs everything in this process.
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, 'tests'), os.path.join(ROOT, 'tools'), ROOT):
    sys.path.insert(0, p)
from perkons.mods import add_to_path, mod_dirs  # noqa: E402

FAST = ['test_fwimage', 'test_patch', 'test_mod_clashes']


def test_dirs(framework_only):
    """[(tests dir, mod dir or None)]"""
    out = [(os.path.join(ROOT, 'tests'), None)]
    if not framework_only:
        out += [(os.path.join(m, 'tests'), m) for m in mod_dirs() if os.path.isdir(os.path.join(m, 'tests'))]
    return out


def setup_paths(tests, mod):
    if mod:
        add_to_path(mod)
    sys.path.insert(0, tests)


def run_one(tests, mod, module, verbose):
    """Worker: one test module; prints its result as JSON on the last line."""
    setup_paths(tests, mod)
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    r = unittest.TextTestRunner(verbosity=2 if verbose else 1, stream=sys.stderr).run(suite)
    print(json.dumps({'run': r.testsRun, 'failures': len(r.failures), 'errors': len(r.errors),
                      'skipped': len(r.skipped)}))
    return 0 if r.wasSuccessful() else 1


def jobs(framework_only):
    """[(tests dir, mod dir, module)], largest module first (a rough guide to its time)."""
    out = []
    for tests, mod in test_dirs(framework_only):
        for f in os.listdir(tests):
            if f.startswith('test_') and f.endswith('.py'):
                out.append((os.path.getsize(os.path.join(tests, f)), tests, mod, f[:-3]))
    return [(t, m, name) for _, t, m, name in sorted(out, key=lambda x: (-x[0], x[3]))]


def parallel(work, n, verbose):
    def go(job):
        tests, mod, module = job
        cmd = [sys.executable, os.path.abspath(__file__), '--one', tests, mod or '', module] + (['-v'] if verbose else [])
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        lines = r.stdout.strip().splitlines()
        try:
            res = json.loads(lines[-1])
        except (IndexError, ValueError):
            res = {'run': 0, 'failures': 0, 'errors': 1, 'skipped': 0}
        return job, res, r.stderr
    total = {'run': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    with concurrent.futures.ThreadPoolExecutor(n) as ex:
        for (tests, mod, module), res, err in ex.map(go, work):
            for k in total:
                total[k] += res[k]
            bad = res['failures'] or res['errors']
            where = os.path.relpath(os.path.join(tests, module), os.path.dirname(ROOT))
            print(f'{"FAIL" if bad else "ok  "} {where}: {res["run"]} tests'
                  + (f', {res["skipped"]} skipped' if res['skipped'] else ''), flush=True)
            if bad or verbose:
                print(err)
    ok = not total['failures'] and not total['errors']
    print(f'\nRan {total["run"]} tests ({total["skipped"]} skipped): '
          + ('OK' if ok else f'FAILED (failures={total["failures"]}, errors={total["errors"]})'))
    return 0 if ok else 1


def serial(work, verbose):
    suite = unittest.TestSuite()
    for tests, mod, module in work:
        setup_paths(tests, mod)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
    return 0 if unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite).wasSuccessful() else 1


def main():
    args = sys.argv[1:]
    verbose = '-v' in args
    if args and args[0] == '--one':
        _, tests, mod, module = args[:4]
        return run_one(tests, mod or None, module, verbose)
    if '--fast' in args:
        return serial([(os.path.join(ROOT, 'tests'), None, m) for m in FAST], verbose)
    work = jobs('--framework-only' in args)
    if '--serial' in args:
        return serial(work, verbose)
    n = int(args[args.index('-j') + 1]) if '-j' in args else min(os.cpu_count() or 1, 8)
    return parallel(work, n, verbose)


if __name__ == '__main__':
    sys.exit(main())
