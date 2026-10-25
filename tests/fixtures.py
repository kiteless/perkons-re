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
