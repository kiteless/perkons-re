"""Flash for mod code: a fixed budget per core.

  m4code  the M4 host + M4 mods: right after the M4 firmware, at most CODE['m4']
  m7code  the M7 host + M7 mods: right after the M7 firmware, at most CODE['m7']

Each core keeps its own flash region: the M7's in bank 1 (after the bootloader), the M4's
in bank 2. A region is cut into the firmware (at most FIRMWARE_MAX, whole 128 KB sectors
with room for Erica's firmware to grow) and the mods' code budget, so the budgets hold for
any firmware version under its ceiling (check_firmware; the porter refuses one that
isn't). The rest of bank 2 is unassigned.

Each host records the code it links by source (record_linked) under its area, with the RAM
(Patcher.ram): the manifests, the per-option figures and the Mod Matrix (its FLASH meter,
block(); an option that would overrun a budget can't be ticked) take it from there like RAM. The linker region is exactly the budget, so the build refuses code
that doesn't fit.
"""
import os
import re

SECTOR = 0x20000
BANKS = {1: (0x08000000, 0x08100000), 2: (0x08100000, 0x08200000)}
REGIONS = {'m7': (0x08020000, 0x08100000), 'm4': BANKS[2]}       # each core's segment
BANK = {'m7': 1, 'm4': 2}
FIRMWARE_MAX = {'m7': 6 * SECTOR, 'm4': 2 * SECTOR}   # 768 KB, 256 KB (1.3.0: 713 KB, 181 KB)
CODE = {'m7': SECTOR, 'm4': 2 * SECTOR}               # 128 KB, 256 KB
AREAS = ('m4code', 'm7code')
AREA = {'m4': 'm4code', 'm7': 'm7code'}

for _core, (_lo, _hi) in REGIONS.items():
    assert _lo + FIRMWARE_MAX[_core] + CODE[_core] <= _hi


def check_firmware(img):
    """Error text if this firmware's segments are too big for the layout, else None."""
    for s in img.segments:
        lo, hi = REGIONS[s.name]
        if s.addr != lo:
            return f'{s.name} firmware at {s.addr:#x}, expected {lo:#x}'
        if len(s.data) > FIRMWARE_MAX[s.name]:
            return (f'{s.name} firmware is {len(s.data)} B, over the {FIRMWARE_MAX[s.name]} B the flash layout '
                    f'leaves it (tools/perkons/flash.py)')
    return None


def code_origin(p, core):
    """Where the core's host links its code: right after what's in its segment."""
    return p.cave_origin(core)


def block(fw_end):
    """The FLASH meter's block: all 2 MB, cut in address order into ranges [(owner, start,
    end)] that tile it. The mods' code budgets are named by their area (m7code, m4code);
    everything else is the firmware's or unassigned. fw_end: {core: where its firmware ends}."""
    ranges = []
    for core in ('m7', 'm4'):
        blo, bhi = BANKS[BANK[core]]
        lo, end = REGIONS[core][0], fw_end[core]
        if lo > blo:
            ranges.append(('bootloader', blo, lo))
        ranges += [(f'{core.upper()} firmware', lo, end), (AREA[core], end, end + CODE[core]),
                   ('unassigned' if core == 'm4' else 'firmware growth', end + CODE[core], bhi)]
    return {'name': 'flash', 'start': BANKS[1][0], 'end': BANKS[2][1], 'ranges': ranges}


def areas(fw_end):
    """{area: (start, end)}: the mods' part of each."""
    return {AREA[core]: (fw_end[core], fw_end[core] + CODE[core]) for core in AREA}


def code_placed(build_dir):
    """{source: [(addr, size)]} for the code and constants (.text*, .rodata*) the last
    build in build_dir linked, from its map."""
    import json
    with open(os.path.join(build_dir, 'objects.json')) as f:
        objs = json.load(f)
    with open(os.path.join(build_dir, 'cave.elf.map')) as f:
        text = f.read().partition('Linker script and memory map')[2]
    out = {}
    for name, addr, size, obj in re.findall(r'^ (\.(?:text|rodata)\S*)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(.+\.o)$',
                                            text, re.M):
        if int(size, 16):
            out.setdefault(objs.get(obj, obj), []).append((int(addr, 16), int(size, 16)))
    return out


def record_linked(p, core, build_dir, blob_len):
    """Record the code the core's host linked, by source: each section up to the next (so
    alignment counts and the owners add up to the blob). Generated sources are named by
    their file only, so every build names them alike."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    rows = sorted((a, n, src) for src, secs in code_placed(build_dir).items() for a, n in secs)
    if not rows:
        return
    end = rows[0][0] + blob_len
    gen = os.path.join(os.path.abspath(build_dir), 'gen')
    owners = {}
    for (addr, size, src), following in zip(rows, rows[1:] + [None]):
        taken = (following[0] if following else end) - addr
        if os.path.abspath(src).startswith(gen + os.sep):
            owner = f'{core}host:gen/{os.path.basename(src)}:code'
        else:
            owner = f'{os.path.relpath(src, root)}:code'
        owners[owner] = owners.get(owner, 0) + taken
    for owner, size in owners.items():
        p.ram_use(AREA[core], owner, size)
