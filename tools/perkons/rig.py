"""A booted M4 with a virtual panel, for mod tests.

    rig = M4Rig(img, cave=p.cave_symbols['m4host'])      # boots, sequencer set up, host booted
    rig.held.add(FW_KEY_TRIG(1))                          # key_held / steps_held / held steps
    rig.knob(0x21, 0.4); rig.moving.add(0x21)             # knob objects and their moved flags
    rig.press(0x47)                                       # a key event into the key handler
    rig.leds[0x4b]                                        # what set_led was last given
    rig.set_step(0, 4, note=40); rig.play(); rig.run(8)   # clock the sequencer: what it sent

stub_hardware(e, sym) is the part every M4 test needs (SD card present, DMA copies done
directly, the DAC and filter-switch drivers silent) for harnesses of their own.
"""
import os
import struct

from .emu import M4Emu, Symbols
from .patch import thumb_bl_target

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
        # the key handler the image registers (mods chain theirs before the stock one)
        site = self.sym.site('keys.handler_lit')['addr']
        seg = img.segment('m4')
        self.key_handler = struct.unpack_from('<I', seg.data, site - seg.addr)[0] & ~1
        self.seq = e.r32(self.sym.g['seq_ptr'])
        self.clock = self.sym.g['clock_state']
        irq = 16 + self.sym.const['subtick_irq']
        self.subtick_irq = struct.unpack_from('<I', seg.data, 4 * irq)[0] & ~1
        self.tim = e.r32(e.r32(e.r32(self.sym.g['subtick_timer_ptr']) + 12))     # TIM registers

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
        """A key event {key, 0x11 down / 0x10 up} into `handler` (default: the image's
        registered key handler, so mods' key hooks run as on the unit)."""
        self.e.uc.mem_write(EVT, bytes([key, 0x11 if down else 0x10, 0, 0, 0, 0, 0, 0]))
        (self.held.add if down else self.held.discard)(key)
        return self.e.call(handler or self.key_handler, EVT, max_insns=50_000_000)

    def press(self, key, handler=None):
        self.event(key, True, handler)
        self.event(key, False, handler)

    def mode(self):
        return self.e.call(self.sym.fn['get_mode'], max_insns=100_000)

    def set_mode(self, m):
        """Request a UI mode and apply it, as the main loop does (apply_mode)."""
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

    # -- the sequencer, clocked as the firmware does ---------------------------------------
    # The clock interrupt starts each step (clock+0x22 sub-tick reset, +0x20 beat count,
    # tick callback +0x3c with 1); the sub-tick timer interrupt then advances +0x22 and
    # calls tick(0), (+0x1c x +0x1e) per step.
    def r16(self, a):
        return struct.unpack('<H', bytes(self.e.uc.mem_read(a, 2)))[0]

    def w16(self, a, v):
        self.e.uc.mem_write(a, struct.pack('<H', v & 0xffff))

    def block(self, track):
        return self.e.r32(self.voice_state(track) + 4)

    def set_step(self, track, step, note=36, velocity=100, on=True):
        """A step record: +0 on, +6 note (36: no shift), +7 velocity."""
        a = self.block(track) + 8 * step
        self.e.w8(a, 1 if on else 0)
        self.e.w8(a + 6, note)
        self.e.w8(a + 7, velocity)

    def play(self):
        self.e.w8(self.seq, 1)
        self.e.w8(self.seq + 1, 1)

    def subtick(self):
        self.e.w32(self.tim + 0x10, 1)                   # TIM SR: update interrupt pending
        self.e.call(self.subtick_irq, max_insns=5_000_000)

    def step(self):
        c = self.clock
        self.w16(c + 0x22, 0)
        self.w16(c + 0x20, self.r16(c + 0x20) + 1)
        self.e.call(self.e.r32(c + 0x3c) & ~1, 1, max_insns=5_000_000)
        for _ in range(self.r16(c + 0x1c) * self.r16(c + 0x1e) - 1):
            self.subtick()

    def run(self, steps):
        """Clock `steps` steps; [(step, triggers, midi)] for the steps that sent anything:
        triggers [[(track, note)] per trigger message], midi [bytes]."""
        out = []
        for i in range(steps):
            self.step()
            trig = [self.decode_trigger(p) for typ, p in self.e.sent(2) if typ == 0]
            midi = [self.decode_midi(m) for m in self.midi]
            self.midi.clear()
            if trig or midi:
                out.append((i, trig, midi))
        return out

    def switch_to(self, p):
        """What the PATTERN page does when stopped: queue pattern p, switch now, then the
        main loop's switch-done step."""
        f = self.sym.fn
        self.e.call(f['seq_queue'], self.sym.g['pat_headers'] + 0x20 * p, max_insns=5_000_000)
        self.e.call(f['seq_switch_now'], max_insns=5_000_000)
        self.e.call(self.call_target('main.call_switch_done'), max_insns=50_000_000)

    def call_target(self, site):
        """What the `bl` at a call site calls in this image (a mod's hook chain, or stock)."""
        a = self.sym.site(site)['addr']
        seg = self.img.segment('m4')
        return thumb_bl_target(a, seg.data[a - seg.addr:a - seg.addr + 4])

    @staticmethod
    def decode_trigger(payload):
        """[(track, note)] for the tracks a trigger message turns on."""
        return [(t, payload[4 * t + 2]) for t in range(len(payload) // 4) if payload[4 * t]]

    @staticmethod
    def decode_midi(m):
        """(port, packed) from midi_out_bytes -> the message bytes."""
        packed = m[1]
        return bytes((packed >> (8 * i)) & 0xff for i in range(min(packed >> 24, 3)))
