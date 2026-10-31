"""A booted M4 with a virtual panel, for mod tests.

    rig = M4Rig(img, cave=p.cave_symbols['m4host'])      # boots, sequencer set up, host booted
    rig.held.add(FW_KEY_TRIG(1))                          # key_held / steps_held / held steps
    rig.knob(0x21, 0.4); rig.moving.add(0x21)             # knob objects and their moved flags
    rig.press(0x47)                                       # a key event into the key handler
    rig.leds[0x4b]                                        # what set_led was last given

stub_hardware(e, sym) is the part every M4 test needs (SD card present, DMA copies done
directly, the DAC and filter-switch drivers silent) for harnesses of their own.
"""
import os
import struct

from .emu import M4Emu, Symbols

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVT = 0x2407ff00            # scratch for key event structs (end of the sample area)
KNOB_AREA = 0x2407f000      # scratch knob objects when the firmware hasn't made them
KNOB_SCALE = 65535          # knob object +0xc: raw value 0..65535 (knob_value: 0..1)
KNOB_SIZE = 0x20


def stub_hardware(e, sym):
    """SD present, DMA copies done directly, DAC / filter-switch drivers silent."""
    f = sym.fn
    e.stub(f['sd_present'], lambda emu, *a: 1)

    def dma_copy(emu, src, dst, n, *_):
        e.uc.mem_write(dst, bytes(e.uc.mem_read(src, n)))
        return 1
    e.stub(f['dma_copy'], dma_copy)
    for name in ('analog_out', 'filter_out', 'analog_flush'):
        e.stub(f[name], lambda *a: 0)


class M4Rig:
    def __init__(self, img, cave=None, sd=None, version='v1.3.0', boot=True):
        self.img, self.cave = img, cave or {}
        self.sym = Symbols(os.path.join(ROOT, 'symbols', f'{version}-m4.json'))
        e = self.e = M4Emu(img.segment('m4').data, self.sym, img.segment('m7').data, sd=sd or {}).boot()
        f = self.sym.fn
        stub_hardware(e, self.sym)
        self.midi = []
        e.stub(f['midi_out_bytes'], lambda emu, port, packed, *_: self.midi.append((port, packed)))
        e.call(f['seq_setup'], max_insns=20_000_000)
        if boot and 'pk4_boot' in self.cave:
            e.call(self.cave['pk4_boot'], max_insns=50_000_000)
        # the panel
        self.held, self.moving, self.leds = set(), set(), {}
        e.stub(f['key_held'], lambda emu, k, *_: 1 if k in self.held else 0)
        e.stub(f['steps_held'], lambda emu, *_: 1 if any(k < 0x40 for k in self.held) else 0)
        e.stub(f['held_first'], self._held_first)
        e.stub(f['held_next'], self._held_next)
        e.stub(f['pot_moved'], lambda emu, pot, *_: 1 if pot in self.moving else 0)
        e.stub(f['set_led'], lambda emu, k, lvl, *_: self.leds.__setitem__(k, lvl))
        if not e.r32(self.sym.g['knobs_ptr']):
            e.w32(self.sym.g['knobs_ptr'], KNOB_AREA)
        self.knobs = e.r32(self.sym.g['knobs_ptr'])
        self._iter = []

    # held steps, as the firmware's list of held step keys (value = row << 4 | col)
    def _held_first(self, emu, it, *_):
        self._iter = sorted(k for k in self.held if k < 0x40)
        emu.w32(it, 1)
        return 0

    def _held_next(self, emu, it, *_):
        if not self._iter:
            return 0xffffffff
        k = self._iter.pop(0)
        return (k // 16) << 4 | (k % 16)

    # -- knobs ---------------------------------------------------------------------------
    def knob(self, pot, x):
        """Set knob `pot` (0x00-0x1f track * 8 + slot, 0x20 TEMPO, 0x21-0x23 LFO) to x in 0..1."""
        self.e.w32(self.knobs + KNOB_SIZE * pot + 0xc, int(x * KNOB_SCALE))

    def knob_at(self, pot):
        return self.e.r32(self.knobs + KNOB_SIZE * pot + 0xc) / KNOB_SCALE

    def turn(self, pot, to, poll, steps=8):
        """Turn a knob to `to` over `steps` calls of poll(), flagged as moving meanwhile."""
        start = self.knob_at(pot)
        self.moving.add(pot)
        for i in range(1, steps + 1):
            self.knob(pot, start + (to - start) * i / steps)
            poll()
        self.moving.discard(pot)

    # -- keys and UI modes ---------------------------------------------------------------
    def event(self, key, down, handler=None):
        """A key event {key, 0x11 down / 0x10 up} into `handler` (default: key_event)."""
        self.e.uc.mem_write(EVT, bytes([key, 0x11 if down else 0x10, 0, 0, 0, 0, 0, 0]))
        (self.held.add if down else self.held.discard)(key)
        return self.e.call(handler or self.sym.fn['key_event'], EVT, max_insns=50_000_000)

    def press(self, key, handler=None):
        self.event(key, True, handler)
        self.event(key, False, handler)

    def mode(self):
        return self.e.call(self.sym.fn['get_mode'], max_insns=100_000)

    def set_mode(self, m):
        """Request a UI mode and apply it, as the main loop does (FUN_081040c8)."""
        self.e.call(self.sym.fn['set_mode'], m, max_insns=100_000)
        self.e.call(self.sym.fn['apply_mode'], max_insns=5_000_000)

    # -- outputs -------------------------------------------------------------------------
    def stream1(self):
        """Voice records the stream-1 sender sent since last asked: [[u16 x 6] per voice]."""
        out = []
        for typ, p in self.e.sent(1):
            out.append([list(struct.unpack_from('<6H', p, 12 * v)) for v in range(len(p) // 12)])
        return out

    def voice_state(self, track):
        return self.e.r32(self.e.r32(self.sym.g['seq_ptr']) + 4) + track * 0x10c
