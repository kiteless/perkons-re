import unittest

from fixtures import require_image
from perkons.fwimage import Image
from perkons.patch import Patcher, PatchError, thumb_bl, thumb_str_imm


class TestEncoders(unittest.TestCase):
    def test_match_firmware_bytes(self):
        # instructions as they appear in v1.3.0 M7
        self.assertEqual(thumb_str_imm(5, 3, 0x28), bytes.fromhex('9d62'))  # 0x0802421a
        self.assertEqual(thumb_str_imm(4, 3, 0x2c), bytes.fromhex('dc62'))  # 0x0802429c
        self.assertEqual(thumb_bl(0x08027c9e, 0x080241d8), bytes.fromhex('fcf79bfa'))  # bl wire_voices


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
