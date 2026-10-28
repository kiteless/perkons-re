"""Behavioural checks for a symbols file: does each symbol do what we think it does?

Addresses are only trustworthy if the code at them behaves as expected, so each check
runs firmware code in the emulator and looks at the effect. This is the acceptance test
for hand-written symbols and for ones produced by the porter (tools/port_symbols.py).

    results = run_all(img, sym_m7, sym_m4)   # [(name, ok, detail), ...]
"""
import struct
import traceback

from .emu import M4Emu, M7Emu, M7System, _h
from .patch import thumb_bl
from .port import Program, read_schema

M7_CLASSES = ['cFirstSlot', 'cSecondSlot', 'cThirdSlot', 'cFourthSlot']


class CheckFailed(Exception):
    pass


def need(cond, msg):
    if not cond:
        raise CheckFailed(msg)


# -- M7 ---------------------------------------------------------------------------------

def m7_boot(img, sym):
    """reset-handler work, ctors, wire_voices, init: slots hold the four voice classes."""
    e = M7Emu(img.segment('m7').data, sym, img.segment('m4').data).boot_voices()
    got = [e.class_of(e.slot(i)) for i in range(4)]
    need(got == M7_CLASSES, f'slots[] classes {got}')
    need(not e.periph_writes, 'voice engine boot touched peripherals')
    return f'slots @{[hex(e.slot(i)) for i in range(4)]}'


def m7_params(img, sym):
    """wire_voices points every voice's param pointers at params[voice][0..3]."""
    e = M7Emu(img.segment('m7').data, sym, img.segment('m4').data).boot_voices()
    p = sym.g['params']
    for v in range(4):
        obj = e.slot(v)
        ptrs = [e.r32(obj + sym.off['cVoice.param_ptrs'] + 4 * k) for k in range(4)]
        need(ptrs == [p + 16 * v + 4 * k for k in range(4)], f'voice {v + 1} param ptrs {[hex(x) for x in ptrs]}')
    return f'params @{p:#x}'


def m7_setters(img, sym):
    """cVoice_set_* write exactly the byte at their OFF_cVoice_* offset."""
    e = M7Emu(img.segment('m7').data, sym, img.segment('m4').data).boot_voices()
    obj = e.slot(0)
    for fn, off, val in (('cVoice_set_algo', 'cVoice.algo', 2), ('cVoice_set_mode', 'cVoice.mode', 1),
                         ('cVoice_set_velocity', 'cVoice.velocity', 0x55), ('cVoice_set_accent', 'cVoice.accent', 0x33),
                         ('cVoice_set_mute', 'cVoice.mute', 1)):
        before = bytes(e.uc.mem_read(obj, 0x100))
        e.call(sym.fn[fn], obj, val)
        after = bytes(e.uc.mem_read(obj, 0x100))
        changed = [i for i in range(0x100) if before[i] != after[i]]
        need(changed == [sym.off[off]] and after[sym.off[off]] == val, f'{fn}: changed bytes {changed}, expected [{sym.off[off]}]')
    return 'algo/mode/velocity/accent/mute'


def m7_render(img, sym):
    """Every voice renders sound; render_sample is vtable[3]."""
    peaks = []
    for v in range(4):
        e = M7Emu(img.segment('m7').data, sym, img.segment('m4').data).boot_voices()
        e.set_params(v, [2048] * 4)
        e.set_algo_mode(v, 1, 0)
        e.trigger(v)
        peaks.append(max(map(abs, e.render(v, 3000))))
    need(all(p > 500 for p in peaks), f'peaks {peaks}')
    return f'peaks {peaks}'


def m7_extents(img, sym):
    """Each voice object's extent starts at its slot and contains all its param pointers."""
    e = M7Emu(img.segment('m7').data, sym, img.segment('m4').data).boot_voices()
    p = sym.g['params']
    for v, (lo, hi) in enumerate(sym.raw['slot_extents']):
        lo, hi = _h(lo), _h(hi)
        need(e.slot(v) == lo, f'voice {v + 1}: slot {e.slot(v):#x} != extent start {lo:#x}')
        n = sum(1 for o in range(lo, hi, 4) if p + 16 * v <= e.r32(o) < p + 16 * v + 16)
        need(n >= 4, f'voice {v + 1}: only {n} param pointers inside extent')
    return 'ok'


def m7_system(img, sym):
    """main() from its entry, its message loop and the audio callback; P2 reaches slots[3]."""
    e = M7System(img.segment('m7').data, sym, img.segment('m4').data).boot()
    got = [e.class_of(e.slot(i)) for i in range(4)]
    need(got == M7_CLASSES, f'slots after main wiring block: {got}')
    s3 = e.slot(3)
    e.send(3, 2, b'\x00\x01')
    e.pump()
    need(e.r8(s3 + sym.off['cFourthSlot.p2cfg']) == 1, 'type-2 {0,1} did not set P2 config')
    e.send_voice_state([{'params': [2048] * 4, 'algo': 1, 'mode': 0} for _ in range(4)])
    e.pump()
    e.send_triggers([1, 1, 1, 1], [(1, 0)] * 4)
    outs = e.audio(2048)
    peaks = [max(map(abs, o)) for o in outs]
    need(all(pk > 500 for pk in peaks), f'audio callback peaks {peaks}')
    return f'peaks {peaks}'


def m7_samples(img, sym):
    """A "samples ready" config message (type 3) reloads slots[3]'s sample player."""
    e = M7System(img.segment('m7').data, sym, img.segment('m4').data).boot()
    sp = e.slot(3) + sym.off['cFourthSlot.sampler'] + sym.off['cSamplePlayer.sample_ptr']
    e.w32(sp, 0)                     # clear it, so the message must be what sets it
    e.send(3, 3, b'\x01')
    try:
        e.pump()
    except RuntimeError as ex:
        raise CheckFailed('type-3 message not consumed by main (no runtime sample loading in this firmware?)') from ex
    need(e.r32(sp) != 0, 'type-3 {1} did not load samples into slots[3]')
    return 'ok'


def m7_statics(img, sym):
    """sampler / noise-crush render functions use their function-static globals."""
    from unicorn import UC_HOOK_MEM_WRITE
    e = M7System(img.segment('m7').data, sym, img.segment('m4').data).boot()
    hits = set()
    for name in ('sampler_static', 'crush_static'):
        a = sym.g[name]
        e.uc.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, addr, sz, v, n: hits.add(n), user_data=name, begin=a, end=a + 3)
    for algo, mode in ((2, 0), (1, 1)):
        e.send_voice_state([{'params': [2048, 2048, 600, 2048], 'algo': algo, 'mode': mode} for _ in range(4)])
        e.pump()
        e.send_triggers([0, 0, 0, 1], [(algo, mode)] * 4)
        e.audio(512)
    need(hits == {'sampler_static', 'crush_static'}, f'statics written: {sorted(hits)}')
    return 'ok'


def m7_rand(img, sym):
    """rand() is the shared noise source: pinning it makes noise renders repeatable."""
    def render():
        e = M7Emu(img.segment('m7').data, sym, img.segment('m4').data, freeze_rand=True).boot_voices()
        e.set_params(3, [2048] * 4)
        e.set_algo_mode(3, 0, 0)
        e.trigger(3)
        e.render(3, 64)
        return e.render(3, 1000)
    a, b = render(), render()
    need(a == b and max(map(abs, a)) > 0, 'frozen-rand renders differ or are silent')
    return 'ok'


# -- sites (both cores) -----------------------------------------------------------------

def sites(img, sym, seg):
    """Every named patch site contains what the symbols file says."""
    s_img = img.segment(seg)
    missing = [n for n in sym.sites if not sym.sites[n].get('addr')]
    need(not missing, f'unported sites: {", ".join(missing)}')
    for name in sym.sites:
        s = sym.site(name)
        off = s['addr'] - s_img.addr
        cur = s_img.data[off:off + 4]
        if 'call' in s:
            branch = bool(s.get('branch'))
            need(cur == thumb_bl(s['addr'], sym.fn[s['call']], link=not branch),
                 f'{name}: not {"b.w" if branch else "bl"} {s["call"]}')
        elif 'bytes' in s:
            need(s_img.data[off:off + len(s['bytes'])] == s['bytes'], f'{name}: bytes differ')
        elif 'word' in s:
            need(struct.unpack('<I', cur)[0] == s['word'], f'{name}: literal {cur.hex()}')
    return f'{len(sym.sites)} sites'


# -- M4 ---------------------------------------------------------------------------------

def m4_ipc(img, sym):
    """ipc_init sets up the rings; ipc_send queues a 0xC0FFEE message on a stream."""
    e = M4Emu(img.segment('m4').data, sym, img.segment('m7').data).boot()
    need(e.r8(sym.g['ipc_ready']) == 1, 'ipc ready flag not set')
    buf = sym.mem['bss_end']  # scratch in RAM
    e.uc.mem_write(buf, b'\x11\x22\x33\x44')
    e.call(sym.fn['ipc_send'], 3, buf, 4, 7)
    need(e.sent(3) == [(7, b'\x11\x22\x33\x44')], 'message not found on stream 3')
    return 'ok'


def m4_json(img, sym):
    """json_load parses device.json (from a virtual SD card) through the device schema."""
    sd = {'system/device.json': b'{"vintage-bbd": true, "midi-trig-note": {"voice1": 36, "voice4": 46}}'}
    e = M4Emu(img.segment('m4').data, sym, img.segment('m7').data, sd=sd).boot()
    path = sym.mem['bss_end']
    e.uc.mem_write(path, b'system/device.json\0')
    cfg = sym.g['device_config']
    ok = e.call(sym.fn['json_load'], path, sym.g['device_json_schema'], cfg)
    need(ok == 1, f'json_load returned {ok}')
    seg = img.segment('m4')
    schema = read_schema(Program(seg.data, seg.addr, {}), sym.g['device_json_schema'])
    need('vintage-bbd' in schema and 'midi-trig-note' in schema, f'schema keys: {sorted(schema)[:8]}...')
    need(e.r8(cfg + schema['vintage-bbd']) == 1, 'vintage-bbd not parsed')
    mt = schema['midi-trig-note']
    o1, o4 = mt['offset'] + mt['fields']['voice1'], mt['offset'] + mt['fields']['voice4']
    need([e.r8(cfg + o1), e.r8(cfg + o4)] == [36, 46], 'midi-trig-note not parsed')
    need(e.call(sym.fn['file_exists'], path) != 0, 'file_exists says no')
    return 'ok'


def m4_snprintf(img, sym):
    """snprintf formats like the bank paths need."""
    e = M4Emu(img.segment('m4').data, sym, img.segment('m7').data).boot()
    out, fmt = sym.mem['bss_end'], sym.mem['bss_end'] + 0x100
    e.uc.mem_write(fmt, b'BANKS/%02d/x\0')
    e.call(sym.fn['snprintf'], out, 64, fmt, 7)
    need(e.cstr(out) == 'BANKS/07/x', f'got {e.cstr(out)!r}')
    return 'ok'


M7_CHECKS = [m7_boot, m7_params, m7_setters, m7_render, m7_extents, m7_system, m7_samples, m7_statics, m7_rand]
M4_CHECKS = [m4_ipc, m4_json, m4_snprintf]


def run_all(img, sym_m7, sym_m4):
    results = []

    def run(name, fn, *a):
        try:
            results.append((name, True, fn(*a)))
        except Exception as ex:  # noqa: BLE001 -- every failure is a finding
            detail = str(ex) if isinstance(ex, CheckFailed) else f'{type(ex).__name__}: {ex}'
            if not isinstance(ex, (CheckFailed, KeyError, RuntimeError)):
                detail += '\n' + traceback.format_exc(limit=2)
            results.append((name, False, detail))
    for c in M7_CHECKS:
        run(c.__name__, c, img, sym_m7)
    run('m7_sites', sites, img, sym_m7, 'm7')
    for c in M4_CHECKS:
        run(c.__name__, c, img, sym_m4)
    run('m4_sites', sites, img, sym_m4, 'm4')
    return results
