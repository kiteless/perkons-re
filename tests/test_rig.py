"""The test rig (tools/perkons/rig.py) and the emulated SD card's directories."""
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons.emu import M4Emu, Symbols
from perkons.fwimage import Image
from perkons.rig import M4Rig


class TestRig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))

    def test_step_key_press_sets_the_step(self):
        r = M4Rig(self.stock)
        r.press(0x10 + 4)                                   # row 2 step 5
        blk = r.e.r32(r.voice_state(1) + 4)
        self.assertEqual((r.e.r8(blk + 8 * 4), r.e.r8(blk + 8 * 4 + 7)), (1, 0x7f))

    def test_held_step_and_ratchet(self):
        r = M4Rig(self.stock)
        r.held.update({0x20 + 8, 0x40})                     # row 3 step 9 + RATCHET held
        r.press(0x4b + 2)                                   # third trigger key: x4
        blk = r.e.r32(r.voice_state(2) + 4)
        self.assertEqual(r.e.r8(blk + 8 * 8 + 4), 3)


class TestCardDirectories(unittest.TestCase):
    def test_listing_and_stat(self):
        s4 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))
        img = Image.load(require_image('v1.3.0'))
        e = M4Emu(img.segment('m4').data, s4, img.segment('m7').data,
                  sd={'BANKS/00/00.PAT': b'x', 'BANKS/00/KITS/01.KIT': b'yy', 'voices.json': b'{}'}).boot()
        buf, dp, fno = 0x2407e000, 0x2407e100, 0x2407e200
        e.uc.mem_write(buf, b'BANKS/00\0')
        self.assertEqual(e.call(s4.fn['f_stat'], buf, fno), 0)
        self.assertEqual(e.r8(fno + 8), 0x10)
        self.assertEqual(e.call(s4.fn['f_opendir'], dp, buf), 0)
        names = []
        while True:
            e.call(s4.fn['f_readdir'], dp, fno)
            name = e.cstr(fno + 0x16)
            if not name:
                break
            names.append((name, e.r8(fno + 8)))
        self.assertEqual(names, [('00.PAT', 0x20), ('KITS', 0x10)])


if __name__ == '__main__':
    unittest.main()
