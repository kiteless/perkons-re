"""The stock player and the step delay (include/m4/fw_m4_seq.h FW_STEP_DELAY): a signed % of a
step, late when positive, early when negative (started during the step before), and the track
state's FW_VS_STEP_STATE while an early step plays ahead of its time."""
import struct
import unittest

from fixtures import require_image
from perkons.fwimage import Image
from perkons.rig import M4Rig

FW_STEP_DELAY = 2
FW_VS_STEP, FW_VS_TICK, FW_VS_STEP_STATE = 0x1c, 0x24, 0x28
STEP_TICKS = 24
PASS = STEP_TICKS * 12 * 16             # sub-ticks in a 16-step pass at the rig's clock


class Rig(M4Rig):
    """Stock firmware, clocked one sub-tick at a time; `fired`: (step, tick) of each trigger
    track 1 sends."""

    def __init__(self, img):
        super().__init__(img)
        self.sub, self.fired = 0, []

    def tick(self):
        c = self.clock
        if self.sub % (self.r16(c + 0x1c) * self.r16(c + 0x1e)) == 0:
            self.w16(c + 0x22, 0)
            self.w16(c + 0x20, self.r16(c + 0x20) + 1)
            self.e.call(self.e.r32(c + 0x3c) & ~1, 1, max_insns=5_000_000)
        else:
            self.subtick()
        self.sub += 1
        vs = self.voice_state(0)
        if any(p[0] for typ, p in self.e.sent(2) if typ == 0):
            self.fired.append((self.r16(vs + FW_VS_STEP), self.r16(vs + FW_VS_TICK)))

    def delay(self, step, d):
        self.e.uc.mem_write(self.block(0) + 8 * step + FW_STEP_DELAY, struct.pack('<h', d))


class TestStepDelay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stock = Image.load(require_image('v1.3.0'))

    def passes(self, delay):
        r = Rig(self.stock)
        r.set_step(0, 8)
        r.delay(8, delay)
        r.play()
        for i in range(3 * PASS):
            if i == PASS:
                r.fired.clear()             # after a warm-up pass
            r.tick()
        return r.fired

    def test_late_and_early(self):
        """delay * 24 / 100 ticks, truncated towards 0: late in the step, or early in the step
        before (counted there: the track is already on step 8)."""
        for d, want in ((0, (8, 0)), (17, (8, 4)), (50, (8, 12)), (99, (8, 23)),
                        (-17, (8, 20)), (-50, (8, 12)), (-84, (8, 4))):
            with self.subTest(delay=d):
                self.assertEqual(self.passes(d), [want, want])

    def test_step_state_while_an_early_step_plays_ahead(self):
        """Step 8 at -50: from tick 12 of step 7 the track is on step 8 with state 2, until
        step 8's own time, where it counts from 0 again."""
        r = Rig(self.stock)
        r.set_step(0, 8)
        r.delay(8, -50)
        r.play()
        vs, seen = r.voice_state(0), set()
        for _ in range(2 * PASS):
            r.tick()
            seen.add((r.r16(vs + FW_VS_STEP), r.r16(vs + FW_VS_TICK) >= 12, r.e.r8(vs + FW_VS_STEP_STATE)))
        self.assertIn((8, True, 2), seen)
        self.assertNotIn((7, True, 2), seen)


if __name__ == '__main__':
    unittest.main()
