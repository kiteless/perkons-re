import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.patch import Patcher, PatchError, thumb_bl, thumb_bl_target, thumb_str_imm


class TestEncoders(unittest.TestCase):
    def test_encodings_disassemble_as_meant(self):
        from perkons.insn import disasm
        self.assertEqual(disasm(thumb_str_imm(5, 3, 0x28), 0, 1)[0], 'str r5, [r3, #0x28]')
        self.assertEqual(disasm(thumb_bl(0x1000, 0x2000), 0x1000, 1)[0], 'bl #0x2000')
        self.assertEqual(disasm(thumb_bl(0x1000, 0x2000, link=False), 0x1000, 1)[0], 'b.w #0x2000')

    def test_bl_target_inverts_bl(self):
        for src, dst in ((0x1000, 0x2000), (0x200000, 0x1000), (0x08100000, 0x081fff00)):
            self.assertEqual(thumb_bl_target(src, thumb_bl(src, dst)), dst)

    def test_match_the_firmware(self):
        """A call site in the symbols is a bl to its function, as thumb_bl encodes it."""
        sym = Symbols(SYMBOLS_V130)
        seg = Image.load(require_image('v1.3.0')).segment('m7')
        s = sym.site('main.call_wire_voices')
        insn = bytes(seg.data[s['addr'] - seg.addr:s['addr'] - seg.addr + 4])
        self.assertEqual(insn, thumb_bl(s['addr'], sym.fn[s['call']]))


class TestPatcherGuards(unittest.TestCase):
    def setUp(self):
        self.p = Patcher(Image.load(require_image('v1.3.0')))
        self.site = Symbols(SYMBOLS_V130).site('main.call_wire_voices')['addr']

    def test_wrong_expected_bytes_rejected(self):
        with self.assertRaises(PatchError):
            self.p.write('m7', self.site, b'\x00\x00', b'\xff\xff', 'bogus')

    def test_bootloader_region_rejected(self):
        with self.assertRaises(PatchError):
            self.p.write('m7', 0x08000000, b'\x00', b'\x00', 'bootloader')

    def test_unpatched_result_is_identical(self):
        with open(require_image('v1.3.0'), 'rb') as f:
            orig = f.read()
        self.assertEqual(self.p.result().build(), orig)
