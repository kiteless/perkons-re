"""Emulator facts other work depends on: the voice engine boots and makes sound."""
import unittest

from fixtures import SYMBOLS_V130, require_image
from perkons.emu import M7Emu, Symbols
from perkons.fwimage import Image

PARAMS = [1500, 2500, 1800, 3000]
N = 6000


class TestM7Emu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        img = Image.load(require_image('v1.3.0'))
        cls.m7, cls.m4 = img.segment('m7').data, img.segment('m4').data
        cls.sym = Symbols(SYMBOLS_V130)

    def emu(self):
        return M7Emu(self.m7, self.sym, self.m4)

    def render(self, e, voice, algo, mode):
        e.set_params(voice, PARAMS)
        e.set_algo_mode(voice, algo, mode)
        e.trigger(voice)
        return e.render(voice, N)

    def test_stock_slots(self):
        e = self.emu().boot_voices()
        self.assertEqual([e.class_of(e.slot(i)) for i in range(4)],
                         ['cFirstSlot', 'cSecondSlot', 'cThirdSlot', 'cFourthSlot'])
        self.assertEqual(e.periph_writes, {}, 'voice engine boot should not touch peripherals')

    def test_voices_make_sound(self):
        for v in range(4):
            with self.subTest(voice=v + 1):
                out = self.render(self.emu().boot_voices(), v, 1, 0)
                self.assertGreater(max(map(abs, out)), 1000)
