#!/usr/bin/env python3
"""Quick Thumb-2 disassembler for raw Perkons segments.

usage: thumbdis.py <bin> <base> <start> [end|+len]   (addresses in hex)
Resolves PC-relative literal loads and annotates them with the loaded word.
"""
import struct, sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from capstone.arm import ARM_OP_MEM, ARM_REG_PC


def disasm(data, base, start, end):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    md.detail = True
    md.skipdata = True
    out = []
    for ins in md.disasm(data[start - base:end - base], start):
        note = ''
        if ins.mnemonic.startswith('ldr') and len(ins.operands) > 1:
            op = ins.operands[1]
            if op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC:
                lit = ((ins.address + 4) & ~3) + op.mem.disp
                if base <= lit < base + len(data) - 3:
                    note = f'  ; [{lit:08x}] = {struct.unpack_from("<I", data, lit - base)[0]:08x}'
        out.append(f'{ins.address:08x}: {ins.bytes.hex():<10} {ins.mnemonic:<8} {ins.op_str}{note}')
    return out


if __name__ == '__main__':
    fn, base, start, end = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16), sys.argv[4]
    end = start + int(end[1:], 16) if end.startswith('+') else int(end, 16)
    print('\n'.join(disasm(open(fn, 'rb').read(), base, start & ~1, end)))
