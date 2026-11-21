"""Flash test: a test image that checks the bootloader writes every flash sector the stock
firmware never uses (rerun it if a bootloader update is suspected of changing that).

Both cores' segments run to the end of their flash regions: past the firmware and the
mods' code, a pattern fills the rest (M7 to 0x08100000, M4 to 0x08200000). Whenever the
firmware saves its settings (change any setting on a settings page and leave it),
FLASHTST.TXT on the card root lists each sector stock never writes as OK or BAD.

Debug builds only: the image is ~1.9 MB and takes longer to flash.
"""
import os

from perkons import m4host
from perkons.patch import PatchError, SEGMENT_LIMITS

TARGET = None  # any version
SUMMARY = 'Test image: does the bootloader write every flash sector? (FLASHTST.TXT)'

SRC = os.path.dirname(os.path.abspath(__file__))
CHECK = {'m7': (0x080E0000, 0x08100000),    # bank 1 sector 7: past the 6 sectors stock M7 uses
         'm4': (0x08140000, 0x08200000)}    # bank 2 sectors 2-7: past the 2 stock M4 uses


def pattern(a):
    return ((a * 0x9e3779b1) ^ 0x5a5aa5a5) & 0xffffffff


def fill(lo, hi):
    return b''.join(pattern(a).to_bytes(4, 'little') for a in range(lo, hi, 4))


def apply(p, arg=None):
    defines = {'PK_FT_B1_LO': f'0x{CHECK["m7"][0]:08x}u', 'PK_FT_B1_HI': f'0x{CHECK["m7"][1]:08x}u',
               'PK_FT_B2_LO': f'0x{CHECK["m4"][0]:08x}u', 'PK_FT_B2_HI': f'0x{CHECK["m4"][1]:08x}u'}
    m4host.host(p).add([os.path.join(SRC, 'src', 'm4', 'flash_test.c')], on_save='pk_flashtest_report',
                       defines=defines)

    def pad():                          # after both hosts have placed their code
        for seg in ('m7', 'm4'):
            start = p.cave_origin(seg, align=4)
            if start > CHECK[seg][0]:
                raise PatchError(f'flash_test: {seg} code ends at {start:#x}, past {CHECK[seg][0]:#x}')
            p.append(seg, fill(start, SEGMENT_LIMITS[seg][1]), f'flash test pattern, to the end of the {seg} region')
    p.on_finish(pad)
