"""card_bench: the D3 canary, save/load timing and card measurements, reported in BENCH.TXT
whenever the settings are saved. Needs arm-none-eabi-gcc."""
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, build_patched, require_image
from perkons.emu import M4Emu, Symbols
from perkons.fwimage import Image
from perkons.mods import load_patch

cb = load_patch('card_bench')


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestCardBench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s4 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))
        cls.tmp = tempfile.mkdtemp(prefix='pk-bench-')
        cls.img, p = build_patched(Image.load(require_image('v1.3.0')), ['card_bench'], cls.tmp)
        cls.s = p.cave_symbols['m4host']
        cls.lo, cls.hi = cb.D3_GAP

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def booted(self, sd=None):
        card = {'system/device.json': b'{"vintage-bbd": true}', 'BENCH.WAV': bytes(range(256)) * 1024,
                'BANKS/00/SAMPLES/1.wav': b'RIFF', 'BANKS/00/SAMPLES/7.wav': b'RIFF'}
        card.update(sd or {})
        e = M4Emu(self.img.segment('m4').data, self.s4, self.img.segment('m7').data, sd=card).boot()
        e.call(self.s['pk4_boot'], max_insns=50_000_000)
        return e

    def report(self, e):
        e.call(self.s['pk4_device_json_save'], max_insns=400_000_000)
        return e.sd_written['bench.txt'].decode()

    def test_d3_gap_clear_of_the_channels_and_the_adc_buffer(self):
        self.assertEqual((self.lo, self.hi), (0x38004600, 0x3800fb00))
        self.assertGreaterEqual(self.lo, 0x38004500 + 0x100)            # inter-core channel buffers end
        self.assertLessEqual(self.hi, 0x3800fc00 - 0x100)               # ADC DMA buffer

    def test_d3_intact_then_overwrites_reported(self):
        e = self.booted()
        self.assertNotEqual(e.r32(self.lo), e.r32(self.lo + 4), 'filled with a pattern')
        self.assertIn('changed words 0\r\n', self.report(e))
        e.uc.mem_write(self.lo + 3 * 1024 + 16, bytes(4))
        txt = self.report(e)
        self.assertIn(f'changed words 1 (first 0x{self.lo + 3 * 1024 + 16:08x}', txt)
        line = txt.split("'X' changed): ")[1].split('\r\n')[0]
        self.assertEqual((len(line), line.index('X')), ((self.hi - self.lo + 1023) // 1024, 3))

    def test_card_read_seek_and_open(self):
        txt = self.report(self.booted())
        self.assertIn('card: BENCH.WAV, 262144 bytes', txt)
        self.assertIn('straight read: 262144 bytes', txt)
        self.assertIn('each 4 KB (64)', txt)
        self.assertIn('random 4 KB (seek + read) (64)', txt)
        self.assertIn('open, found (2)', txt)                            # 1.wav and 7.wav
        self.assertIn('open, missing (62)', txt)

    def test_no_large_file_says_so(self):
        e = self.booted()
        for f in ('bench.wav', 'banks/00/samples/1.wav'):                  # the large file and the fallback
            del e.sd[f]
        txt = self.report(e)
        self.assertIn('card: no BENCH.WAV or SAMPLES/1.wav to read', txt)
        self.assertIn('"vintage-bbd": true', e.sd_written['system/device.json'].decode(), 'settings still saved')

    def test_saves_and_loads_timed(self):
        e = self.booted()
        for f in ('kit_save', 'pat_save', 'switch_bank', 'load_samples'):
            e.stub(self.s4.fn[f], lambda *a: 1)
        e.call(self.s['pk_bench_kit_save'], 0, 3, max_insns=5_000_000)
        e.call(self.s['pk_bench_kit_save'], 0, 4, max_insns=5_000_000)
        self.assertEqual(e.call(self.s['pk_bench_pat_save'], 0, 0, 2, max_insns=5_000_000), 1, 'result passed on')
        e.call(self.s['pk_bench_switch_bank'], 5, max_insns=5_000_000)
        txt = self.report(e)
        self.assertIn('kit save: 2 times', txt)
        self.assertIn('pattern save: 1 times', txt)
        self.assertIn('bank switch: 1 times', txt)

    def test_main_loop_gaps(self):
        e = self.booted()
        e.stub(self.s4.fn['key_poll'], lambda *a: 0)
        tick = self.s4.g['hal_tick']
        for t in (1000, 1001, 1003, 1003, 1150):                         # gaps 1, 2, 0, 147
            e.w32(tick, t)
            e.call(self.s['pk_bench_loop'], max_insns=1_000_000)
        txt = self.report(e)
        self.assertIn('main loop: 5 passes', txt)
        self.assertIn('longest gap 147 ms (at 1 s)', txt)
        self.assertIn('<=1: 2 <=2: 1 <=5: 0', txt)
        self.assertIn('<=200: 1 >200: 0', txt)

    def test_hooks_are_first_in_their_chains(self):
        """Built with a mod that also hooks the saves (eight-lanes, the host's sidecars), the
        site's guard jumps to the bench first, so it times the whole chain."""
        import capstone
        from perkons.patch import thumb_bl_target
        img, p = build_patched(Image.load(require_image('v1.3.0')), ['card_bench', 'eight_lanes'], self.tmp + '/el')
        s, seg = p.cave_symbols['m4host'], img.segment('m4')
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        for site, want in (('patpage.call_save_a', 'pk_bench_pat_save'), ('kits.save.08105c84', 'pk_bench_kit_save')):
            with self.subTest(site=site):
                a = self.s4.site(site)['addr']
                guard = thumb_bl_target(a, bytes(seg.data[a - seg.addr:a - seg.addr + 4]))
                code = bytes(seg.data[guard - seg.addr:guard - seg.addr + 32])
                b = next(i for i in md.disasm(code, guard) if i.mnemonic == 'b.w')   # booted: the first link
                self.assertEqual(int(b.op_str.lstrip('#'), 16), s[want] & ~1)


if __name__ == '__main__':
    unittest.main()
