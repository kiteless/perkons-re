import unittest

from fixtures import require_image
from perkons.fwimage import Image
from perkons.patch import Patcher, PatchError, thumb_bl, thumb_str_imm


class TestEncoders(unittest.TestCase):
    def test_encodings_disassemble_as_meant(self):
        from perkons.insn import disasm
        self.assertEqual(disasm(thumb_str_imm(5, 3, 0x28), 0, 1)[0], 'str r5, [r3, #0x28]')
        self.assertEqual(disasm(thumb_str_imm(4, 3, 0x2c), 0, 1)[0], 'str r4, [r3, #0x2c]')
        self.assertEqual(disasm(thumb_bl(0x08027c9e, 0x080241d8), 0x08027c9e, 1)[0], 'bl #0x80241d8')
        self.assertEqual(disasm(thumb_bl(0x08027c9e, 0x080241d8, link=False), 0x08027c9e, 1)[0], 'b.w #0x80241d8')

    def test_match_the_firmware(self):
        """In v1.3.0 M7 wire_voices stores slots[0] / [1] and main calls it like this."""
        seg = Image.load(require_image('v1.3.0')).segment('m7')
        at = lambda a, n: bytes(seg.data[a - seg.addr:a - seg.addr + n])
        self.assertEqual(at(0x0802421a, 2), thumb_str_imm(5, 3, 0x28))
        self.assertEqual(at(0x0802429c, 2), thumb_str_imm(4, 3, 0x2c))
        self.assertEqual(at(0x08027c9e, 4), thumb_bl(0x08027c9e, 0x080241d8))


class TestPatcherGuards(unittest.TestCase):
    def setUp(self):
        self.p = Patcher(Image.load(require_image('v1.3.0')))

    def test_wrong_expected_bytes_rejected(self):
        with self.assertRaises(PatchError):
            self.p.write('m7', 0x0802421a, b'\x00\x00', b'\xff\xff', 'bogus')

    def test_bootloader_region_rejected(self):
        with self.assertRaises(PatchError):
            self.p.write('m7', 0x08000000, b'\x00', b'\x00', 'bootloader')

    def test_unpatched_result_is_identical(self):
        with open(require_image('v1.3.0'), 'rb') as f:
            orig = f.read()
        self.assertEqual(self.p.result().build(), orig)
