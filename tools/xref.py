#!/usr/bin/env python3
"""Find references to an address in a raw Thumb-2 segment.

usage: xref.py <bin> <base> <addr> [<addr> ...]
Reports literal-pool words equal to addr (or addr|1) and BL/B.W branch sites targeting it.
"""
import struct, sys


def literal_refs(data, base, value):
    out = []
    for i in range(0, len(data) - 3, 2):
        w = struct.unpack_from('<I', data, i)[0]
        if w in (value, value | 1):
            out.append(base + i)
    return out


def decode_bl(hw1, hw2, pc):
    """Decode a Thumb-2 BL / B.W (T4) pair. Returns (kind, target) or None."""
    if (hw1 & 0xF800) != 0xF000:
        return None
    if (hw2 & 0xD000) == 0xD000:
        kind = 'bl'
    elif (hw2 & 0xD000) == 0x9000:
        kind = 'b.w'
    else:
        return None
    s = (hw1 >> 10) & 1
    j1, j2 = (hw2 >> 13) & 1, (hw2 >> 11) & 1
    i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((hw1 & 0x3FF) << 12) | ((hw2 & 0x7FF) << 1)
    if s:
        imm -= 1 << 25
    return kind, pc + 4 + imm


def branch_refs(data, base, target):
    out = []
    target &= ~1
    for i in range(0, len(data) - 3, 2):
        hw1, hw2 = struct.unpack_from('<HH', data, i)
        r = decode_bl(hw1, hw2, base + i)
        if r and r[1] == target:
            out.append((base + i, r[0]))
    return out


if __name__ == '__main__':
    data = open(sys.argv[1], 'rb').read()
    base = int(sys.argv[2], 16)
    for a in sys.argv[3:]:
        v = int(a, 16)
        lits = literal_refs(data, base, v)
        brs = branch_refs(data, base, v)
        print(f'{v:08x}: literals={[hex(x) for x in lits]} branches={[(hex(x), k) for x, k in brs]}')
