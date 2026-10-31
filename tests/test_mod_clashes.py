"""Every mod together, without building: option ids, build codes, requires/conflicts, and
everything the hosts check at registration (config keys, setting names, config messages,
engine names, hook sites) must not clash. Fast: nothing is compiled."""
import json
import os
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import catalog
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.mods import load_patch, mod_dirs, symbol_overlays
from perkons.patch import Patcher


class TestModClashes(unittest.TestCase):
    def test_options(self):
        opts = catalog.options()                       # refuses duplicate ids
        ids = {o['id'] for o in opts}
        codes = [o['code'] for o in opts]
        self.assertEqual(len(codes), len(set(codes)), f'build codes used twice: {codes}')
        for o in opts:
            with self.subTest(option=o['id']):
                self.assertRegex(o['code'], r'^[a-z0-9]{2}$')
                self.assertLessEqual(set(o['requires']) | set(o['conflicts']), ids)

    def test_mod_sites_name_known_functions(self):
        for core in ('m4', 'm7'):
            path = SYMBOLS_V130.replace('-m7.json', f'-{core}.json')
            sym = Symbols(path)
            for o in symbol_overlays(path):
                with open(o) as f:
                    sites = json.load(f).get('sites', {})
                for k, s in sites.items():
                    if not k.startswith('_') and 'call' in s:
                        with self.subTest(file=os.path.relpath(o), site=k):
                            self.assertIn(s['call'], sym.fn)

    def test_every_option_registers_together(self):
        """apply() of every option's patches into one patcher: the hosts raise on clashes."""
        stock = Image.load(require_image('v1.3.0'))
        p = Patcher(stock)
        p.symbols = {'m7': Symbols(SYMBOLS_V130), 'm4': Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))}
        p.build_dir = None
        for o in catalog.options():
            if o['conflicts']:
                continue                               # can't be in the same build anyway
            for spec in o['patches']:
                name, _, arg = spec.partition(':')
                mod = load_patch(name)
                mod.apply(p, arg) if arg else mod.apply(p)
        self.assertTrue(mod_dirs())


if __name__ == '__main__':
    unittest.main()
