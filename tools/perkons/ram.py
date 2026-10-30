"""RAM that mods can use: three areas, named as the Mod Matrix shows them.

  main    M4 D2 SRAM patch RAM: the M4 host's .bss (fast; per-sample audio state)
  voice   M7 DTCM between the newlib heap cap and a stack reserve (M7 mods only)
  store   AXI SRAM gap: the M4 host's PK_AXI variables (settings, bulk data)

Patches record what they take with Patcher.ram_use(area, owner, size, addr); the M4 host
records each RAM section it links (by source), a mod with fixed M7 addresses its range. Owners
are names, so two options that share one (the FX buffer) count it once when combined.
Patcher.finish() refuses a build that doesn't fit (check()).
"""
from . import m4host

AREAS = ('main', 'voice', 'store')

# v1.3.0: the M7 newlib heap (rand state, a few dozen bytes) keeps the ~16 KB below
# VOICE_BASE, where voice-map caps it. The M7 stack's deepest use (main loop with the audio
# interrupt on top) is under 1 KB and stock protects 1 KB; VOICE_STACK keeps 4 KB.
VOICE_BASE = 0x2000c000
VOICE_STACK = 0x1000


def areas(symbols):
    """{area: (start, end)} for this firmware; symbols = {'m4': Symbols, 'm7': Symbols}."""
    return {'main': (m4host.RAM_BASE, m4host.RAM_END),
            'voice': (VOICE_BASE, symbols['m7'].mem['stack_top'] - VOICE_STACK),
            'store': m4host.axi_gap(symbols['m4'])}


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
