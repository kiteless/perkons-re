"""RAM that mods can use: three areas, named as the Mod Matrix shows them.

  main    M4 D2 SRAM patch RAM: the M4 host's .bss (fast; per-sample audio state)
  voice   M7 DTCM between the newlib heap cap and a stack reserve (M7 mods only)
  store   AXI SRAM gap: the M4 host's PK_AXI variables (settings, bulk data)

Patches record what they take with Patcher.ram_use(area, owner, size, addr); each core's host
records each RAM section it links (by source), a mod with fixed M7 addresses its range. Owners
are names, so two options that share one (the FX buffer) count it once when combined.
Patcher.finish() refuses a build that doesn't fit (check()).

Each area is the mods' part of a physical RAM block (blocks()): the rest of the block is
the firmware's own, in named ranges (STOCK), and the Mod Matrix draws the whole block. A
mod that takes over one of those ranges (STEP SAMPLER: the stock custom-sample pool)
records it with Patcher.ram_takeover(area, stock name, owner): it shows as that mod's,
and the mods' part is unchanged. A mod that uses a firmware buffer for a moment
(BORROWABLE: the JSON buffer) records it with Patcher.ram_borrow: no cost, but listed.

Every build leaves its RAM map (ram_map, save_map: found by its changed segments), and the
emulator watches writes with it (emu.CoreEmu): what wasn't recorded can't be written.
"""
from . import m4host

AREAS = ('main', 'voice', 'store')

# v1.3.0: the M7 newlib heap (rand state, a few dozen bytes) keeps the ~16 KB below
# VOICE_BASE, where voice-map caps it. The M7 stack's deepest use (main loop with the audio
# interrupt on top) is under 1 KB and stock protects 1 KB; VOICE_STACK keeps 4 KB.
VOICE_BASE = 0x2000c000
VOICE_STACK = 0x1000


# the physical blocks (STM32H745/H747/H755), as each area's core addresses them
BLOCKS = {'main': ('D2 SRAM', 0x10000000, 0x10048000),
          'voice': ('M7 DTCM', 0x20000000, 0x20020000),
          'store': ('AXI SRAM', 0x24000000, 0x24080000)}

# the firmware's own ranges in each block (stock names; the mods' area fills the rest)
STOCK = {'main': ('.data', '.bss', 'heap', 'audio buffer + stack'),
         'voice': ('.data + .bss: the voice engines', 'heap', 'stack'),
         'store': ('file system + JSON', 'default custom samples')}


# the firmware's ranges whose memory is reserved rather than working state: mod code may
# write them only where it took the range over (ram_takeover) or borrows a buffer in it
GUARDED = {'store': ('file system + JSON', 'default custom samples')}

# firmware buffers a mod may borrow for a moment (Patcher.ram_borrow): area -> name ->
# symbols -> (start, end)
BORROWABLE = {'store': {'json_buf': lambda s: (s['m4'].g['json_buf'],
                                               s['m4'].g['json_buf'] + s['m4'].const['json_buf_size'])}}


def blocks(symbols):
    """{area: {'name', 'start', 'end', 'ranges': [(owner, start, end)]}}: each physical block
    cut, in address order, into the firmware's ranges (named as in STOCK) and the mods'
    area ('mods'). The ranges cover the block exactly."""
    m4, m7 = symbols['m4'], symbols['m7']
    a = areas(symbols)
    cuts = {
        'main': [('.data', m4.mem['data_start'], m4.mem['data_end']),
                 ('.bss', m4.mem['data_end'], m4.mem['bss_end']),
                 ('heap', m4.mem['bss_end'], a['main'][0]),
                 ('mods', *a['main']),
                 ('audio buffer + stack', a['main'][1], BLOCKS['main'][2])],
        'voice': [('.data + .bss: the voice engines', BLOCKS['voice'][1], m7.mem['bss_end']),
                  ('heap', m7.mem['bss_end'], a['voice'][0]),
                  ('mods', *a['voice']),
                  ('stack', a['voice'][1], BLOCKS['voice'][2])],
        'store': [('file system + JSON', BLOCKS['store'][1], a['store'][0]),
                  ('mods', *a['store']),
                  ('default custom samples', a['store'][1], BLOCKS['store'][2])],
    }
    out = {}
    for area, ranges in cuts.items():
        name, lo, hi = BLOCKS[area]
        assert ranges[0][1] == lo and ranges[-1][2] == hi and all(
            r[2] == n[1] for r, n in zip(ranges, ranges[1:])), f'{area}: ranges must tile {name}'
        assert [r[0] for r in ranges if r[0] != 'mods'] == list(STOCK[area])
        out[area] = {'name': name, 'start': lo, 'end': hi, 'ranges': ranges}
    return out


def areas(symbols):
    """{area: (start, end)} for this firmware; symbols = {'m4': Symbols, 'm7': Symbols}."""
    return {'main': (m4host.RAM_BASE, m4host.RAM_END),
            'voice': (VOICE_BASE, symbols['m7'].mem['stack_top'] - VOICE_STACK),
            'store': m4host.axi_gap(symbols['m4'])}


def record_linked(p, build_dir, area_of):
    """Record every RAM section the build in build_dir linked, at its address: each one up to
    the next in its area (so padding counts and no two overlap). area_of(section) -> area."""
    import os
    from . import cbuild
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    placed = {}
    for (src, section), (addr, size) in cbuild.ram_placed(build_dir).items():
        placed.setdefault(area_of(section), []).append((addr, size, src, section))
    for area, rows in placed.items():
        rows.sort()
        for (addr, size, src, section), following in zip(rows, rows[1:] + [None]):
            taken = following[0] - addr if following else (size + 3) & ~3
            p.ram_use(area, f'{os.path.relpath(src, root)}:{section}', taken, addr)


def totals(use):
    """use = {area: {owner: (addr, size)}} -> {area: bytes}."""
    return {a: sum(size for _, size in use.get(a, {}).values()) for a in AREAS}


def check(use, symbols):
    """Error text for the first area that's over, or a fixed range outside its area or
    overlapping another owner's; None if it all fits."""
    bounds = areas(symbols)
    for a in AREAS:
        lo, hi = bounds[a]
        own = use.get(a, {})
        used = sum(size for _, size in own.values())
        if used > hi - lo:
            return f'out of memory in {a.upper()}: {used} B needed, {hi - lo} B available'
        fixed = sorted((addr, addr + size, o) for o, (addr, size) in own.items() if addr is not None)
        for s, e, o in fixed:
            if s < lo or e > hi:
                return f'{o} uses {s:#x}-{e:#x}, outside {a.upper()} ({lo:#x}-{hi:#x})'
        for (_, e1, o1), (s2, _, o2) in zip(fixed, fixed[1:]):
            if s2 < e1:
                return f'{o1} and {o2} overlap in {a.upper()}'
    return None


# -- the RAM map each build leaves for the emulator's watch (emu.CoreEmu) ----------------

def ram_map(p):
    """What the build may write, from what its patches recorded: {areas: {area: [lo, hi]},
    used: [[lo, hi, owner]], guarded: [[lo, hi, name]], allowed: [[lo, hi, owner]],
    caves: [[lo, hi]]} (allowed: takeovers and borrows, inside the guarded ranges)."""
    bounds = areas(p.symbols)
    blk = blocks(p.symbols)
    used = sorted([addr, addr + size, owner] for own in p.ram.values() for owner, (addr, size) in own.items()
                  if addr is not None and size)
    stock = {(a, o): (s, e) for a, b in blk.items() for o, s, e in b['ranges']}
    guarded = sorted([*stock[(a, n)], n] for a, names in GUARDED.items() for n in names)
    allowed = [[*stock[(a, n)], o] for a, t in p.ram_takeovers.items() for n, o in t.items()]
    allowed += [[*BORROWABLE[a][b](p.symbols), ','.join(o)] for a, t in p.ram_borrows.items() for b, o in t.items()]
    caves = [[s.addr + p._orig_len[s.name], s.addr + len(p._data[s.name])] for s in p.img.segments
             if len(p._data[s.name]) > p._orig_len[s.name]]
    return {'areas': {a: list(v) for a, v in bounds.items()}, 'used': used, 'guarded': guarded,
            'allowed': sorted(allowed), 'caves': caves}


def _map_path(seg_bytes):
    import hashlib
    from . import srchash
    return srchash.path('rammap', hashlib.sha256(seg_bytes).hexdigest()[:32], '.json')


def save_map(p, img):
    """Keep the build's RAM map, found by each of its segments (load_map)."""
    import json
    import os
    if not getattr(p, 'symbols', None) or not p.ram:
        return                                  # a hand patch: nothing recorded, nothing watched
    text = json.dumps(ram_map(p))
    stock = {seg.name: seg.data for seg in p.img.segments}
    for seg in img.segments:
        if seg.data == stock.get(seg.name):
            continue                            # unchanged: a stock segment has no map
        path = _map_path(seg.data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f'{path}.{os.getpid()}.tmp'       # parallel test processes may build the same image
        with open(tmp, 'w') as f:
            f.write(text)
        os.replace(tmp, path)


def load_map(seg_bytes):
    """The RAM map of the build a segment came from, or None (stock, or not built here)."""
    import json
    import os
    path = _map_path(seg_bytes)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
