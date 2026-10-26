"""Safe binary patching of Perkons firmware images.

Rules this enforces:
  * every write states the bytes it expects to replace; a mismatch aborts the build,
    so a patch can never be applied to the wrong firmware version
  * writes must stay inside a segment's existing data, or in a declared code cave
    appended to the segment (never the bootloader at 0x08000000-0x0801ffff, never
    across into the other core's bank)
  * the header (product, version, git hash) is carried over unchanged; only segment
    data and CRCs change
"""
import struct
from dataclasses import dataclass
from typing import List

from .fwimage import Image

BOOTLOADER_END = 0x08020000
# Flash bank limits per core: M7 app may grow up to the start of bank 2 (M4 app).
SEGMENT_LIMITS = {'m7': (0x08020000, 0x08100000), 'm4': (0x08100000, 0x08200000)}


class PatchError(Exception):
    pass


@dataclass
class Change:
    seg: str
    addr: int
    old: bytes
    new: bytes
    why: str


class Patcher:
    def __init__(self, img: Image):
        self.img = img
        self.changes: List[Change] = []
        self._data = {s.name: bytearray(s.data) for s in img.segments}
        self._orig_len = {s.name: len(s.data) for s in img.segments}
        self._finishers = []
        # patches that cooperate register with each other here, by agreed keys (e.g. a
        # mod offering extra engines to another mod), without importing each other
        self.shared = {}

    # -- primitives ------------------------------------------------------------------
    def _seg(self, name):
        s = self.img.segment(name)
        if s is None:
            raise PatchError(f'no segment {name}')
        return s

    def read(self, seg, addr, n):
        s = self._seg(seg)
        off = addr - s.addr
        return bytes(self._data[seg][off:off + n])

    def write(self, seg, addr, new: bytes, expect: bytes, why: str):
        """Replace `expect` at `addr` with `new` (same length)."""
        if len(new) != len(expect):
            raise PatchError(f'{why}: length mismatch {len(new)} != {len(expect)}')
        s = self._seg(seg)
        if addr < BOOTLOADER_END:
            raise PatchError(f'{why}: refusing to touch bootloader region @{addr:08x}')
        off = addr - s.addr
        if off < 0 or off + len(new) > len(self._data[seg]):
            raise PatchError(f'{why}: {addr:08x} outside {seg} segment')
        cur = bytes(self._data[seg][off:off + len(new)])
        if cur != expect:
            raise PatchError(f'{why}: expected {expect.hex()} at {addr:08x}, found {cur.hex()} '
                             f'(wrong firmware version, or patch already applied?)')
        self._data[seg][off:off + len(new)] = new
        self.changes.append(Change(seg, addr, cur, new, why))

    def write_u32(self, seg, addr, new, expect, why):
        self.write(seg, addr, struct.pack('<I', new), struct.pack('<I', expect), why)

    def append(self, seg, blob: bytes, why: str, align=4) -> int:
        """Append blob to the end of a segment (code cave); returns its flash address."""
        s = self._seg(seg)
        d = self._data[seg]
        while len(d) % align:
            d.append(0xFF)
        addr = s.addr + len(d)
        lo, hi = SEGMENT_LIMITS[seg]
        if addr + len(blob) > hi:
            raise PatchError(f'{why}: cave would cross into the next bank')
        d.extend(blob)
        self.changes.append(Change(seg, addr, b'', blob, why + ' [cave]'))
        return addr

    # -- symbol-aware patching (patches should use these, not raw addresses) -------------
    # They need self.symbols = {'m4': Symbols, 'm7': Symbols} (tools/build.py sets it).

    def site(self, seg, name):
        return self.symbols[seg].site(name)

    def redirect_call(self, seg, site, new_target, why):
        """Site is `bl <fn>`: make it `bl new_target`."""
        s = self.site(seg, site)
        old = self.symbols[seg].fn[s['call']]
        self.write(seg, s['addr'], thumb_bl(s['addr'], new_target), thumb_bl(s['addr'], old), why)

    def replace_with_call(self, seg, site, new_target, why):
        """Site is a 4-byte instruction (`bytes`): replace it with `bl new_target`."""
        s = self.site(seg, site)
        if len(s['bytes']) != 4:
            raise PatchError(f'{site}: can only replace a 4-byte instruction with a bl')
        self.write(seg, s['addr'], thumb_bl(s['addr'], new_target), s['bytes'], why)

    def replace_word(self, seg, site, new, why):
        """Site is a literal (`word`): replace its value."""
        s = self.site(seg, site)
        self.write_u32(seg, s['addr'], new, s['word'], why)

    def cave_origin(self, seg, align=16):
        """Address the next append() to this segment will land at."""
        s = self._seg(seg)
        return (s.addr + len(self._data[seg]) + align - 1) & ~(align - 1)

    # -- deferred steps --------------------------------------------------------------
    def on_finish(self, fn):
        """Run fn() once, after every patch has been applied (e.g. a shared build that
        several patches register into, like the M4 host)."""
        self._finishers.append(fn)

    def finish(self):
        while self._finishers:
            self._finishers.pop(0)()

    # -- output ----------------------------------------------------------------------
    def result(self) -> Image:
        self.finish()
        out = Image(product=self.img.product, field2=self.img.field2, major=self.img.major,
                    minor=self.img.minor, patch=self.img.patch, git=self.img.git)
        for s in self.img.segments:
            out.segments.append(type(s)(core=s.core, addr=s.addr, data=bytes(self._data[s.name])))
        out.build()  # computes CRCs
        return out

    def report(self):
        lines = []
        for c in self.changes:
            lines.append(f'  {c.seg} {c.addr:08x} +{len(c.new):<5} {c.why}')
            if c.old:
                lines.append(f'      {c.old.hex()} -> {c.new.hex()}')
        for name, n in self._orig_len.items():
            grown = len(self._data[name]) - n
            if grown:
                lines.append(f'  {name}: segment grew by {grown} bytes')
        return '\n'.join(lines)


# -- Thumb-2 encoders (enough for small hand patches; use a real toolchain for code caves) --

def thumb_bl(src, dst, link=True):
    """Encode BL (or B.W when link=False) at src jumping to dst."""
    off = (dst & ~1) - (src + 4)
    if not -(1 << 24) <= off < (1 << 24):
        raise PatchError('branch out of range')
    s = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
    hw1 = 0xF000 | (s << 10) | ((off >> 12) & 0x3FF)
    hw2 = (0xD000 if link else 0x9000) | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF)
    return struct.pack('<HH', hw1, hw2)


def thumb_str_imm(rt, rn, imm):
    """16-bit STR Rt, [Rn, #imm] (low regs, imm multiple of 4, <= 124)."""
    assert rt < 8 and rn < 8 and imm % 4 == 0 and 0 <= imm <= 124
    return struct.pack('<H', 0x6000 | ((imm // 4) << 6) | (rn << 3) | rt)
