"""Locate official firmware images (not in the repo) and shared test helpers."""
import glob
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, ROOT)

IMAGES = {
    'v1.1.1': 'perkons_both_v1.1.1-0-g8447464.img',
    'v1.2.1': 'perkons_both_v1.2.1-0-gbcccfd0.img',
    'v1.2.2': 'perkons_both_v1.2.2-0-g243b10f_force.img',
    'v1.3.0': 'perkons_v1.3.0-0-force.img',
}
SYMBOLS_V130 = os.path.join(ROOT, 'symbols', 'v1.3.0-m7.json')


def image_path(version):
    """Official images live in the repo root or firmware/ (both gitignored)."""
    name = IMAGES[version]
    for d in (ROOT, os.path.join(ROOT, 'firmware')):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def require_image(version):
    p = image_path(version)
    if p is None:
        raise unittest.SkipTest(f'official {IMAGES[version]} not found (put it in the repo root or firmware/)')
    return p


class Built:
    """What a cached build hands back in place of its Patcher: the linked symbols."""

    def __init__(self, cave_symbols):
        self.cave_symbols = cave_symbols


def build_patched(stock, names, build_dir):
    """Apply patch specs `names` ('name' or 'name:arg', this repo or PERKONS_MODS) to the
    v1.3.0 image `stock`. Returns (Image, Patcher), or (Image, Built) from the build cache
    (.cache/builds/, keyed by every build input: tests that build the same image share it,
    across processes and runs)."""
    import hashlib
    import json
    from perkons import srchash
    from perkons.emu import Symbols
    from perkons.fwimage import Image
    from perkons.mods import load_patch
    from perkons.patch import Patcher
    base = hashlib.sha256(b''.join(seg.data for seg in stock.segments)).hexdigest()
    k = srchash.key(base, *names)
    img_path, sym_path = srchash.path('builds', k, '.img'), srchash.path('builds', k, '.json')
    if os.path.exists(img_path) and os.path.exists(sym_path):
        with open(sym_path) as f:
            return Image.load(img_path), Built(json.load(f))
    p = Patcher(stock)
    p.symbols = {'m7': Symbols(SYMBOLS_V130), 'm4': Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))}
    p.build_dir = build_dir
    for spec in names:
        name, _, arg = spec.partition(':')
        mod = load_patch(name)
        mod.apply(p, arg) if arg else mod.apply(p)
    img = p.result()
    for path, write in ((img_path, img.save), (sym_path, lambda t: _dump(getattr(p, 'cave_symbols', {}), t))):
        write(path + '.tmp')
        os.replace(path + '.tmp', path)             # whole files only: tests run in parallel
    return img, p


def _dump(obj, path):
    import json
    with open(path, 'w') as f:
        json.dump(obj, f)
