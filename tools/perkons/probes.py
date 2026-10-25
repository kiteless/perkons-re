"""Derive layout facts for a (ported) M7 symbols file by running the firmware.

Struct offsets and RAM layout can change between firmware versions even when the code
matches, so instead of copying them the porter measures them:

  cVoice.param_ptrs, params   four consecutive pointers params[v][0..3] in a wired voice
  cVoice.algo/mode/...        the byte each setter changes
  cFourthSlot.sampler/crush   where the cSamplePlayer / cNoiseCrush vtable pointer sits
  slots                       the 4 pointers to cFirstSlot..cFourthSlot after wire_voices
  cFourthSlot.p2cfg           the byte a config type-2 message changes (main()'s loop)
  cSamplePlayer.sample_ptr    the word a "samples ready" message sets (if main handles it)
  slot_extents, group_v*      slot addresses up to the next known object

Each probe returns (value, how) or raises; callers keep the old value on failure.
"""
from .emu import M7Emu, M7System
from .port import Program

SETTERS = [('cVoice_set_algo', 'cVoice.algo', 2), ('cVoice_set_mode', 'cVoice.mode', 1),
           ('cVoice_set_velocity', 'cVoice.velocity', 0x55), ('cVoice_set_accent', 'cVoice.accent', 0x33),
           ('cVoice_set_mute', 'cVoice.mute', 1)]


def _diff(a, b):
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


def probe_m7(img, sym, report):
    """Update sym.raw (and sym.off / sym.g) in place; append to report."""
    raw = sym.raw
    m7, m4 = img.segment('m7').data, img.segment('m4').data

    def setv(section, key, val, how):
        old = raw[section].get(key)
        raw[section][key] = f'{val:#x}' if section == 'offsets' else f'{val:#010x}'
        report.append((section, key, old, val, 'probe: ' + how))
        (sym.off if section == 'offsets' else sym.g)[key] = val

    def attempt(name, fn):
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            report.append(('probe', name, None, None, f'probe failed ({type(ex).__name__}: {ex}); old value kept'))

    def slots():
        e = M7Emu(m7, sym, m4)
        e.init_ram()
        e.call(sym.fn['ctor_misc'])
        e.call(sym.fn['ctor_voices'])
        e.call(sym.fn['wire_voices'])
        want = ['cFirstSlot', 'cSecondSlot', 'cThirdSlot', 'cFourthSlot']

        def cls(ptr):
            try:
                return e.class_of(ptr) if 0x20000000 <= ptr < 0x20020000 else None
            except Exception:  # noqa: BLE001
                return None
        lo, hi = sym.mem['bss_start'], sym.mem['bss_end']
        hits = [a for a in range(lo, hi - 12, 4)
                if cls(e.r32(a)) == want[0] and [cls(e.r32(a + 4 * i)) for i in range(4)] == want]
        if len(hits) != 1:
            raise RuntimeError(f'slots array found {len(hits)} times')
        setv('globals', 'slots', hits[0], 'the 4 pointers to cFirstSlot..cFourthSlot after wire_voices')

    def wiring():
        e = M7Emu(m7, sym, m4).boot_voices()
        obj = e.slot(0)
        words = [e.r32(obj + o) for o in range(0, 0x100, 4)]
        for k in range(len(words) - 3):
            w = words[k:k + 4]
            if 0x20000000 <= w[0] < 0x20020000 and w == [w[0] + 4 * i for i in range(4)]:
                setv('offsets', 'cVoice.param_ptrs', 4 * k, f'4 consecutive pointers in voice 1 at +{4 * k:#x}')
                setv('globals', 'params', w[0], 'voice 1 param pointer 0')
                break
        else:
            raise RuntimeError('no param pointers found in voice 1')
        slots = [e.slot(i) for i in range(4)]
        for i in range(1, 4):
            if f'group_v{i + 1}' in raw['globals']:
                setv('globals', f'group_v{i + 1}', slots[i], f'slots[{i}]')
        # extents: slot start .. next known object / global above it
        bounds = sorted(set(slots) | {v for k, v in sym.g.items() if 0x20000000 <= v < 0x20020000}
                        | {sym.mem['bss_end']})
        ext = []
        for i, s in enumerate(slots):
            nxt = min(b for b in bounds if b > s)
            ext.append([f'{s:#010x}', f'{nxt:#010x}'])
        old = raw.get('slot_extents')
        raw['slot_extents'] = ext
        report.append(('slot_extents', 'all', old, None, 'probe: slot addresses to next known object'))

    def setters():
        e = M7Emu(m7, sym, m4).boot_voices()
        obj = e.slot(0)
        for fn, off, val in SETTERS:
            before = bytes(e.uc.mem_read(obj, 0x100))
            e.call(sym.fn[fn], obj, val)
            d = _diff(before, bytes(e.uc.mem_read(obj, 0x100)))
            if len(d) != 1:
                raise RuntimeError(f'{fn} changed {len(d)} bytes')
            setv('offsets', off, d[0], f'byte changed by {fn}')

    def subobjects():
        e = M7Emu(m7, sym, m4).boot_voices()
        seg = img.segment('m7')
        rt = Program(seg.data, seg.addr, {}).rtti(with_vptr=True)
        s3 = e.slot(3)
        for cls, key in (('cSamplePlayer', 'cFourthSlot.sampler'), ('cNoiseCrush', 'cFourthSlot.crush')):
            vptr = rt[cls][0]
            hits = [o for o in range(0, 0x4000, 4) if e.r32(s3 + o) == vptr]
            if len(hits) != 1:
                raise RuntimeError(f'{cls} vptr found {len(hits)} times in voice 4')
            setv('offsets', key, hits[0], f'{cls} vtable pointer inside voice 4')

    def p2cfg():
        e = M7System(m7, sym, m4).boot()
        s3 = e.slot(3)
        before = bytes(e.uc.mem_read(s3, 0x4000))
        e.send(3, 2, b'\x00\x01')
        e.pump()
        d = _diff(before, bytes(e.uc.mem_read(s3, 0x4000)))
        if len(d) != 1:
            raise RuntimeError(f'type-2 message changed {len(d)} bytes of voice 4')
        setv('offsets', 'cFourthSlot.p2cfg', d[0], 'byte changed by config message type 2')

    def samples():
        e = M7System(m7, sym, m4).boot()
        sp = e.slot(3) + sym.off['cFourthSlot.sampler']
        for o in range(0, 0x200, 4):          # clear pointers so the message must set them
            if 0x08000000 <= e.r32(sp + o) < 0x08200000 or 0x24000000 <= e.r32(sp + o) < 0x24080000:
                e.w32(sp + o, 0)
        before = bytes(e.uc.mem_read(sp, 0x200))
        e.send(3, 3, b'\x01')
        e.pump()
        after = bytes(e.uc.mem_read(sp, 0x200))
        cand = [o for o in range(0, 0x200, 4) if before[o:o + 4] != after[o:o + 4]]
        if not cand:
            raise RuntimeError('"samples ready" message changed nothing (not handled by main?)')
        setv('offsets', 'cSamplePlayer.sample_ptr', cand[0], 'first word set by "samples ready" message')

    attempt('slots', slots)
    attempt('wiring', wiring)
    attempt('setters', setters)
    attempt('subobjects', subobjects)
    attempt('p2cfg', p2cfg)
    attempt('samples', samples)
