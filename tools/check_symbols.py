#!/usr/bin/env python3
"""Check a firmware image's symbols by behaviour (see tools/perkons/symcheck.py).

  check_symbols.py <img> [--symbols-dir symbols] [--ver v1.3.0]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from perkons.emu import Symbols  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.symcheck import run_all  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('--symbols-dir', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'symbols'))
    ap.add_argument('--ver')
    a = ap.parse_args()
    img = Image.load(a.img)
    ver = a.ver or f'v{img.version}'
    s7 = Symbols(os.path.join(a.symbols_dir, f'{ver}-m7.json'))
    s4 = Symbols(os.path.join(a.symbols_dir, f'{ver}-m4.json'))
    res = run_all(img, s7, s4)
    for name, ok, detail in res:
        print(f'{"PASS" if ok else "FAIL"}  {name:14s} {detail}')
    bad = sum(1 for r in res if not r[1])
    print(f'\n{len(res) - bad}/{len(res)} checks passed for {ver}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
