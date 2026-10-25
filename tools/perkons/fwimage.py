"""Perkons HD-01 firmware update image (.img) container.

Layout (reverse engineered from v1.1.1 / v1.2.1 / v1.3.0):

    varint  header_len
    bytes   header            protobuf message, see below
    bytes   segment[0] data   concatenated, in header order
    bytes   segment[1] data   ...

Header (proto3, zero-valued fields omitted on the wire):

    message Header {
      string  product = 1;              // "Perkons"
      uint32  field2  = 2;              // always 2 (format/hardware revision?)
      Version version = 3;
      repeated Segment segment = 4;
    }
    message Version { uint32 major = 1; uint32 minor = 2; uint32 patch = 3; string git = 4; }
    message Segment {
      uint32 core  = 1;                 // 0 = Cortex-M4 (0x08100000), 1 = Cortex-M7 (0x08020000)
      uint32 addr  = 2;                 // flash load address
      uint32 size  = 3;
      uint32 crc32 = 4;                 // zlib.crc32 of the segment bytes
    }

The STM32H7 bootloader at 0x08000000 (not part of the update) applies the image.
"""
import zlib
from dataclasses import dataclass, field
from typing import List, Optional

CORE_NAMES = {0: 'm4', 1: 'm7'}


# --- minimal protobuf wire helpers -------------------------------------------------

def _read_varint(buf, i):
    result = shift = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if b < 0x80:
            return result, i


def _varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _fields(buf):
    i = 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            val, i = _read_varint(buf, i)
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            val = bytes(buf[i:i + ln])
            i += ln
        else:
            raise ValueError(f'unsupported wire type {wt} for field {num}')
        yield num, wt, val


def _enc_uint(num, v):
    return _varint(num << 3) + _varint(v) if v else b''


def _enc_bytes(num, v):
    return _varint((num << 3) | 2) + _varint(len(v)) + v if v else b''


# --- model ---------------------------------------------------------------------------

@dataclass
class Segment:
    core: int
    addr: int
    data: bytes
    crc32: int = 0  # as stored in the header

    @property
    def name(self):
        return CORE_NAMES.get(self.core, f'core{self.core}')

    @property
    def crc_ok(self):
        return zlib.crc32(self.data) == self.crc32


@dataclass
class Image:
    product: str = 'Perkons'
    field2: int = 2
    major: int = 0
    minor: int = 0
    patch: int = 0
    git: str = ''
    segments: List[Segment] = field(default_factory=list)

    @property
    def version(self):
        return f'{self.major}.{self.minor}.{self.patch}'

    def segment(self, name_or_core) -> Optional[Segment]:
        for s in self.segments:
            if s.name == name_or_core or s.core == name_or_core:
                return s
        return None

    # -- parse ------------------------------------------------------------------------
    @classmethod
    def parse(cls, raw: bytes) -> 'Image':
        hlen, off = _read_varint(raw, 0)
        hdr = raw[off:off + hlen]
        off += hlen
        img = cls(product='', field2=0)
        seg_meta = []
        for num, _, val in _fields(hdr):
            if num == 1:
                img.product = val.decode()
            elif num == 2:
                img.field2 = val
            elif num == 3:
                for n, _, v in _fields(val):
                    if n == 1:
                        img.major = v
                    elif n == 2:
                        img.minor = v
                    elif n == 3:
                        img.patch = v
                    elif n == 4:
                        img.git = v.decode()
            elif num == 4:
                m = {1: 0, 2: 0, 3: 0, 4: 0}
                for n, _, v in _fields(val):
                    m[n] = v
                seg_meta.append(m)
        for m in seg_meta:
            data = raw[off:off + m[3]]
            if len(data) != m[3]:
                raise ValueError('image truncated')
            off += m[3]
            img.segments.append(Segment(core=m[1], addr=m[2], data=bytes(data), crc32=m[4]))
        if off != len(raw):
            raise ValueError(f'{len(raw) - off} trailing bytes after last segment')
        return img

    @classmethod
    def load(cls, path) -> 'Image':
        with open(path, 'rb') as f:
            return cls.parse(f.read())

    # -- build ------------------------------------------------------------------------
    def build(self, recompute_crc=True) -> bytes:
        ver = (_enc_uint(1, self.major) + _enc_uint(2, self.minor) + _enc_uint(3, self.patch)
               + _enc_bytes(4, self.git.encode()))
        hdr = _enc_bytes(1, self.product.encode()) + _enc_uint(2, self.field2) + _enc_bytes(3, ver)
        for s in self.segments:
            if recompute_crc:
                s.crc32 = zlib.crc32(s.data)
            seg = _enc_uint(1, s.core) + _enc_uint(2, s.addr) + _enc_uint(3, len(s.data)) + _enc_uint(4, s.crc32)
            hdr += _enc_bytes(4, seg)
        return _varint(len(hdr)) + hdr + b''.join(s.data for s in self.segments)

    def save(self, path, recompute_crc=True):
        with open(path, 'wb') as f:
            f.write(self.build(recompute_crc))

    def describe(self):
        lines = [f'{self.product} v{self.version} ({self.git})  field2={self.field2}']
        for s in self.segments:
            lines.append(f'  {s.name}: addr=0x{s.addr:08x} size=0x{len(s.data):x} ({len(s.data)} B) '
                         f'end=0x{s.addr + len(s.data):08x} crc32=0x{s.crc32:08x} '
                         f'{"OK" if s.crc_ok else "MISMATCH"}')
        return '\n'.join(lines)
