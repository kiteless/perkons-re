"""Controls: the button and knob combinations options list, and the checks made with them
(tools/perkons/controls.py)."""
import unittest

from perkons import catalog, controls
from perkons.controls import ControlsError, check_clashes, stock_changes, validate


def opt(title, *ctl):
    return {'title': title, 'controls': list(ctl)}


class TestControls(unittest.TestCase):
    def test_the_same_combination_is_the_same_buttons_on_overlapping_pages(self):
        a = {'combo': 'KIT + SYNC', 'does': 'x'}
        self.assertTrue(controls.same(a, {'combo': 'SYNC + KIT (HOLD 0.5 S)', 'does': 'y'}), 'order, gesture aside')
        self.assertTrue(controls.same(a, {'combo': 'kit+sync', 'page': 'MAIN', 'does': 'y'}), 'ANY overlaps MAIN')
        self.assertFalse(controls.same({'combo': 'KIT + SYNC', 'page': 'KIT', 'does': 'x'},
                                       {'combo': 'KIT + SYNC', 'page': 'MAIN', 'does': 'y'}), 'other pages')
        self.assertFalse(controls.same(a, {'combo': 'KIT + SYNC + TRIGGER', 'does': 'y'}), 'more buttons: another')

    def test_two_options_with_the_same_combination_clash(self):
        a = opt('A', {'combo': 'KIT + SYNC', 'does': 'x'})
        b = opt('B', {'combo': 'SYNC + KIT (HOLD)', 'page': 'MAIN', 'does': 'y'})
        self.assertEqual(check_clashes([a, b]), 'B and A both use SYNC + KIT (HOLD) (MAIN)')
        self.assertIsNone(check_clashes([a, opt('C', {'combo': 'KIT + SYNC', 'does': 'y', 'adds': True})]),
                          'only adding to stock: no clash')
        self.assertIsNone(check_clashes([a, opt('D'), {'title': 'E', 'controls': None}]), 'none / not listed')

    def test_the_platforms_combinations_are_taken(self):
        self.assertIn('the platform', check_clashes([opt('A', {'combo': 'MOD + KIT', 'does': 'x'})]) or '')

    def test_stock_changes_are_whole_combinations(self):
        shift_knob = {'combo': 'SHIFT + KNOB', 'page': 'MAIN', 'does': 'x'}
        self.assertEqual([s['combo'] for _, s in stock_changes(opt('A', shift_knob))], ['SHIFT + KNOB'])
        self.assertEqual(stock_changes(opt('A', {'combo': 'TRIGGER + LFO RATE', 'does': 'x'})), [],
                         'a stock button in a new combination: not a change')
        self.assertEqual(stock_changes(opt('A', dict(shift_knob, adds=True))), [], 'stock\'s action kept')
        self.assertEqual(stock_changes(opt('A', dict(shift_knob, page='SAMPLES'))), [], 'a mod\'s own page')

    def test_validate(self):
        self.assertIsNone(validate(None), 'optional')
        validate([{'combo': 'ROW 3 STEP 15', 'page': 'CONFIG', 'does': 'x'}, {'combo': 'STEP', 'page': 'X', 'does': 'y'}])
        for bad in ({'combo': 'KIT + SNYC', 'does': 'x'},                       # not a control
                    {'combo': 'ROW 3 STEP 15', 'does': 'x'},                      # a config key off the config page
                    {'combo': 'KIT + SYNC'},                                     # what it does
                    {'combo': 'KIT + SYNC', 'does': 'x', 'risk': 1}):            # unknown field
            with self.subTest(bad=bad), self.assertRaises(ControlsError):
                validate([bad])
        with self.assertRaises(ControlsError):
            validate({'combo': 'KIT'})

    def test_stock_and_platform_lists_are_well_formed(self):
        validate(controls.STOCK)
        validate(controls.PLATFORM)

    def test_the_mods_on_disk(self):
        """Every mod's controls check out, no two clash, and only the known ones change stock."""
        opts = [o for o in catalog.options() if o['controls'] is not None]
        if not opts:
            self.skipTest('no mods with controls on disk (PERKONS_MODS)')
        self.assertIsNone(check_clashes(opts))
        changes = {o['id'].split(':')[-1]: sorted(s['combo'] for _, s in stock_changes(o)) for o in opts}
        for oid, want in (('fx-freeze', ['FX SWITCH']),
                          ('per-track-lfo', []), ('voice-step-sampler', [])):
            if oid in changes:
                self.assertEqual(changes[oid], want, oid)

    def test_the_doc_tables_are_current(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, controls.DOC)) as f:
            self.assertIn(controls.tables(), f.read(), 'run: cd tools && python3 -m perkons.controls')
