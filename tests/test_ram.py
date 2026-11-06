"""RAM areas (MAIN / VOICE / STORE), the patcher's RAM ledger, the emulator's RAM watch and
the Mod Matrix's sums."""
import os
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import catalog, ram
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.patch import Patcher, PatchError

SYMS = {'m7': Symbols(SYMBOLS_V130), 'm4': Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))}


class TestAreas(unittest.TestCase):
    def test_v130_areas(self):
        a = ram.areas(SYMS)
        self.assertEqual(a['main'], (0x1002ff00, 0x10040000))
        self.assertEqual(a['voice'], (0x2000c000, 0x2001f000))
        self.assertEqual(a['store'], (0x24004000, 0x2401fe00))

    def test_check(self):
        lo, hi = ram.areas(SYMS)['voice']
        self.assertIsNone(ram.check({'voice': {'a': (lo, 0x100), 'b': (lo + 0x100, 0x100)}}, SYMS))
        self.assertIn('overlap', ram.check({'voice': {'a': (lo, 0x100), 'b': (lo + 0xff, 4)}}, SYMS))
        self.assertIn('outside', ram.check({'voice': {'a': (hi - 4, 8)}}, SYMS))
        self.assertIn('out of memory in MAIN', ram.check({'main': {'a': (None, 0x10000), 'b': (None, 0x200)}}, SYMS))


class TestBlocks(unittest.TestCase):
    """The meters draw whole physical blocks: the firmware's ranges and the mods' area."""

    def test_v130_blocks(self):
        b = ram.blocks(SYMS)
        self.assertEqual({a: (v['name'], v['start'], v['end']) for a, v in b.items()},
                         {'main': ('D2 SRAM', 0x10000000, 0x10048000), 'voice': ('M7 DTCM', 0x20000000, 0x20020000),
                          'store': ('AXI SRAM', 0x24000000, 0x24080000)})
        stock = {a: [(o, s, e) for o, s, e in v['ranges'] if o != 'mods'] for a, v in b.items()}
        self.assertIn(('.bss', 0x10001c60, 0x1002efac), stock['main'])
        self.assertIn(('default custom samples', 0x2401fe00, 0x24080000), stock['store'])
        self.assertIn(('stack', 0x2001f000, 0x20020000), stock['voice'])

    def test_mods_range_is_each_area(self):
        a = ram.areas(SYMS)
        for area, v in ram.blocks(SYMS).items():
            mods = [(s, e) for o, s, e in v['ranges'] if o == 'mods']
            self.assertEqual(mods, [a[area]], area)

    def test_the_stock_sample_pool_is_inside_its_range(self):
        g, c = SYMS['m4'].g, SYMS['m4'].const
        _, lo, hi = next(r for r in ram.blocks(SYMS)['store']['ranges'] if r[0] == 'default custom samples')
        self.assertLessEqual(lo, g['sample_table'])
        self.assertEqual(g['sample_data'] + c['sample_data_size'], hi)


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.p = Patcher(Image.load(require_image('v1.3.0')))
        self.p.symbols = SYMS

    def test_unknown_area_rejected(self):
        with self.assertRaises(PatchError):
            self.p.ram_use('dtcm', 'x', 4)

    def test_finish_refuses_a_build_that_does_not_fit(self):
        self.p.ram_use('store', 'big', 0x20000)
        with self.assertRaises(PatchError):
            self.p.finish()

    def test_takeover(self):
        self.p.ram_takeover('store', 'default custom samples', 'step-sampler')
        self.p.ram_takeover('store', 'default custom samples', 'step-sampler')      # again: fine
        self.assertEqual(self.p.ram_takeovers, {'store': {'default custom samples': 'step-sampler'}})
        with self.assertRaises(PatchError):
            self.p.ram_takeover('store', 'default custom samples', 'another')         # one owner
        with self.assertRaises(PatchError):
            self.p.ram_takeover('store', 'mods', 'x')                                 # not a stock range
        self.p.finish()

    def test_borrow(self):
        self.p.ram_borrow('store', 'json_buf', 'a')
        self.p.ram_borrow('store', 'json_buf', 'b')                                 # shared: fine
        self.assertEqual(self.p.ram_borrows, {'store': {'json_buf': ['a', 'b']}})
        with self.assertRaises(PatchError):
            self.p.ram_borrow('store', 'sample_table', 'a')                         # not borrowable

    def test_a_fixed_range_over_linked_variables_is_refused(self):
        lo = ram.areas(SYMS)['main'][0]
        self.p.ram_use('main', 'src/m4/host/pk_host.c:.bss', 0x40, lo)              # as the host records it
        self.p.ram_use('main', 'my_buffer', 0x10, lo + 0x20)
        with self.assertRaisesRegex(PatchError, 'overlap'):
            self.p.finish()

    def test_finish_accepts_a_build_that_fits(self):
        self.p.ram_use('store', 'small', 0x100)
        self.p.finish()


WATCHED_C = r"""
#include <stdint.h>
uint32_t pk_t_var[4];                       /* linked: recorded by the host */
void pk_t_linked(void) { pk_t_var[3] = 1; }
void pk_t_write(uint32_t a) { *(volatile uint32_t *)(uintptr_t)a = 1; }
"""


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestWatch(unittest.TestCase):
    """The emulator lets a build's code write only the RAM its patches recorded."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix='pk-ramwatch-')
        cls.builds = {}
        for borrow in (False, True):
            # different code too: a build's RAM map is found by its image (the same image, the
            # same map)
            src = os.path.join(cls.dir, f'watched{int(borrow)}.c')
            with open(src, 'w') as f:
                f.write(WATCHED_C + ('void pk_t_borrows(void) {}\n' if borrow else ''))
            p = Patcher(Image.load(require_image('v1.3.0')))
            p.symbols = SYMS
            p.build_dir = os.path.join(cls.dir, f'b{int(borrow)}')
            from perkons import m4host
            m4host.host(p).add([src], [cls.dir])
            if borrow:
                p.ram_borrow('store', 'json_buf', 'watched')
            cls.builds[borrow] = (p.result(), p.cave_symbols['m4host'])

    def rig(self, borrow=False):
        from perkons.rig import M4Rig
        img, cave = self.builds[borrow]
        return M4Rig(img, cave), cave

    def test_recorded_ram_and_firmware_state_are_fine(self):
        r, cave = self.rig()
        self.assertTrue(r.e.ram_map)
        r.e.call(cave['pk_t_linked'])
        self.assertEqual(r.e.r32(cave['pk_t_var'] + 12), 1)
        seq = r.e.r32(SYMS['m4'].g['seq_ptr'])
        r.e.call(cave['pk_t_write'], SYMS['m4'].g['seq_ptr'])                  # the firmware's own state
        r.e.w32(SYMS['m4'].g['seq_ptr'], seq)

    def test_unrecorded_area_ram_is_refused(self):
        from perkons.emu import RamViolation
        r, cave = self.rig()
        lo, hi = ram.areas(SYMS)['main']
        with self.assertRaisesRegex(RamViolation, f'{hi - 4:08x}.*not in any RAM the build recorded'):
            r.e.call(cave['pk_t_write'], hi - 4)

    def test_guarded_firmware_ram_needs_a_borrow_or_takeover(self):
        from perkons.emu import RamViolation
        r, cave = self.rig()
        with self.assertRaisesRegex(RamViolation, "file system \\+ JSON"):
            r.e.call(cave['pk_t_write'], SYMS['m4'].g['json_buf'])
        r, cave = self.rig()
        with self.assertRaisesRegex(RamViolation, 'default custom samples'):
            r.e.call(cave['pk_t_write'], SYMS['m4'].g['sample_table'])
        r, cave = self.rig(borrow=True)
        r.e.call(cave['pk_t_write'], SYMS['m4'].g['json_buf'])


class TestSums(unittest.TestCase):
    MEM = {'areas': {'main': {'size': 100}, 'voice': {'size': 100}, 'store': {'size': 100}},
           'options': {'a': {'main': {'shared': 60, 'a': 10}}, 'b': {'main': {'shared': 60, 'b': 20}},
                       'c': {'main': {'c': 50}}}}

    def test_shared_owners_count_once(self):
        self.assertEqual(catalog.ram_used(['a', 'b'], self.MEM), {'main': 90, 'voice': 0, 'store': 0})
        catalog.check_memory(['a', 'b'], self.MEM)

    def test_over_is_refused(self):
        with self.assertRaises(catalog.CatalogError):
            catalog.check_memory(['a', 'c'], self.MEM)

    def test_with_requires(self):
        by_id = {'x': {'requires': ['y']}, 'y': {'requires': ['z']}, 'z': {'requires': []}}
        self.assertEqual(catalog.with_requires(['x'], by_id), ['x', 'y', 'z'])
