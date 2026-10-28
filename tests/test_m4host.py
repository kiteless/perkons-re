"""M4 host (tools/perkons/m4host.py): config toggles, device.json keys, boot, FX chain.
Needs arm-none-eabi-gcc."""
import json
import os
import shutil
import struct
import tempfile
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import m4host
from perkons.emu import M4Emu, M4FX, Symbols
from perkons.fwimage import Image
from perkons.patch import Patcher

DEMO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'm4host_demo.c')


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestM4Host(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.s4, cls.s7 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json')), Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-host-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, fx=False, toggles=((46, 'demo-a', 'pk_demo_a'), (47, 'demo-b', 'pk_demo_b'))):
        p = Patcher(self.stock)
        p.symbols = {'m7': self.s7, 'm4': self.s4}
        p.build_dir = tempfile.mkdtemp(dir=self.tmp)
        h = m4host.host(p)
        h.add([DEMO], init='pk_demo_init')
        for t in toggles:
            h.toggle(*t)
        if fx:
            h.fx()
        return p.result(), p.cave_symbols['m4host']

    def emu(self, img, sd=None):
        return M4Emu(img.segment('m4').data, self.s4, img.segment('m7').data, sd=sd or {}).boot()

    def test_boot_zeroes_ram_then_inits(self):
        img, s = self.build()
        e = self.emu(img)
        e.w8(s['pk_demo_a'], 0x55)                                 # garbage before boot
        e.call(s['pk4_boot'], max_insns=50_000_000)
        self.assertEqual(e.r8(s['pk_demo_a']), 0)
        self.assertEqual(e.r32(s['pk_demo_inited']), 0x600d)

    def test_config_toggles_dirty_flag_and_leds(self):
        img, s = self.build()
        e = self.emu(img)
        e.call(s['pk4_boot'], max_insns=50_000_000)
        leds = {}
        e.stub(self.s4.fn['set_led'], lambda emu, k, lvl, *_: leds.__setitem__(k, lvl))
        ev = self.s4.mem['bss_end']
        for key, var in ((46, 'pk_demo_a'), (47, 'pk_demo_b')):
            e.w8(self.s4.g['cfg_dirty'], 0)
            e.uc.mem_write(ev, bytes([key, 0x11]))
            self.assertEqual(e.call(s['pk4_cfg_event'], ev), 1)
            self.assertEqual(e.r8(s[var]), 1)
            self.assertEqual(e.r8(self.s4.g['cfg_dirty']), 1, 'marked for saving')
        e.call(s['pk4_cfg_render'], 0, 0, 0, 0)
        self.assertEqual((leds.get(46), leds.get(47)), (0x80, 0x80))

    def test_settings_load_from_mods_json(self):
        img, s = self.build()
        sd = {'system/device.json': b'{"vintage-bbd": true}', 'system/mods.json': b'{"demo-a": true, "demo-b": false}'}
        e = self.emu(img, sd)
        e.call(s['pk4_boot'], max_insns=50_000_000)
        self.assertEqual((e.r8(s['pk_demo_a']), e.r8(s['pk_demo_b'])), (1, 0))
        self.assertEqual(e.r8(self.s4.g['device_config'] + 7), 1, 'stock keys still load')

    def test_mod_keys_in_device_json_are_ignored(self):
        img, s = self.build()
        e = self.emu(img, {'system/device.json': b'{"demo-a": true}'})
        e.call(s['pk4_boot'], max_insns=50_000_000)
        self.assertEqual(e.r8(s['pk_demo_a']), 0)

    def test_saving_writes_mods_json_and_a_stock_device_json(self):
        img, s = self.build()
        e = self.emu(img, {'system/device.json': b'{"vintage-bbd": true}'})
        e.call(s['pk4_boot'], max_insns=50_000_000)
        e.w8(s['pk_demo_b'], 1)
        e.call(s['pk4_device_json_save'], max_insns=50_000_000)
        mods = json.loads(e.sd_written['system/mods.json'])
        self.assertEqual(mods, {'demo-a': False, 'demo-b': True})
        dev = json.loads(e.sd_written['system/device.json'])
        self.assertNotIn('demo-a', dev)
        self.assertTrue(dev['vintage-bbd'])

    def test_device_json_schema_untouched(self):
        img, _ = self.build()
        seg, stock = img.segment('m4'), self.stock.segment('m4')
        for site in ('device_schema.load_literal', 'device_schema.create_literal', 'device_schema.save_literal'):
            a = self.s4.site(site)['addr'] - seg.addr
            self.assertEqual(seg.data[a:a + 4], stock.data[a:a + 4], site)

    def test_heap_capped_below_patch_ram(self):
        img, s = self.build()
        seg = img.segment('m4')
        lit = self.s4.site('sbrk.limit_literal')['addr']
        self.assertEqual(struct.unpack_from('<I', seg.data, lit - seg.addr)[0] - 0x400, m4host.RAM_BASE)
        self.assertTrue(all(m4host.RAM_BASE <= s[v] < m4host.RAM_END for v in ('pk_demo_a', 'pk_demo_inited')))

    def test_clashing_toggles_refused(self):
        with self.assertRaises(m4host.HostError):
            self.build(toggles=((46, 'demo-a', 'pk_demo_a'), (46, 'demo-b', 'pk_demo_b')))

    def test_fx_without_engine_is_stock(self):
        img, s = self.build(fx=True)
        send = [int(8000 * ((i // 40) % 2 * 2 - 1)) if i < 2000 else 0 for i in range(20000)]
        out = []
        for image, pre in ((self.stock, None), (img, lambda e: e.call(s['pk4_boot'], max_insns=50_000_000))):
            fx = M4FX(image.segment('m4').data, self.s4, image.segment('m7').data).boot(pre)
            fx.knobs = dict(time=.4, feedback=.6, rate=.3, depth=.3)
            out.append(fx.process(send))
        self.assertEqual(out[0], out[1])
        self.assertGreater(max(map(abs, out[1])), 300)
