"""The example C patch builds, runs through main()'s real code, and changes nothing."""
import os
import shutil
import tempfile
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons import verify
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.mods import load_patch
from perkons.patch import Patcher


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestExampleHook(unittest.TestCase):
    def test_builds_and_matches_stock(self):
        stock = Image.load(require_image('v1.3.0'))
        sym = Symbols(SYMBOLS_V130)
        tmp = tempfile.mkdtemp(prefix='pk-ex-')
        try:
            p = Patcher(stock)
            p.symbols = {'m7': sym}
            p.build_dir = tmp
            load_patch('example_hook').apply(p)
            img = p.result()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertGreater(len(img.segment('m7').data), len(stock.segment('m7').data))
        a, b = verify.boot(stock, sym), verify.boot(img, sym)
        lo, hi = 0x20000000, 0x20008100   # all of .data/.bss after boot
        self.assertEqual(bytes(a.uc.mem_read(lo, hi - lo)), bytes(b.uc.mem_read(lo, hi - lo)))
        for out, algo, mode, _, ok in verify.compare_to_stock(stock, img, sym, algos=(1,), modes=(0,)):
            self.assertTrue(ok, f'output {out + 1} differs')
