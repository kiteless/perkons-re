"""The mods' code flash (tools/perkons/flash.py): fixed budgets, each core in its own bank.
Needs arm-none-eabi-gcc."""
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from fixtures import SYMBOLS_V130, require_image
from perkons import flash, m4host, m7host
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.hooks import HostError
from perkons.patch import Patcher


def patcher(img, build_dir):
    p = Patcher(img)
    p.symbols = {'m7': Symbols(SYMBOLS_V130), 'm4': Symbols(SYMBOLS_V130.replace('-m7.json', '-m4.json'))}
    p.build_dir = build_dir
    return p


class TestLayout(unittest.TestCase):
    def test_budgets_fit_whole_sectors(self):
        self.assertEqual((flash.CODE['m7'], flash.CODE['m4']), (128 * 1024, 256 * 1024))
        self.assertEqual((flash.FIRMWARE_MAX['m7'], flash.FIRMWARE_MAX['m4']), (768 * 1024, 256 * 1024))
        lo, hi = flash.REGIONS['m7']
        self.assertEqual(lo + flash.FIRMWARE_MAX['m7'] + flash.CODE['m7'], hi, 'the M7 region exactly')
        lo, hi = flash.REGIONS['m4']
        self.assertLessEqual(lo + flash.FIRMWARE_MAX['m4'] + flash.CODE['m4'], hi)

    def test_firmware_ceiling(self):
        stock = Image.load(require_image('v1.3.0'))
        self.assertIsNone(flash.check_firmware(stock))
        for core in ('m4', 'm7'):
            big = SimpleNamespace(segments=[SimpleNamespace(name=core, addr=flash.REGIONS[core][0],
                                                            data=bytes(flash.FIRMWARE_MAX[core] + 4))])
            self.assertIn(f'{core} firmware is', flash.check_firmware(big))

    def test_flash_meter_block_tiles_2_mb(self):
        fw_end = {'m4': 0x0812d390, 'm7': 0x080d221c}
        b = flash.block(fw_end)
        r = b['ranges']
        self.assertEqual((b['start'], b['end']), (0x08000000, 0x08200000))
        self.assertEqual((r[0][1], r[-1][2]), (b['start'], b['end']))
        self.assertTrue(all(x[2] == y[1] for x, y in zip(r, r[1:])))
        mods = {o: (s, e) for o, s, e in r if o in flash.AREAS}
        self.assertEqual(mods, flash.areas(fw_end))


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestBudgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))
        cls.tmp = tempfile.mkdtemp(prefix='pk-flash-')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def table(self, core, n):
        name = f'pk_tbl_{core}_{n}'
        path = os.path.join(self.tmp, f'{name}.c')
        with open(path, 'w') as f:
            f.write(f'const unsigned char {name}[{n}] = {{1}};\n'
                    f'const void *{name}_init(void) {{ return {name}; }}\n')
        return path, f'{name}_init'

    def test_code_after_each_firmware_and_recorded(self):
        p = patcher(self.stock, os.path.join(self.tmp, 'a'))
        for core, host in (('m7', m7host), ('m4', m4host)):
            src, init = self.table(core, 100000)
            host.host(p).add([src], init=init)
        img = p.result()
        for core in ('m7', 'm4'):
            grown = len(img.segment(core).data) - len(self.stock.segment(core).data)
            used = sum(s for _, s in p.ram[flash.AREA[core]].values())
            self.assertGreater(used, 100000)
            self.assertLessEqual(used, grown)
            self.assertTrue(any(o.endswith(f'pk_tbl_{core}_100000.c:code') and s >= 100000
                                for o, (_, s) in p.ram[flash.AREA[core]].items()))

    def test_over_budget_refused(self):
        for core, host in (('m7', m7host), ('m4', m4host)):
            p = patcher(self.stock, os.path.join(self.tmp, 'b' + core))
            src, init = self.table(core, flash.CODE[core] + 1)
            host.host(p).add([src], init=init)
            with self.assertRaisesRegex(HostError, f'{core.upper()} mods\' code is over its '
                                                   f'{flash.CODE[core] // 1024} KB'):
                p.result()


if __name__ == '__main__':
    unittest.main()
