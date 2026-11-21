"""voice-map on the M4: each kit's engines (kit sidecar record VMAP), the engine page (a page
of its own: KIT + MOD), the map sent to the M7 on the trigger stream."""
import os
import shutil
import struct
import tempfile
import unittest

from fixtures import build_patched, require_image
from perkons.fwimage import Image
from perkons.mods import load_patch
from perkons.rig import M4Rig

SHIFT, KIT, MOD, TRIG1 = 0x47, 0x41, 0x43, 0x4b
MAIN_MODE, MOD_MODE, KIT_MODE, CONFIG_MODE = 0, 3, 5, 7
ENGINES_PAGE = 17                             # PK_PAGE_ENGINES: the first page after the stock 0-16
MSG = 4                                       # PK_MSG_VOICE_MAP
_images = {}


def image(patches):
    if patches not in _images:
        try:
            load_patch('voice_zibens')
        except ImportError:
            raise unittest.SkipTest('an extra engine to choose: voice-zibens (perkons-re-mods, PERKONS_MODS)')
        img, p = build_patched(Image.load(require_image('v1.3.0')), list(patches), tempfile.mkdtemp())
        _images[patches] = (img, p.cave_symbols['m4host'])
    return _images[patches]


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestEnginePage(unittest.TestCase):
    patches = ('voice_map', 'voice_zibens')

    def rig(self, sd=None):
        img, cave = image(self.patches)
        r = M4Rig(img, cave, sd=sd if sd is not None else {'BANKS/00/KITS/00.KIT': b''})
        seg = img.segment('m4')
        site = r.sym.site('keys.handler_lit')['addr']
        r.handler = struct.unpack_from('<I', seg.data, site - seg.addr)[0] & ~1     # the chained key handler
        r.e.sent(2)
        return r

    def key(self, r, k, down):
        r.event(k, down, handler=r.handler)

    def press(self, r, k):
        self.key(r, k, True)
        self.key(r, k, False)

    def apply(self, r):
        r.e.call(r.sym.fn['apply_mode'], max_insns=5_000_000)

    def open_page(self, r, from_mode=KIT_MODE):
        r.set_mode(from_mode)
        self.key(r, KIT, True)
        self.apply(r)                                 # KIT changes page before MOD comes
        self.press(r, MOD)
        self.key(r, KIT, False)
        self.apply(r)
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def maps(self, r):
        return [list(p) for t, p in r.e.sent(2) if t == MSG]

    def leds(self, r):
        r.leds.clear()
        r.e.call(r.sym.fn['ui_update'], max_insns=20_000_000)
        return [[r.leds.get(16 * v + e, 0) for e in range(16)] for v in range(4)]

    def test_defaults_and_leds(self):
        r = self.rig()
        self.open_page(r)
        rows = self.leds(r)
        for v in range(4):
            self.assertEqual(rows[v][v], 0x80, f'voice {v + 1}: engine {v + 1}')
            self.assertEqual([x for e, x in enumerate(rows[v][:5]) if e != v], [0x10] * 4)   # 5 engines
            self.assertEqual(rows[v][5:], [0] * 11)

    def test_a_step_chooses_and_sends(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 2 + 4)                     # voice 3 -> engine 5 (zibens)
        self.assertEqual(self.maps(r), [[0, 1, 4, 3]])
        self.press(r, 16 * 0 + 7)                     # no engine 8: nothing
        self.assertEqual(self.maps(r), [])
        self.assertEqual(self.leds(r)[2][4], 0x80)

    def test_opens_from_any_page(self):
        for mode in (MAIN_MODE, KIT_MODE, MOD_MODE, CONFIG_MODE):
            with self.subTest(page=mode):
                self.open_page(self.rig(), from_mode=mode)

    def test_trigger_keys_play_the_voices(self):
        r = self.rig()
        self.open_page(r)
        played = []
        r.e.stub(r.sym.fn['voice_play'], lambda e, voice, on, *a: played.append((voice, on)))
        self.press(r, TRIG1 + 2)
        self.assertEqual(played, [(2, 1), (2, 0)], 'voice 3 played, as on the config page')
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def test_the_panel_switches_work_on_the_page(self):
        from perkons.rig import EVT
        r = self.rig()
        self.open_page(r)
        vs = r.voice_state(1)
        for which, pos in ((0, 2), (1, 1), (2, 2)):             # ALGO, MODE, filter: switch events
            r.e.uc.mem_write(EVT, bytes([3 + which, 0x15]) + struct.pack('<H', pos) + bytes(4))
            r.e.call(r.key_handler, EVT, max_insns=50_000_000)
        self.assertEqual([struct.unpack('<H', bytes(r.e.uc.mem_read(vs + 0x50 + 2 * s, 2)))[0] for s in (8, 9)],
                         [2, 1], 'voice 2 ALGO / MODE')
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def test_leaving_keeps_it_in_the_kit(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 1 + 3)                     # voice 2 -> engine 4
        self.press(r, MOD)                            # a page button leaves (saves: changed)
        self.apply(r)
        self.assertEqual(r.mode(), MOD_MODE)
        kix = r.e.sd_written['banks/00/kits/00.kix']
        self.assertEqual(kix, b'PKX1VMAP' + struct.pack('<IH', 2, 0x3230))

    def test_a_long_hold_stays_on_the_page(self):
        r = self.rig()
        r.set_mode(MAIN_MODE)
        self.key(r, KIT, True)
        self.apply(r)
        self.press(r, MOD)
        self.apply(r)
        r.e.stub(r.sym.fn['key_held_ms'], lambda *a: 1000)    # stock: a long hold's release goes to MAIN
        self.key(r, KIT, False)
        self.apply(r)
        self.assertEqual(r.mode(), ENGINES_PAGE)

    def test_leaving_unchanged_writes_nothing(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, KIT)
        self.apply(r)
        self.assertEqual(r.mode(), KIT_MODE)
        self.assertNotIn('banks/00/kits/00.kix', r.e.sd_written)

    def test_kit_load_sends_its_engines(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 3 + 0)                     # voice 4 -> engine 1
        self.press(r, MOD)
        self.apply(r)
        r.e.sent(2)
        r.e.call(r.cave['pk_vm_kit_load'], 0, max_insns=50_000_000)
        self.assertEqual(self.maps(r), [[0, 1, 2, 0]])
        r.e.call(r.cave['pk_vm_kit_load'], 1, max_insns=50_000_000)
        self.assertEqual(self.maps(r), [[0, 1, 2, 3]], 'a kit without a record: stock engines')

    def test_bank_load_reads_the_kits(self):
        rec = b'PKX1VMAP' + struct.pack('<IH', 2, 0x0123)
        r = self.rig(sd={'BANKS/02/KITS/05.KIX': rec, 'BANKS/02/00.PAT': b''})
        r.e.call(r.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        r.e.call(r.cave['pk_vm_kit_load'], 5, max_insns=50_000_000)
        self.assertEqual(self.maps(r), [[3, 2, 1, 0]])

    def test_shift_mod_is_the_stock_config_menu(self):
        r = self.rig()
        r.set_mode(KIT_MODE)
        self.key(r, SHIFT, True)
        self.apply(r)
        self.press(r, MOD)
        self.key(r, SHIFT, False)
        self.apply(r)
        self.assertEqual(r.mode(), CONFIG_MODE)
        self.press(r, 16 * 2 + 4)
        self.assertEqual(self.maps(r), [])

    def test_kit_save_stores_the_engines_playing(self):
        r = self.rig()
        self.open_page(r)
        self.press(r, 16 * 0 + 4)                     # voice 1 -> zibens
        r.e.stub(r.sym.fn['kit_save'], lambda *a: 0)
        r.e.call(r.cave['pk4_store_kit_save'], 0, 9, max_insns=50_000_000)   # KIT + REC into kit 10
        self.assertEqual(r.e.sd_written['banks/00/kits/09.kix'], b'PKX1VMAP' + struct.pack('<IH', 2, 0x3214))


_slot_images = {}
SLOT_OWNER = 'src/m4/voicemap/voice_map_m4.c:.pk_axi.kit_slots'


def slot_image(kit_bytes):
    """voice_map + voice_zibens, zibens declaring a kit record of kit_bytes: the kit slots."""
    if kit_bytes not in _slot_images:
        from fixtures import SYMBOLS_V130
        from perkons import voicemap
        from perkons.emu import Symbols
        from perkons.patch import Patcher
        try:
            zibens = load_patch('voice_zibens')
        except ImportError:
            raise unittest.SkipTest('an extra engine: voice-zibens (perkons-re-mods, PERKONS_MODS)')
        p = Patcher(Image.load(require_image('v1.3.0')))
        p.symbols = {'m7': Symbols(SYMBOLS_V130), 'm4': Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))}
        p.build_dir = tempfile.mkdtemp()
        load_patch('voice_map').apply(p)
        zibens.apply(p)
        voicemap.engines(p)['zibens']['kit_bytes'] = kit_bytes
        img = p.result()
        _slot_images[kit_bytes] = (img, p.cave_symbols['m4host'], p.ram)
    return _slot_images[kit_bytes]


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestKitSlots(TestEnginePage):
    """The kit slots: one table for every engine's per-kit sound, a slot per kit and voice
    owned by the engine that voice has in the kit (and the engine page as before)."""
    ZIBENS = 4                                    # engine 5: the nibble value

    def rig(self, sd=None):
        img, cave, _ = slot_image(10)
        r = M4Rig(img, cave, sd=sd if sd is not None else {'BANKS/00/KITS/00.KIT': b''})
        seg = img.segment('m4')
        site = r.sym.site('keys.handler_lit')['addr']
        r.handler = struct.unpack_from('<I', seg.data, site - seg.addr)[0] & ~1
        r.e.sent(2)
        return r

    def slot(self, r, kit, v, engine=ZIBENS, size=10):
        return r.e.call(r.cave['pk_vm_kit_slot'], kit, v, engine, size, max_insns=100_000)

    def choose(self, r, v, engine):
        self.open_page(r)
        self.press(r, 16 * v + engine)
        self.press(r, MOD)                            # leave: into the kit (and its file)
        self.apply(r)

    def test_size_is_the_largest_record_in_words(self):
        _, _, ram = slot_image(10)
        self.assertEqual(ram['store'][SLOT_OWNER][1], 64 * 4 * 12)

    def test_a_slot_belongs_to_the_voice_s_engine(self):
        r = self.rig()
        self.assertEqual(self.slot(r, 0, 2), 0, 'voice 3 runs a stock engine')
        self.choose(r, 2, self.ZIBENS)
        self.assertNotEqual(self.slot(r, 0, 2), 0)
        self.assertEqual(self.slot(r, 0, 1), 0, 'voice 2 is still stock')
        self.assertEqual(self.slot(r, 1, 2), 0, 'kit 2 still has the stock engine')
        self.assertEqual(self.slot(r, 0, 2, size=13), 0, 'more than the slot holds')
        self.assertEqual(self.slot(r, 0, 3) or self.slot(r, 0, 0), 0)
        self.assertEqual(r.e.call(r.cave['pk_vm_kit_engine'], 0, 2), self.ZIBENS)

    def test_changing_engine_empties_the_slot(self):
        r = self.rig()
        self.choose(r, 2, self.ZIBENS)
        a = self.slot(r, 0, 2)
        r.e.uc.mem_write(a, bytes(range(1, 13)))
        self.choose(r, 0, 1)                          # another voice: kept
        self.assertEqual(bytes(r.e.uc.mem_read(a, 12)), bytes(range(1, 13)))
        self.choose(r, 2, 0)                          # voice 3 -> engine 1
        self.choose(r, 2, self.ZIBENS)                # and back: empty
        self.assertEqual(bytes(r.e.uc.mem_read(self.slot(r, 0, 2), 12)), bytes(12))

    def test_kit_save_into_another_kit_empties_the_changed_voices(self):
        r = self.rig()
        self.choose(r, 2, self.ZIBENS)
        r.e.stub(r.sym.fn['kit_save'], lambda *a: 0)
        r.e.call(r.cave['pk4_store_kit_save'], 0, 9, max_insns=50_000_000)
        a = self.slot(r, 9, 2)
        self.assertNotEqual(a, 0)
        r.e.uc.mem_write(a, b'\x55' * 12)
        self.choose(r, 2, 1)                          # voice 3 -> engine 2, then saved into kit 10
        r.e.call(r.cave['pk4_store_kit_save'], 0, 9, max_insns=50_000_000)
        self.choose(r, 2, self.ZIBENS)
        r.e.call(r.cave['pk4_store_kit_save'], 0, 9, max_insns=50_000_000)
        self.assertEqual(bytes(r.e.uc.mem_read(self.slot(r, 9, 2), 12)), bytes(12))

    def test_bank_load_empties_the_slots(self):
        rec = b'PKX1VMAP' + struct.pack('<IH', 2, 0x4210)    # voice 4 runs zibens in kit 6
        r = self.rig(sd={'BANKS/02/KITS/05.KIX': rec, 'BANKS/02/00.PAT': b''})
        r.e.call(r.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        a = self.slot(r, 5, 3)
        self.assertNotEqual(a, 0)
        r.e.uc.mem_write(a, b'\x77' * 12)
        r.e.call(r.cave['pk4_store_bank_load'], 2, max_insns=900_000_000)
        self.assertEqual(bytes(r.e.uc.mem_read(a, 12)), bytes(12))


class TestKitBytes(unittest.TestCase):
    def p(self, **sizes):
        class P:
            shared = {}
        p = P()
        from perkons import voicemap as vmc
        for name, n in sizes.items():
            vmc.engines(p)[name] = {'sources': [], 'build': f'pk_{name}_build', 'kit_bytes': n}
        return vmc.kit_bytes(p)

    def test_the_largest_in_words(self):
        self.assertEqual(self.p(a=23, b=40, c=6), 40)
        self.assertEqual(self.p(a=23, c=6), 24)
        self.assertEqual(self.p(), 0)
        self.assertEqual(self.p(a=None), 0)


if __name__ == '__main__':
    unittest.main()


class TestSlots(unittest.TestCase):
    """Extra engines take the slot they're installed in (the engine page's column)."""

    def p(self, **slots):
        class P:
            shared = {}
        p = P()
        from perkons import voicemap as vmc
        for name, slot in slots.items():
            vmc.engines(p)[name] = {'sources': [], 'build': f'pk_{name}_build', 'slot': slot}
        return p, vmc

    def test_slots_and_free_ones(self):
        p, vmc = self.p(b=7, a=None, c=None)
        self.assertEqual({k: n for k, (n, _) in vmc.numbered(p).items()}, {5: 'a', 6: 'c', 7: 'b'})
        self.assertEqual(vmc.engine_names(p)[5:], ['a', 'c', 'b'])

    def test_a_gap_is_an_empty_column(self):
        p, vmc = self.p(x=6)
        self.assertEqual(vmc.engine_names(p)[5:], ['', 'x'])

    def test_clashes_and_range(self):
        p, vmc = self.p(a=5, b=5)
        with self.assertRaises(ValueError):
            vmc.numbered(p)
        p, vmc = self.p(a=17)
        with self.assertRaises(ValueError):
            vmc.numbered(p)

    def test_the_last_column(self):
        p, vmc = self.p(a=16)
        self.assertEqual(vmc.engine_names(p)[16], 'a')
