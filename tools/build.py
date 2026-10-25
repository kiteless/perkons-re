#!/usr/bin/env python3
"""Build a patched firmware image and check it in the emulator.

  build.py <base.img> <out.img> <patch> [<patch> ...] [--symbols symbols/v1.3.0-m7.json] [--no-emu]

<patch> names a module in patches/ or in a mod's patches/ (see tools/perkons/mods.py),
optionally with an argument: name:arg. After building, it:
  1. re-parses the output and checks CRCs
  2. boots the patched M7 through main()'s real wiring code in the emulator and reports
     which engine each output runs
  3. for every output/algo/mode, renders it through the real message handling and audio
     callback and checks it's bit-identical to the stock engine it runs (rand() pinned)
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, ROOT)
from perkons import verify  # noqa: E402
from perkons.emu import Symbols  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.mods import load_patch  # noqa: E402
from perkons.patch import Patcher  # noqa: E402


def build_image(base, out_path, specs, symbols_m7, build_dir=None, extra_kwargs=None):
    """Apply patch specs ('name' or 'name:arg') to `base` and write `out_path`.
    extra_kwargs: {patch name: {kwarg: value}} passed to that patch's apply().
    Returns (Image, Patcher)."""
    p = Patcher(base)
    p.symbols = {'m7': Symbols(symbols_m7), 'm4': Symbols(symbols_m7.replace('-m7.json', '-m4.json'))}
    p.build_dir = build_dir or os.path.join(os.path.dirname(os.path.abspath(out_path)), 'obj',
                                            os.path.basename(out_path))
    for spec in specs:
        name, _, arg = spec.partition(':')
        mod = load_patch(name)
        if mod.TARGET not in (None, f'v{base.version}'):
            sys.exit(f'{name} targets {mod.TARGET}, base image is v{base.version}')
        print(f'[{mod.RISK:>6}] {spec}: {mod.SUMMARY}')
        kw = (extra_kwargs or {}).get(name, {})
        mod.apply(p, arg, **kw) if arg else mod.apply(p, **kw)
    print(p.report())
    p.result().save(out_path)
    chk = Image.load(out_path)
    assert all(s.crc_ok for s in chk.segments)
    print(chk.describe())
    print(f'-> {out_path}')
    return chk, p


def regression(base, chk, symbols_m7):
    """Every output/algo/mode vs the stock engine it runs. Returns the failing cases."""
    sym = Symbols(symbols_m7)
    emap = verify.engine_map(chk, sym)
    print('emulated boot OK; outputs run stock voice engines:', ' '.join(str(v + 1) for v in emap))
    print('checking every output/algo/mode against stock (36 renders x2)...')
    res = verify.compare_to_stock(base, chk, sym)
    bad = [r for r in res if not r[4]]
    print(f'{len(res) - len(bad)}/{len(res)} identical to the stock engine they run')
    for out, algo, mode, eng, _ in bad:
        print(f'  DIFFERS: output {out + 1} algo {algo} mode {mode} (engine of voice {eng + 1})')
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base')
    ap.add_argument('out')
    ap.add_argument('patches', nargs='+')
    ap.add_argument('--symbols', default=os.path.join(ROOT, 'symbols', 'v1.3.0-m7.json'))
    ap.add_argument('--no-emu', action='store_true')
    a = ap.parse_args()

    base = Image.load(a.base)
    chk, _ = build_image(base, a.out, a.patches, a.symbols)
    if not a.no_emu:
        regression(base, chk, a.symbols)


if __name__ == '__main__':
    main()
