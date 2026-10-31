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

    def test_axi_variables_in_the_gap_and_zeroed_at_boot(self):
        img, s = self.build()
        lo, hi = m4host.axi_gap(self.s4)
        self.assertTrue(all(lo <= s[v] < hi for v in ('pk_demo_b', 'pk_demo_axi_words')))
        self.assertEqual(img.segment('m4').data, self.build()[0].segment('m4').data, 'nothing loaded into AXI')
        e = self.emu(img)
        e.uc.mem_write(s['pk_demo_axi_words'], b'\x55' * 16)
        e.call(s['pk4_boot'], max_insns=50_000_000)
        self.assertEqual(bytes(e.uc.mem_read(s['pk_demo_axi_words'], 16)), bytes(16))

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

    def test_settings_load_and_save_in_mods_json(self):
        p = Patcher(self.stock)
        p.symbols = {'m7': self.s7, 'm4': self.s4}
        p.build_dir = tempfile.mkdtemp(dir=self.tmp)
        h = m4host.host(p)
        h.add([DEMO], init='pk_demo_init')
        h.setting('demo-number', 'pk_demo_a')
        img, s = p.result(), p.cave_symbols['m4host']
        e = self.emu(img, {'system/mods.json': b'{"demo-number": 42}'})
        e.call(s['pk4_boot'], max_insns=50_000_000)
        self.assertEqual(e.r8(s['pk_demo_a']), 42)
        e.w8(s['pk_demo_a'], 7)
        e.call(s['pk4_device_json_save'], max_insns=50_000_000)
        self.assertEqual(json.loads(e.sd_written['system/mods.json']), {'demo-number': 7})

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


CHAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'm4host_chain.c')
SITE = 'fx_lfo.call_led_pwm'


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestChains(unittest.TestCase):
    """Several mods on one hook point: chained in order, stock until boot, events."""

    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.s4, cls.s7 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json')), Symbols(SYMBOLS_V130)
        cls.tmp = tempfile.mkdtemp(prefix='pk-chain-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self, register):
        p = Patcher(self.stock)
        p.symbols = {'m7': self.s7, 'm4': self.s4}
        p.build_dir = tempfile.mkdtemp(dir=self.tmp)
        h = m4host.host(p)
        h.add([CHAIN])
        register(h)
        return p.result(), p.cave_symbols['m4host']

    def run_site(self, img, s, boot=True):
        """The hooked call at SITE, as the firmware makes it: returns (log, pwm reaching stock)."""
        e = M4Emu(img.segment('m4').data, self.s4, img.segment('m7').data, sd={}).boot()
        if boot:
            e.call(s['pk4_boot'], max_insns=50_000_000)
        got = []
        e.stub(self.s4.fn['fx_lfo_led_pwm'], lambda emu, pwm, *_: got.append(pwm))
        site = self.s4.site(SITE)['addr']
        seg = img.segment('m4')
        off = struct.unpack('<HH', seg.data[site - seg.addr:site - seg.addr + 4])
        target = _bl_target(site, *off)
        e.call(target, 100, max_insns=1_000_000)
        n = e.r32(s['pk_chain_n'])
        return [e.r32(s['pk_chain_log'] + 4 * i) for i in range(n)], got

    def test_two_hooks_chain_in_order(self):
        img, s = self.build(lambda h: (h.redirect_call(SITE, 'pk_chain_second', 'b'),
                                       h.redirect_call(SITE, 'pk_chain_first', 'a')))
        self.assertEqual(self.run_site(img, s), ([1, 2], [111]))

    def test_order_overrides_names(self):
        img, s = self.build(lambda h: (h.redirect_call(SITE, 'pk_chain_first', 'a', order=1),
                                       h.redirect_call(SITE, 'pk_chain_second', 'b')))
        self.assertEqual(self.run_site(img, s), ([2, 1], [111]))

    def both(self, h):
        h.redirect_call(SITE, 'pk_chain_first', 'a')
        h.redirect_call(SITE, 'pk_chain_second', 'b')

    def test_stock_until_booted(self):
        img, s = self.build(self.both)
        log, got = self.run_site(img, s, boot=False)
        self.assertEqual(got, [100])                               # straight to stock

    def test_events_call_subscribers_then_stock(self):
        img, s = self.build(lambda h: (self.both(h), h.on('track_clear', 'pk_chain_cleared')))
        e = M4Emu(img.segment('m4').data, self.s4, img.segment('m7').data, sd={}).boot()
        e.call(s['pk4_boot'], max_insns=50_000_000)
        got = []
        e.stub(self.s4.fn['track_clear'], lambda emu, vs, *_: got.append(vs))
        e.call(s['pk_ev_track_clear'], 0x1234, max_insns=1_000_000)
        self.assertEqual((e.r32(s['pk_chain_n']), e.r32(s['pk_chain_log']), got), (1, 3, [0x1234]))

    def test_unregistered_hook_with_pk_next_explained(self):
        with self.assertRaisesRegex(m4host.HostError, 'pk_chain_second'):
            self.build(lambda h: h.redirect_call(SITE, 'pk_chain_first', 'a'))

    def test_unknown_event_refused(self):
        with self.assertRaises(m4host.HostError):
            self.build(lambda h: h.on('no_such_event', 'pk_chain_cleared'))

    def test_same_hook_with_different_next_refused(self):
        def reg(h):
            h.redirect_call(SITE, 'pk_chain_first', 'a')
            h.redirect_call(SITE, 'pk_chain_second', 'b')
            h.redirect_call('event.track_clear.08103738', 'pk_chain_first', 'a elsewhere')
        with self.assertRaises(m4host.HostError):
            self.build(reg)


def _bl_target(src, hw1, hw2):
    s = (hw1 >> 10) & 1
    j1, j2 = (hw2 >> 13) & 1, (hw2 >> 11) & 1
    i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((hw1 & 0x3ff) << 12) | ((hw2 & 0x7ff) << 1)
    if s:
        off -= 1 << 25
    return src + 4 + off


STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'm4host_store.c')


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestStore(unittest.TestCase):
    """Mods' per-pattern records in BANKS/NN/PP.PAX (src/m4/host/pk_host_store.c)."""

    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.s4, cls.s7 = Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json')), Symbols(SYMBOLS_V130)
        p = Patcher(cls.stock)
        p.symbols = {'m7': cls.s7, 'm4': cls.s4}
        cls.tmp = tempfile.mkdtemp(prefix='pk-store-')
        p.build_dir = cls.tmp
        h = m4host.host(p)
        h.add([STORE])
        h.store('pattern', 'DEMO', 'pk_st_save', 'pk_st_load')
        cls.img, cls.s = p.result(), p.cave_symbols['m4host']

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def emu(self, sd=None):
        e = M4Emu(self.img.segment('m4').data, self.s4, self.img.segment('m7').data, sd=sd or {}).boot()
        e.call(self.s['pk4_boot'], max_insns=50_000_000)
        for f in ('pat_save', 'pat_clear', 'bank_prepare'):
            e.stub(self.s4.fn[f], lambda *a: 0)            # the stock part: not under test
        return e

    def test_save_writes_a_record_and_bank_load_hands_it_back(self):
        e = self.emu()
        e.call(self.s['pk4_store_pat_save'], 0, 2, 5, max_insns=5_000_000)
        pax = e.sd_written['banks/02/05.pax']
        self.assertEqual(pax, b'PKX1DEMO' + struct.pack('<I', 2) + bytes([0x25, 0x5a]))
        foreign = b'PKX1' + b'XXXX' + struct.pack('<I', 3) + b'abc' + pax[4:]
        e2 = self.emu({'BANKS/02/05.PAX': pax, 'BANKS/02/06.PAX': foreign})
        e2.call(self.s['pk4_store_bank_load'], 2, max_insns=200_000_000)
        got = [e2.r8(self.s['pk_st_loaded'] + i) for i in (4, 5, 6)]
        self.assertEqual(got, [0xee, 0x25, 0x25])          # none, own, own after a foreign record

    def test_nothing_to_keep_no_file(self):
        e = self.emu({'BANKS/00/09.PAX': b'PKX1old!'})
        e.call(self.s['pk4_store_pat_save'], 0, 0, 9, max_insns=5_000_000)
        self.assertNotIn('banks/00/09.pax', e.sd)

    def test_clear_deletes_and_reports_none(self):
        e = self.emu()
        e.call(self.s['pk4_store_pat_save'], 0, 1, 3, max_insns=5_000_000)
        e.call(self.s['pk4_store_pat_clear'], 1, 3, max_insns=5_000_000)
        self.assertNotIn('banks/01/03.pax', e.sd)
        self.assertEqual(e.r8(self.s['pk_st_loaded'] + 3), 0xee)

    def test_bad_tags_refused(self):
        p = Patcher(self.stock)
        p.symbols = {'m7': self.s7, 'm4': self.s4}
        h = m4host.host(p)
        with self.assertRaises(m4host.HostError):
            h.store('pattern', 'TOOLONG', 'a', 'b')
        h.store('kit', 'ABCD', 'a', 'b')
        with self.assertRaises(m4host.HostError):
            h.store('kit', 'ABCD', 'c', 'd')
