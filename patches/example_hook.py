"""Template for a C patch: redirect one `bl` to C code in a code cave.

Builds patches/src/m7/example_hook.c, appends it after the M7 segment and redirects
main()'s call to wire_voices() through it. Behaviour is identical to stock (tested in
tests/test_example_hook.py), so it's a safe starting point to copy for a new mod.
"""
import os

from perkons import cbuild
from perkons.patch import thumb_bl

TARGET = 'v1.3.0'
SUMMARY = 'Example: wrap main()\'s wire_voices() call with C code (no behaviour change)'
RISK = 'low'

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src', 'm7')
SITE, ORIGINAL = 0x08027c9e, 0x080241d8   # main: bl wire_voices


def apply(p):
    seg = p.img.segment('m7')
    end = seg.addr + len(p.read('m7', seg.addr, 0x7fffffff))
    origin = (end + 15) & ~15                           # code cave right after the segment
    blob, syms = cbuild.build('m7', [os.path.join(SRC, 'example_hook.c')], [SRC],
                              os.path.join(p.build_dir, 'example_hook'), origin, 'pk_example_wire',
                              p.symbols['m7'])
    assert p.append('m7', blob, f'example_hook code ({len(blob)} B)', align=16) == origin
    # expected-bytes check: refuses to patch if the site isn't `bl wire_voices`
    p.write('m7', SITE, thumb_bl(SITE, syms['pk_example_wire']), thumb_bl(SITE, ORIGINAL),
            'main: wire_voices -> pk_example_wire')
