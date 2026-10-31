"""Instruction sites by their assembly text, not their bytes.

A symbols site may name the instruction(s) it expects as text ("insn": "strb.w r3, [r2,
#0xc6d]", several joined with "; "). The bytes are read from the firmware image being
patched and accepted only if they disassemble to that text, so no firmware bytes need to
be stored anywhere."""
from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs

_md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)


def norm(text):
    return '; '.join(' '.join(part.split()).lower() for part in text.split(';') if part.strip())


def disasm(data, addr, n_insns):
    """(normalized text, byte length) of the first n_insns instructions of data at addr."""
    insns = list(_md.disasm(data, addr, count=n_insns))
    return norm('; '.join(f'{i.mnemonic} {i.op_str}'.strip() for i in insns)), sum(i.size for i in insns)


def expect(seg_data, seg_addr, addr, text):
    """The bytes at addr if they are the instruction(s) `text`, else None."""
    want = norm(text)
    n = want.count(';') + 1
    off = addr - seg_addr
    got, size = disasm(bytes(seg_data[off:off + 4 * n + 4]), addr, n)
    return bytes(seg_data[off:off + size]) if got == want else None
