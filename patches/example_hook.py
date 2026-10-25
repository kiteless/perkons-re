"""Template for a C patch: redirect one `bl` to C code in a code cave.

Builds patches/src/m7/example_hook.c, appends it after the M7 segment and redirects
main()'s call to wire_voices() through it. Behaviour is identical to stock (tested in
tests/test_example_hook.py), so it's a safe starting point to copy for a new mod.
"""
import os

from perkons import cbuild

TARGET = 'v1.3.0'
SUMMARY = 'Example: wrap main()\'s wire_voices() call with C code (no behaviour change)'
RISK = 'low'

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src', 'm7')


def apply(p):
    origin = p.cave_origin('m7')                        # code cave right after the segment
    blob, syms = cbuild.build('m7', [os.path.join(SRC, 'example_hook.c')], [SRC],
                              os.path.join(p.build_dir, 'example_hook'), origin, 'pk_example_wire',
                              p.symbols['m7'])
    assert p.append('m7', blob, f'example_hook code ({len(blob)} B)', align=16) == origin
    # by name: symbols/<version>-m7.json says where main() calls wire_voices; refuses to
    # patch unless that instruction really is `bl wire_voices`
    p.redirect_call('m7', 'main.call_wire_voices', syms['pk_example_wire'], 'main: wire_voices -> pk_example_wire')
