"""RAM areas (MAIN / VOICE / STORE), the patcher's RAM ledger and the Mod Matrix's sums."""
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

    def test_finish_accepts_a_build_that_fits(self):
        self.p.ram_use('store', 'small', 0x100)
        self.p.finish()


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
