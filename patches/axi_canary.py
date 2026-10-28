"""AXI SRAM canary: a test image that checks whether the AXI SRAM no firmware code
references (m4host.axi_gap: between the M4's JSON buffer and the sample table, ~112 KB)
is really unused.

At power-on the region is filled with a pattern. Whenever the firmware saves its settings
(change any setting on a settings page and leave it), CANARY.TXT on the card root lists
the words overwritten since power-on, with a 1 KB-per-character map. Nothing else changes.
"""
import os

from perkons import m4host

TARGET = 'v1.3.0'
SUMMARY = 'Test image: report whether the unreferenced AXI SRAM gets overwritten (CANARY.TXT)'
RISK = 'low'

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src', 'm4')


def apply(p, arg=None):
    lo, hi = m4host.axi_gap(p.symbols['m4'])
    h = m4host.host(p)
    h.add([os.path.join(SRC, 'axi_canary.c')], init='pk_canary_fill', on_save='pk_canary_report',
          defines={'PK_GAP_START': f'0x{lo:08x}u', 'PK_GAP_END': f'0x{hi:08x}u'})
