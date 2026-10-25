"""Unicorn-based harness for running Perkons M7 (DSP core) code off-device.

It doesn't boot the firmware. It does just enough to put the voice engine in the
same state as after `main()` has wired it up:

  1. copy .data and zero .bss (what the reset handler does)
  2. run the C++ static constructors from .init_array
  3. run wire_voices() and each slots[i]->init()

After that, voices can be driven the way the M4 drives them (params, algo/mode,
trigger) and rendered sample by sample to a WAV file.

Peripheral accesses go to RAM-backed stubs and are counted, so anything that
touches hardware shows up in the report rather than crashing.
"""
import json
import os
import struct
import wave

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_MEM_READ, \
    UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED, UC_HOOK_CODE
from unicorn import arm_const as A

RETURN_MAGIC = 0x0BADF00C  # LR for top-level calls; execution stops here

# STM32H745/H747 memory map (subset we care about)
REGIONS = [
    ('itcm', 0x00000000, 0x00010000),
    ('flash', 0x08000000, 0x00200000),
    ('rtn', RETURN_MAGIC & ~0xFFF, 0x1000),
    ('d2_sram_alias', 0x10000000, 0x00048000),
    ('dtcm', 0x20000000, 0x00020000),
    ('axi_sram', 0x24000000, 0x00080000),
    ('d2_sram', 0x30000000, 0x00048000),
    ('d3_sram', 0x38000000, 0x00010000),
    ('periph', 0x40000000, 0x20000000),
    ('scs', 0xE0000000, 0x00100000),
]


def _h(v):
    return int(v, 16) if isinstance(v, str) else v


class Symbols:
    def __init__(self, path):
        with open(path) as f:
            self.raw = json.load(f)
        self.base = _h(self.raw['segment_base'])
        # keys starting with '_' are comments/notes, not addresses
        self.mem = {k: _h(v) for k, v in self.raw['memory'].items() if not k.startswith('_')}
        self.fn = {k: _h(v) for k, v in self.raw['functions'].items() if not k.startswith('_')}
        self.g = {k: _h(v) for k, v in self.raw['globals'].items() if not k.startswith('_')}
        self.off = {k: _h(v) for k, v in self.raw.get('offsets', {}).items() if not k.startswith('_')}
        self.const = {k: _h(v) for k, v in self.raw.get('constants', {}).items() if not k.startswith('_')}
        self.sites = {k: v for k, v in self.raw.get('sites', {}).items() if not k.startswith('_')}

    def site(self, name):
        """A named patch point: {'addr': int, and 'call': fn name | 'bytes': bytes | 'word': int}."""
        s = dict(self.sites[name])
        s['addr'] = _h(s['addr'])
        if 'bytes' in s:
            s['bytes'] = bytes.fromhex(s['bytes'])
        if 'word' in s:
            s['word'] = _h(s['word'])
        return s


class CoreEmu:
    """One STM32H7 core: memory map, its flash segment, call/memory helpers, peripheral stubs.
    `other_bin` is the other core's segment, loaded so cross-core flash reads resolve."""

    OTHER_BASE = 0x08100000  # where `other_bin` is loaded (the M4 segment, for the M7)

    def __init__(self, seg_bin: bytes, symbols: Symbols, other_bin: bytes = None, trace_periph=False,
                 freeze_rand=False):
        self.sym = symbols
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        for _, base, size in REGIONS:
            self.uc.mem_map(base, size)
        if other_bin:
            self.uc.mem_write(self.OTHER_BASE, other_bin)
        self.uc.mem_write(symbols.base, seg_bin)
        self.uc.mem_write(RETURN_MAGIC & ~1, b'\x00\xbf' * 4)  # nops at the return address
        # Enable the FPU: CPACR CP10/CP11 full access
        self.uc.mem_write(0xE000ED88, struct.pack('<I', 0xF << 20))
        self.periph_reads = {}
        self.periph_writes = {}
        self.insn_count = 0
        self._count_insns = False
        self.uc.hook_add(UC_HOOK_MEM_READ, self._on_periph, user_data='r', begin=0x40000000, end=0x5FFFFFFF)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._on_periph, user_data='w', begin=0x40000000, end=0x5FFFFFFF)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.trace_periph = trace_periph
        if freeze_rand:
            # newlib rand() feeds every noise engine from one shared sequence, so how many
            # noise engines run changes everyone's noise. Pinning it makes renders comparable
            # between differently patched builds (noise becomes a constant; all code paths still run).
            a = symbols.fn['rand']
            self.uc.hook_add(UC_HOOK_CODE, self._fake_rand, begin=a, end=a)

    # -- hooks ------------------------------------------------------------------------
    def _on_periph(self, uc, access, addr, size, value, kind):
        d = self.periph_reads if kind == 'r' else self.periph_writes
        d[addr] = d.get(addr, 0) + 1
        if self.trace_periph:
            print(f'  periph {kind} {addr:08x} pc={uc.reg_read(A.UC_ARM_REG_PC):08x}')

    def _on_unmapped(self, uc, access, addr, size, value, _):
        pc = uc.reg_read(A.UC_ARM_REG_PC)
        raise RuntimeError(f'unmapped access {addr:08x} at pc={pc:08x}')

    def _fake_rand(self, uc, addr, size, _):
        uc.reg_write(A.UC_ARM_REG_R0, 0x2AAAAAAA)
        uc.reg_write(A.UC_ARM_REG_PC, uc.reg_read(A.UC_ARM_REG_LR))

    def _on_code(self, uc, addr, size, _):
        self.insn_count += 1

    # -- memory helpers ---------------------------------------------------------------
    def r32(self, a):
        return struct.unpack('<I', self.uc.mem_read(a, 4))[0]

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def r8(self, a):
        return self.uc.mem_read(a, 1)[0]

    def w8(self, a, v):
        self.uc.mem_write(a, bytes([v & 0xFF]))

    # -- calling ----------------------------------------------------------------------
    def call(self, fn, *args, sp=None, max_insns=50_000_000):
        regs = [A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2, A.UC_ARM_REG_R3]
        for r, v in zip(regs, args):
            self.uc.reg_write(r, v & 0xFFFFFFFF)
        self.uc.reg_write(A.UC_ARM_REG_SP, sp or self.sym.mem['stack_top'] - 0x100)
        self.uc.reg_write(A.UC_ARM_REG_LR, RETURN_MAGIC | 1)
        try:
            self.uc.emu_start(fn | 1, RETURN_MAGIC & ~1, count=max_insns)
        except UcError as e:
            pc = self.uc.reg_read(A.UC_ARM_REG_PC)
            raise RuntimeError(f'emulation error {e} at pc={pc:08x} calling {fn:08x}') from None
        pc = self.uc.reg_read(A.UC_ARM_REG_PC)
        if pc != RETURN_MAGIC & ~1:
            raise RuntimeError(f'call to {fn:08x} did not return (pc={pc:08x}); increase max_insns?')
        return self.uc.reg_read(A.UC_ARM_REG_R0)

    def vcall(self, obj, index, *args):
        """Call virtual method `index` on a C++ object."""
        vtbl = self.r32(obj)
        return self.call(self.r32(vtbl + 4 * index), obj, *args)

    def count_insns(self, on=True):
        if on and not self._count_insns:
            self._code_hook = self.uc.hook_add(UC_HOOK_CODE, self._on_code)
        elif not on and self._count_insns:
            self.uc.hook_del(self._code_hook)
        self._count_insns = on

    def init_ram(self):
        """What the reset handler does: copy .data, zero .bss."""
        m = self.sym.mem
        data = self.uc.mem_read(m['data_lma'], m['data_end'] - m['data_start'])
        self.uc.mem_write(m['data_start'], bytes(data))
        self.uc.mem_write(m['bss_start'], b'\0' * (m['bss_end'] - m['bss_start']))

    def stub(self, addr, fn):
        """Replace the firmware function at addr with a Python function(emu, r0, r1, r2, r3) -> r0."""
        regs = [A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2, A.UC_ARM_REG_R3]

        def hook(uc, address, size, _):
            ret = fn(self, *[uc.reg_read(r) for r in regs])
            uc.reg_write(A.UC_ARM_REG_R0, (ret or 0) & 0xFFFFFFFF)
            uc.reg_write(A.UC_ARM_REG_PC, uc.reg_read(A.UC_ARM_REG_LR))
        self.uc.hook_add(UC_HOOK_CODE, hook, begin=addr & ~1, end=addr & ~1)

    def cstr(self, addr, maxlen=256):
        return bytes(self.uc.mem_read(addr, maxlen)).split(b'\0')[0].decode('latin-1')


class M7Emu(CoreEmu):
    """The M7 (DSP) core: boots the voice engine the way main() does."""

    def __init__(self, m7_bin: bytes, symbols: Symbols, m4_bin: bytes = None, **kw):
        super().__init__(m7_bin, symbols, m4_bin, **kw)

    # -- boot -------------------------------------------------------------------------
    def boot_voices(self):
        f = self.sym.fn
        self.init_ram()
        self.call(f['ctor_misc'])
        self.call(f['ctor_voices'])
        self.call(f['wire_voices'])
        for i in range(4):
            self.vcall(self.slot(i), 1)  # init()
        return self

    # -- voice API (mirrors what main() does with IPC channel 1 messages) ----------------
    def slot(self, i):
        return self.r32(self.sym.g['slots'] + 4 * i)

    def class_of(self, obj):
        """Return the RTTI class name of a C++ object, e.g. 'cFirstSlot'."""
        ti = self.r32(self.r32(obj) - 4)
        name_ptr = self.r32(ti + 4)
        raw = bytes(self.uc.mem_read(name_ptr, 32)).split(b'\0')[0].decode()
        return raw.lstrip('0123456789')

    def set_params(self, voice, p):
        """p: 4 ints 0..4095, the 12-bit knob values M4 sends (order still to be labeled)."""
        for k, v in enumerate(p):
            self.w32(self.sym.g['params'] + 16 * voice + 4 * k, v)

    def set_algo_mode(self, voice, algo, mode):
        s = self.slot(voice)
        self.call(self.sym.fn['cVoice_set_algo'], s, algo)
        self.call(self.sym.fn['cVoice_set_mode'], s, mode)
        self.vcall(s, 2)  # update(): propagates algo/mode into the active engine

    def trigger(self, voice, velocity=0x7F, accent=0):
        s = self.slot(voice)
        self.call(self.sym.fn['cVoice_set_velocity'], s, velocity)
        self.call(self.sym.fn['cVoice_set_accent'], s, accent)
        self.vcall(s, 0)

    def render(self, voice, n):
        s = self.slot(voice)
        fn = self.r32(self.r32(s) + 12)
        out = []
        for _ in range(n):
            v = self.call(fn, s) & 0xFFFF
            out.append(v - 0x10000 if v & 0x8000 else v)
        return out


def write_wav(path, samples, rate=48000):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f'<{len(samples)}h', *samples))


class M7System(M7Emu):
    """Runs more of the real firmware: main()'s wiring block, main()'s message loop and
    the real audio DMA callback, fed by M4-style messages in the shared IPC rings.
    Use this to test patches that hook main() or the message handlers."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        r = self.sym.raw
        self.mp = {k: _h(v) for k, v in r['main_points'].items() if not k.startswith('_') and k != 'loop_regs'}
        self.loop_regs = {k: _h(v) for k, v in r['main_points']['loop_regs'].items()}
        self.ipc = {k: _h(v) for k, v in r['ipc'].items() if not k.startswith('_')}

    def boot(self):
        """Reset-handler work + ctors, IPC rings as M4 sets them up, then main()'s own
        wiring block (bl wire_voices + slots[i]->init()), whatever it's been patched to."""
        f, g = self.sym.fn, self.sym.g
        self.init_ram()
        self.call(f['ctor_misc'])
        self.call(f['ctor_voices'])
        for i in range(4):
            d = self.ipc['desc'] + 0x18 * i
            self.uc.mem_write(d, struct.pack('<6I', self.ipc['buffers'] + self.ipc['size'] * i, self.ipc['size'], 0, 0, 0, 0))
        self.w8(g['ipc_ready'], 1)
        self.w32(g['render_fn_ptr'], self.loop_regs['r4'])  # normal (non-calibration) render callback
        self.run_range(self.mp['wire_block_start'], self.mp['wire_block_end'], {'r8': self.loop_regs['r8']})
        return self

    def run_range(self, start, end, regs=None, max_insns=50_000_000):
        names = {f'r{i}': getattr(A, f'UC_ARM_REG_R{i}') for i in range(13)}
        for k, v in (regs or {}).items():
            self.uc.reg_write(names[k], v)
        self.uc.reg_write(A.UC_ARM_REG_SP, self.sym.mem['stack_top'] - 0x400)
        self.uc.emu_start(start | 1, end, count=max_insns)
        pc = self.uc.reg_read(A.UC_ARM_REG_PC)
        if pc != end:
            raise RuntimeError(f'run_range {start:08x}->{end:08x} stopped at {pc:08x}')

    # -- IPC (M4 side) ----------------------------------------------------------------
    def send(self, stream, mtype, payload: bytes):
        d = self.ipc['desc'] + 0x18 * stream
        buf, size, w, r = struct.unpack('<4I', self.uc.mem_read(d, 16))
        msg = struct.pack('<II', self.ipc['magic'] | mtype, len(payload)) + payload
        free = (r - w - 1) % size
        if len(msg) > free:
            raise RuntimeError('IPC ring full')
        for b in msg:
            self.w8(buf + w, b)
            w = (w + 1) % size
        self.w32(d + 8, w)

    def pending(self, stream):
        d = self.ipc['desc'] + 0x18 * stream
        _, _, w, r = struct.unpack('<4I', self.uc.mem_read(d, 16))
        return w != r

    def pump(self, max_iter=32):
        """Run main()'s message loop until streams 1 and 3 are drained."""
        head = self.mp['loop_head']
        regs = dict(self.loop_regs)
        for _ in range(max_iter):
            if not (self.pending(1) or self.pending(3)):
                return
            # loop head is "add r1, sp, #0x10"; do it here and start after it
            regs['r1'] = self.sym.mem['stack_top'] - 0x400 + 0x10
            self.run_range(head + 2, head, regs)
        raise RuntimeError('message loop did not drain')

    # -- M4-style messages ------------------------------------------------------------
    def send_voice_state(self, voices):
        """voices: 4 dicts {params:[4 x 0..4095], algo, mode, mute} -> stream 1 (0x30 bytes)."""
        out = b''
        for v in voices:
            out += struct.pack('<4H4B', *[(x & 0xFFF) << 4 for x in v['params']], v.get('algo', 0),
                               v.get('mode', 0), v.get('mute', 0), 0)
        self.send(1, 0, out)

    def send_triggers(self, trig, algo_mode, velocity=0x7F, accent=0):
        """trig: 4 bools; algo_mode: 4 (algo, mode). -> stream 2, consumed by the audio callback."""
        out = b''
        for t, (a, m) in zip(trig, algo_mode):
            out += bytes([1 if t else 0, (a & 3) | ((m & 3) << 4), accent, velocity])
        self.send(2, 0, out)

    # -- audio --------------------------------------------------------------------------
    def audio(self, n_frames):
        """Run the real DMA callback; returns 4 lists (one per output) of int16 samples."""
        cb = self.r32(self.sym.g['render_fn_ptr'])
        buf = self.sym.mem['audio_dma_buf']
        outs = [[], [], [], []]
        done = 0
        while done < n_frames:
            for half in (0, 1):
                for block in (0, 1):  # block 0: triggers + outputs 3,4; block 1: outputs 1,2
                    self.call(cb, block, half)
                    raw = self.uc.mem_read(buf + (half * 0x40 + block * 0x80) * 2, 0x80)
                    pairs = struct.unpack('<64h', raw)
                    a, b = (2, 3) if block == 0 else (0, 1)
                    outs[a] += pairs[0::2]
                    outs[b] += pairs[1::2]
                done += 32
        return [o[:n_frames] for o in outs]


class M4Emu(CoreEmu):
    """The M4 (UI/SD) core, for running patch code and the firmware functions it calls.

    `sd` is a virtual SD card: {path: bytes}. FatFs f_open/f_read/f_close/f_stat are
    replaced by Python, so firmware code that reads files (e.g. the JSON loader) runs for
    real against it. Paths are matched case-insensitively, like FAT."""

    OTHER_BASE = 0x08020000  # the M7 segment

    def __init__(self, m4_bin: bytes, symbols: Symbols, m7_bin: bytes = None, sd=None, **kw):
        super().__init__(m4_bin, symbols, m7_bin, **kw)
        self.sd = {self._norm(k): v for k, v in (sd or {}).items()}
        self.sd_log = []
        self._open = {}
        f = symbols.fn
        self.stub(f['f_open'], self._f_open)
        self.stub(f['f_read'], self._f_read)
        self.stub(f['f_close'], self._f_close)
        self.stub(f['f_stat'], self._f_stat)
        self.ipc = {k: _h(v) for k, v in symbols.raw['ipc'].items() if not k.startswith('_')}

    @staticmethod
    def _norm(path):
        path = path.replace('\\', '/')
        if path[:2] in ('0:', '1:'):
            path = path[2:]
        return path.lstrip('/').lower()

    FR_OK, FR_NO_FILE, FR_DENIED = 0, 4, 7

    def _f_open(self, emu, fp, path_ptr, mode, _):
        path = self.cstr(path_ptr)
        self.sd_log.append(('open', path, mode))
        if mode & 0x02 or mode & 0x08 or mode & 0x10:  # write / create: read-only card
            return self.FR_DENIED
        data = self.sd.get(self._norm(path))
        if data is None:
            return self.FR_NO_FILE
        self._open[fp] = [data, 0]
        return self.FR_OK

    def _f_read(self, emu, fp, buf, btr, br_ptr):
        data, pos = self._open[fp]
        chunk = data[pos:pos + btr]
        self.uc.mem_write(buf, chunk)
        self._open[fp][1] = pos + len(chunk)
        self.w32(br_ptr, len(chunk))
        return self.FR_OK

    def _f_close(self, emu, fp, *_):
        self._open.pop(fp, None)
        return self.FR_OK

    def _f_stat(self, emu, path_ptr, fno, *_):
        path = self.cstr(path_ptr)
        self.sd_log.append(('stat', path))
        data = self.sd.get(self._norm(path))
        if data is None:
            return self.FR_NO_FILE
        if fno:
            self.w32(fno, len(data))  # FILINFO.fsize
        return self.FR_OK

    def boot(self):
        """RAM init + the firmware's own ipc_init (sets up the shared rings)."""
        self.init_ram()
        self.call(self.sym.fn['ipc_init'])
        return self

    def sent(self, stream):
        """Drain and return messages the M4 queued on a stream: [(type, payload), ...]."""
        d = self.ipc['desc'] + 0x18 * stream
        buf, size, w, r = struct.unpack('<4I', self.uc.mem_read(d, 16))
        raw = bytearray()
        while r != w:
            raw.append(self.r8(buf + r))
            r = (r + 1) % size
        self.w32(d + 12, r)
        out = []
        while raw:
            hdr, ln = struct.unpack_from('<II', raw)
            if hdr & 0xFFFFFF00 != self.ipc['magic']:
                raise RuntimeError(f'bad IPC header {hdr:08x}')
            out.append((hdr & 0xFF, bytes(raw[8:8 + ln])))
            del raw[:8 + ln]
        return out
