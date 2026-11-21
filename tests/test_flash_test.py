"""flash_test: pattern to the end of both flash regions, FLASHTST.TXT on settings save.
Needs arm-none-eabi-gcc."""
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons.emu import M4Emu, Symbols
from perkons.fwimage import Image
from patches import flash_test


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestFlashTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s4 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))
        cls.tmp = tempfile.mkdtemp(prefix='pk-flashtest-')
        stock = Image.load(require_image('v1.3.0'))
        cls.img, p = build_patched(stock, ['voice_map', 'flash_test'], cls.tmp + '/1')
        cls.s = p.cave_symbols['m4host']

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def report(self, img, s, damage=()):
        e = M4Emu(img.segment('m4').data, self.s4, img.segment('m7').data,
                  sd={'system/device.json': b'{}'}).boot()
        e.call(s['pk4_boot'], max_insns=50_000_000)
        for addr, data in damage:
            e.uc.mem_write(addr, data)
        e.call(s['pk4_device_json_save'], max_insns=200_000_000)
        return e.sd_written['flashtst.txt'].decode()

    def test_segments_run_to_the_region_ends(self):
        self.assertEqual(self.img.segment('m7').addr + len(self.img.segment('m7').data), 0x08100000)
        self.assertEqual(self.img.segment('m4').addr + len(self.img.segment('m4').data), 0x08200000)

    def test_all_ok(self):
        txt = self.report(self.img, self.s)
        self.assertEqual(txt.count(': OK\r\n'), 7, txt)         # bank 1 sector 7, bank 2 sectors 2-7
        self.assertIn('0x080e0000 bank 1 sector 7: OK', txt)
        self.assertIn('0x081e0000 bank 2 sector 7: OK', txt)
        self.assertTrue(txt.endswith('RESULT: ALL OK\r\n'))

    def test_damage_reported(self):
        txt = self.report(self.img, self.s, [(0x080e0010, b'\0\0\0\0'), (0x081c0000, b'\xff' * 8)])
        self.assertIn('0x080e0000 bank 1 sector 7: BAD, 1 words differ (0 erased)', txt)
        self.assertIn('0x081c0000 bank 2 sector 6: BAD, 2 words differ (2 erased)', txt)
        self.assertTrue(txt.endswith('RESULT: FAIL\r\n'))


if __name__ == '__main__':
    unittest.main()
