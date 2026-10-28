"""axi_canary: fills the unreferenced AXI SRAM at boot, reports overwrites on settings save.
Needs arm-none-eabi-gcc."""
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons import m4host
from perkons.emu import M4Emu, Symbols
from perkons.fwimage import Image


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestAxiCanary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s4 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))
        cls.tmp = tempfile.mkdtemp(prefix='pk-canary-')
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.img, p = build_patched(cls.stock, ['axi_canary'], cls.tmp)
        cls.s = p.cave_symbols['m4host']
        cls.lo, cls.hi = m4host.axi_gap(cls.s4)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def booted(self):
        e = M4Emu(self.img.segment('m4').data, self.s4, self.img.segment('m7').data,
                  sd={'system/device.json': b'{"vintage-bbd": true}'}).boot()
        e.call(self.s['pk4_boot'], max_insns=50_000_000)
        return e

    def report(self, e):
        e.call(self.s['pk4_device_json_save'], max_insns=50_000_000)
        return e.sd_written['canary.txt'].decode()

    def test_gap_between_json_buffer_and_samples(self):
        self.assertEqual((self.lo, self.hi), (0x24004000, 0x2401fe00))

    def test_intact_region_reports_nothing(self):
        e = self.booted()
        self.assertNotEqual(e.r32(self.lo), e.r32(self.lo + 4), 'filled with a pattern')
        txt = self.report(e)
        self.assertIn('changed words: 0\r\n', txt)
        self.assertNotIn('X', txt.split("'X' changed):")[1])

    def test_overwrites_reported_with_map(self):
        e = self.booted()
        e.uc.mem_write(self.lo + 5 * 1024 + 8, bytes(8))     # two words in block 5
        e.uc.mem_write(self.hi - 4, bytes(4))                 # the last word
        txt = self.report(e)
        self.assertIn('changed words: 3\r\n', txt)
        self.assertIn(f'first changed: 0x{self.lo + 5 * 1024 + 8:08x}', txt)
        self.assertIn(f'last changed: 0x{self.hi - 4:08x}', txt)
        rows = txt.split("'X' changed):\r\n")[1].split('\r\n')
        cells = ''.join(rows)
        self.assertEqual(len(cells), (self.hi - self.lo + 1023) // 1024)
        self.assertEqual([i for i, c in enumerate(cells) if c == 'X'], [5, len(cells) - 1])

    def test_reports_count_and_device_json_still_saved(self):
        e = self.booted()
        self.report(e)
        txt = self.report(e)
        self.assertIn('report 2 since power-on', txt)
        self.assertIn('"vintage-bbd": true', e.sd_written['system/device.json'].decode())

    def test_only_the_save_sites_and_boot_patched(self):
        seg, stock = self.img.segment('m4'), self.stock.segment('m4')
        for site in ('cfg_page.event_word', 'cfg_page.render_word'):
            a = self.s4.site(site)['addr'] - seg.addr
            self.assertEqual(seg.data[a:a + 4], stock.data[a:a + 4], site)
