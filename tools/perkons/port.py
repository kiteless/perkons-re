"""Port a symbols file from one firmware version to another.

Function matching, strongest evidence first:
  1. exact normalized fingerprints (instruction stream with addresses abstracted away,
     strings kept as text, constants kept), unique in both images
  2. anchors: C++ RTTI vtables (class name -> methods by index), the vector table
  3. propagation: in each matched pair, aligned instructions pair up callees and the
     addresses they load (globals, strings, data sections, function pointers)
  4. fuzzy: best remaining similarity above a threshold

Everything in the symbols file is then re-derived: functions from the function map,
globals / memory / extents from the address map, sites and main_points by aligning the
instruction streams of the function that contains them. Each value records how it was
found. The result must still pass tools/check_symbols.py; that's the real acceptance test.
"""
import bisect
import collections
import difflib
import json
import re
import struct

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC

RAM_RANGES = [(0x10000000, 0x10050000), (0x20000000, 0x20020000), (0x24000000, 0x24080000),
              (0x30000000, 0x30050000), (0x38000000, 0x38010000)]
FLASH = (0x08000000, 0x08200000)
BRANCHES = {'b', 'bl', 'blx', 'b.w', 'cbz', 'cbnz'}
_REG = re.compile(r'\b(r\d+|sb|sl|fp|ip|s\d+|d\d+)\b')
_REGLIST = re.compile(r'\{[^}]*\}')


def coarse(tok):
    """Register-agnostic token: different compilers allocate registers differently."""
    return _REG.sub('R', _REGLIST.sub('{..}', tok))


def _h(v):
    return int(v, 16) if isinstance(v, str) else v


def is_ram(v):
    return any(lo <= v < hi for lo, hi in RAM_RANGES)


def is_flash(v):
    return FLASH[0] <= v < FLASH[1]


class Insn:
    __slots__ = ('addr', 'size', 'mn', 'tok', 'call', 'lit_addr', 'lit', 'raw')

    def __init__(self, addr, size, mn, tok, raw):
        self.addr, self.size, self.mn, self.tok, self.raw = addr, size, mn, tok, raw
        self.call = None        # absolute target of bl/b.w out of the function
        self.lit_addr = None    # pool slot address for pc-relative loads
        self.lit = None         # value loaded


class Program:
    """One core of one firmware version: bytes, functions (from Ghidra) and decoded insns."""

    def __init__(self, data, base, functions):
        self.data, self.base = data, base
        self.md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        self.md.detail = True
        self.funcs = {int(k): v for k, v in functions.items()}
        self.entries = sorted(self.funcs)
        self.insns = {}
        self.fp = {}      # exact tokens: function fingerprints
        self.cfp = {}     # coarse tokens: alignment inside matched pairs, fuzzy matching
        for e in self.entries:
            self._index(e)

    def _index(self, e):
        self.insns[e] = self._decode(e)
        self.fp[e] = tuple(i.tok for i in self.insns[e])
        self.cfp[e] = tuple(coarse(t) for t in self.fp[e])

    def u32(self, a):
        o = a - self.base
        return struct.unpack_from('<I', self.data, o)[0] if 0 <= o <= len(self.data) - 4 else None

    def cstr(self, a):
        o = a - self.base
        if not 0 <= o < len(self.data):
            return None
        end = self.data.find(b'\0', o, o + 128)
        s = self.data[o:end] if end > o else b''
        if len(s) >= 3 and all(32 <= c < 127 or c in (9, 10, 13) for c in s):
            return s.decode()
        return None

    def _lit_token(self, v):
        if v is None:
            return 'LIT?'
        s = self.cstr(v) if is_flash(v) else None
        if s:
            return 'STR:' + s
        if is_flash(v):
            return 'FN' if v & 1 else 'FLASH'
        if is_ram(v):
            return 'RAM'
        return f'{v:#x}'

    def _decode(self, entry):
        out = []
        f = self.funcs[entry]
        lo_fn = min(r[0] for r in f['body'])
        hi_fn = max(r[1] for r in f['body'])
        for lo, hi in sorted(f['body']):
            code = self.data[lo - self.base:hi - self.base]
            for ins in self.md.disasm(code, lo):
                mn = ins.mnemonic
                tok = mn
                insn = Insn(ins.address, ins.size, mn, None, bytes(ins.bytes))
                ops = ins.operands
                if mn.split('.')[0] in BRANCHES or (mn.startswith('b') and len(mn) <= 5 and ops and ops[-1].type == ARM_OP_IMM):
                    t = ops[-1].imm if ops and ops[-1].type == ARM_OP_IMM else None
                    regs = ins.op_str.rsplit(',', 1)[0] if mn in ('cbz', 'cbnz') else ''
                    if t is not None and not (lo_fn <= t < hi_fn):
                        insn.call = t
                        tok = f'{mn} F'
                    else:
                        tok = f'{mn} {regs} L'
                elif len(ops) >= 2 and ops[-1].type == ARM_OP_MEM and ops[-1].mem.base == ARM_REG_PC:
                    la = ((ins.address + 4) & ~3) + ops[-1].mem.disp
                    insn.lit_addr = la
                    insn.lit = self.u32(la)
                    dst = ins.op_str.split(',')[0]
                    tok = f'{mn} {dst}, {self._lit_token(insn.lit) if mn.startswith("ldr") else "LITF"}'
                elif mn in ('adr', 'adr.w') or (mn.startswith('add') and 'pc' in ins.op_str):
                    tok = f'{mn} {ins.op_str.split(",")[0]}, REL'
                else:
                    tok = f'{mn} {ins.op_str}'
                insn.tok = tok
                out.append(insn)
        return out

    def ensure_function(self, entry, max_len=0x1000):
        """Make `entry` a function if Ghidra didn't: decode linearly until a return with no
        pending forward branch inside, then fingerprint it like the rest."""
        if entry in self.funcs:
            return True
        if not is_flash(entry):
            return False
        # Note: entry may lie inside a function Ghidra merged with its neighbour; we create
        # it anyway (overlapping bodies are fine for matching).
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
        md.detail = True
        end, pending, last_end_ok = entry, set(), False
        for ins in md.disasm(self.data[entry - self.base:entry - self.base + max_len], entry):
            end = ins.address + ins.size
            ops = ins.operands
            mn = ins.mnemonic
            if ops and ops[-1].type == ARM_OP_IMM and mn.startswith(('b', 'cb')) and \
                    not mn.startswith('bl') and entry < ops[-1].imm < entry + max_len:
                pending.add(ops[-1].imm)
            pending = {t for t in pending if t >= end}
            # block ends: return, indirect jump, or unconditional branch (in or out of the function)
            ret = (mn.startswith('pop') and 'pc' in ins.op_str) or (mn == 'bx') \
                or (mn in ('b', 'b.w') and ops and ops[-1].type == ARM_OP_IMM)
            last_end_ok = ret and not pending
            if last_end_ok:
                break
        if not last_end_ok:
            return False
        self.funcs[entry] = {'name': f'synthetic_{entry:x}', 'body': [[entry, end]]}
        bisect.insort(self.entries, entry)
        self._index(entry)
        return True

    def containing(self, addr):
        i = bisect.bisect_right(self.entries, addr) - 1
        for e in (self.entries[i:i + 1] if i >= 0 else []):
            if any(lo <= addr < hi for lo, hi in self.funcs[e]['body']):
                return e
        # pool words / gaps: nearest preceding function whose span covers addr
        for e in reversed(self.entries[:i + 1]):
            if min(r[0] for r in self.funcs[e]['body']) <= addr < max(r[1] for r in self.funcs[e]['body']) + 0x200:
                return e
        return None

    def insn_index(self, entry, addr):
        for k, ins in enumerate(self.insns[entry]):
            if ins.addr == addr:
                return k
        return None

    # -- RTTI: class name -> vtable entries ------------------------------------------
    def rtti(self, with_vptr=False):
        out = {}
        for m in re.finditer(rb'\d+(c[A-Z][A-Za-z0-9]+)\x00', self.data):
            name_addr = self.base + m.start()
            for o in range(0, len(self.data) - 3, 4):
                if struct.unpack_from('<I', self.data, o)[0] != name_addr:
                    continue
                ti = self.base + o - 4
                for o2 in range(0, len(self.data) - 3, 4):
                    if struct.unpack_from('<I', self.data, o2)[0] == ti:
                        vt = self.base + o2 + 4
                        ents = []
                        while True:
                            v = self.u32(vt + 4 * len(ents))
                            if v is None or not (is_flash(v) and v & 1):
                                break
                            ents.append(v & ~1)
                        if ents:
                            out[m.group(1).decode()] = (vt, ents) if with_vptr else ents
        return out

    def vectors(self):
        out = []
        for i in range(1, 166):
            v = self.u32(self.base + 4 * i)
            out.append(v & ~1 if v and v & 1 and is_flash(v) else None)
        return out


def _aligned_pairs(a, b, min_block=2, with_size=False):
    """Pairs of instruction indices (i in a, j in b) inside blocks that match token for
    token (optionally with the block length, a measure of how well anchored the pair is).
    Changed regions are never paired positionally; that's where mistakes come from."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for i1, j1, size in sm.get_matching_blocks():
        if size >= min_block:
            for k in range(size):
                yield (i1 + k, j1 + k, size) if with_size else (i1 + k, j1 + k)


def _similar(a, b):
    if min(len(a), len(b)) <= 3:
        return a == b
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.5


class Porter:
    def __init__(self, old: Program, new: Program, log=print):
        self.old, self.new, self.log = old, new, log
        self.fmap = {}                                   # old entry -> (new entry, method)
        self.avotes = collections.defaultdict(collections.Counter)  # old addr -> new addr votes

    def _match(self, o, n, method):
        if o in self.fmap or n in {v[0] for v in self.fmap.values()}:
            return False
        if not self.old.ensure_function(o) or not self.new.ensure_function(n):
            return False
        self.fmap[o] = (n, method)
        return True

    def match_fingerprints(self):
        idx_o = collections.defaultdict(list)
        idx_n = collections.defaultdict(list)
        for e, fp in self.old.fp.items():
            idx_o[fp].append(e)
        for e, fp in self.new.fp.items():
            idx_n[fp].append(e)
        n = 0
        for fp, es in idx_o.items():
            if len(fp) >= 4 and len(es) == 1 and len(idx_n.get(fp, [])) == 1:
                n += self._match(es[0], idx_n[fp][0], 'fingerprint')
        self.log(f'  exact fingerprints: {n}')

    def match_anchors(self):
        n = 0
        ro, rn = self.old.rtti(), self.new.rtti()
        for cls, ents in ro.items():
            for k, (a, b) in enumerate(zip(ents, rn.get(cls, []))):
                n += self._match(a, b, f'rtti {cls}[{k}]')
        for a, b in zip(self.old.vectors(), self.new.vectors()):
            if a and b:
                n += self._match(a, b, 'vector table')
        self.log(f'  RTTI / vector anchors: {n}  (classes: {len(ro)} old, {len(rn)} new)')

    def propagate(self):
        """Matched pairs vote on their callees and on the addresses they load; a callee is
        accepted when its votes agree and its own code is plausibly similar."""
        rounds, total = 0, 0
        done = set()
        while True:
            rounds += 1
            fvotes = collections.defaultdict(collections.Counter)
            for o, (n, _) in list(self.fmap.items()):
                io, inn = self.old.insns[o], self.new.insns[n]
                for i, j, size in _aligned_pairs(self.old.cfp[o], self.new.cfp[n], with_size=True):
                    a, b = io[i], inn[j]
                    if a.call and b.call:
                        fvotes[a.call][b.call] += min(size, 8)
                    if a.lit is not None and b.lit is not None and o not in done:
                        if (is_ram(a.lit) or is_flash(a.lit)) and (is_ram(b.lit) or is_flash(b.lit)):
                            self.avotes[a.lit][b.lit] += 1
                            if a.lit & 1 and b.lit & 1 and is_flash(a.lit):
                                fvotes[a.lit & ~1][b.lit & ~1] += min(size, 8)
                        self.avotes[('pool', a.lit_addr)][b.lit_addr] += 1
                    if o not in done:
                        self.avotes[('insn', a.addr)][b.addr] += 1
                done.add(o)
            # function-pointer literals that appear in the same order in both functions
            for o, (n, _) in list(self.fmap.items()):
                po = [i.lit & ~1 for i in self.old.insns[o] if i.lit and i.lit & 1 and is_flash(i.lit)]
                pn = [i.lit & ~1 for i in self.new.insns[n] if i.lit and i.lit & 1 and is_flash(i.lit)]
                if po and len(po) == len(pn):
                    for a, b in zip(po, pn):
                        fvotes[a][b] += 2
            # tables of function pointers (init_array, handler tables) at corresponding addresses
            for a, cnt in list(self.avotes.items()):
                if not isinstance(a, int) or not is_flash(a) or self.old.containing(a & ~1) is not None:
                    continue
                b = cnt.most_common(1)[0][0]
                for k in range(32):
                    wa, wb = self.old.u32(a + 4 * k), self.new.u32(b + 4 * k)
                    if wa is None or wb is None or not (wa & 1 and wb & 1 and is_flash(wa) and is_flash(wb)):
                        break
                    fvotes[wa & ~1][wb & ~1] += 4
            added = 0
            used = {v[0] for v in self.fmap.values()}
            for oc, cnt in fvotes.items():
                if oc in self.fmap:
                    continue
                (nc, c1), *rest = cnt.most_common(2)
                c2 = rest[0][1] if rest else 0
                if c1 <= 2 * c2 or nc in used:
                    continue
                if not (self.old.ensure_function(oc) and self.new.ensure_function(nc)):
                    continue
                # well anchored (long matching context around the call), or similar code
                if c1 < 4 and not _similar(self.old.cfp[oc], self.new.cfp[nc]):
                    continue
                if self._match(oc, nc, f'callee/pointer (anchor weight {c1})'):
                    used.add(nc)
                    added += 1
            total += added
            if not added:
                break
        self.log(f'  propagation: {total} more in {rounds} rounds')

    def match_fuzzy(self, threshold=0.75):
        used = {v[0] for v in self.fmap.values()}
        cand_new = [e for e in self.new.entries if e not in used and len(self.new.cfp[e]) >= 6]
        n = 0
        for o in self.old.entries:
            if o in self.fmap or len(self.old.cfp[o]) < 6:
                continue
            fo = self.old.cfp[o]
            best, best_r, second = None, 0.0, 0.0
            for e in cand_new:
                fe = self.new.cfp[e]
                if abs(len(fe) - len(fo)) > max(4, len(fo) // 4):
                    continue
                sm = difflib.SequenceMatcher(None, fo, fe, autojunk=False)
                if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
                    continue
                r = sm.ratio()
                if r > best_r:
                    best, best_r, second = e, r, best_r
                elif r > second:
                    second = r
            if best and best_r >= threshold and best_r - second > 0.08:
                if self._match(o, best, f'fuzzy {best_r:.2f}'):
                    n += 1
                    cand_new.remove(best)
        self.log(f'  fuzzy: {n}')

    def run(self):
        self.match_fingerprints()
        self.match_anchors()
        self.propagate()
        self.match_fuzzy()
        self.propagate()
        self.log(f'  matched {len(self.fmap)}/{len(self.old.entries)} old functions')

    # -- mapping individual values ---------------------------------------------------
    def map_function(self, addr):
        if addr in self.fmap:
            n, how = self.fmap[addr]
            return n, how
        o = self.old.containing(addr)
        if o is not None and o in self.fmap:
            m = self.map_insn(addr)
            if m:
                return m[0], f'inside {o:#x}: {m[1]}'
        return None, 'unmatched'

    def map_insn(self, addr):
        """An instruction address inside a matched function -> its counterpart. Fallbacks:
        a coarse instruction window searched inside the counterpart function, then a
        normalized window searched across the whole new image."""
        v = self.avotes.get(('insn', addr))
        if v:
            (b, c), = v.most_common(1)
            return b, 'aligned instruction'
        return self._window_in_function(addr) or self._window(addr)

    def _window_in_function(self, addr):
        o = self.old.containing(addr)
        if o is None or o not in self.fmap:
            return None
        n = self.fmap[o][0]
        k = self.old.insn_index(o, addr)
        if k is None:
            return None
        co, cn = self.old.cfp[o], self.new.cfp[n]
        for w in (6, 5, 4, 3):
            for before in range(w, -1, -1):
                lo, hi = k - before, k - before + w + 1
                if lo < 0 or hi > len(co):
                    continue
                pat = co[lo:hi]
                hits = [j for j in range(len(cn) - len(pat) + 1) if cn[j:j + len(pat)] == pat]
                if len(hits) == 1:
                    return self.new.insns[n][hits[0] + before].addr, f'window of {len(pat)} in matched {n:#x}'
        return None

    def _linear(self, prog, start, count):
        out = []
        for ins in prog.md.disasm(prog.data[start - prog.base:start - prog.base + 4 * count + 8], start):
            out.append(ins)
            if len(out) >= count:
                break
        return out

    def _wtok(self, prog, ins):
        mn = ins.mnemonic
        if mn.split('.')[0] in BRANCHES or mn.startswith('b'):
            return mn + ' X'
        if 'pc' in ins.op_str:
            return mn + ' ' + ins.op_str.split(',')[0] + ' PCREL'
        return mn + ' ' + ins.op_str

    def _window(self, addr, before=6, after=6):
        old = self.old
        # find an instruction boundary `before` instructions back by decoding from earlier offsets
        for back in range(2 * before, 4 * before + 2, 2):
            seq = self._linear(old, addr - back, before + after + 4)
            idx = [k for k, ins in enumerate(seq) if ins.address == addr]
            if idx:
                k = idx[0]
                pat = [self._wtok(old, ins) for ins in seq[max(0, k - before):k + after + 1]]
                off = min(k, before)
                break
        else:
            return None
        if not hasattr(self, '_new_linear'):
            md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
            md.skipdata = True      # keep going through literal pools and data
            self._new_linear = list(md.disasm(self.new.data, self.new.base))
            self._new_toks = [self._wtok(self.new, ins) for ins in self._new_linear]
        hits = [j for j in range(len(self._new_toks) - len(pat))
                if self._new_toks[j:j + len(pat)] == pat]
        if len(hits) == 1:
            return self._new_linear[hits[0] + off].address, f'instruction window ({len(pat)} insns, unique)'
        return None

    def map_pool(self, addr):
        v = self.avotes.get(('pool', addr))
        if v:
            (b, c), = v.most_common(1)
            return b, 'aligned literal slot'
        # the same value in the counterpart function's literal pool
        val = self.old.u32(addr)
        users = [o for o in self.old.entries if any(i.lit_addr == addr for i in self.old.insns[o])]
        for o in users:
            if o in self.fmap:
                n = self.fmap[o][0]
                slots = {i.lit_addr for i in self.new.insns[n] if i.lit == val}
                if len(slots) == 1:
                    return slots.pop(), f'same literal value in matched {n:#x}'
        return None

    def _unchanged_literal(self, a):
        for o in self.old.entries:
            if o in self.fmap and any(i.lit == a for i in self.old.insns[o]):
                if any(i.lit == a for i in self.new.insns[self.fmap[o][0]]):
                    return a, f'unchanged: same literal in matched {self.fmap[o][0]:#x}'
        return None

    def map_address(self, a):
        """A data/RAM address -> new address, via literal votes (exact, then nearby delta)."""
        if a in self.avotes:
            (b, c), = self.avotes[a].most_common(1)
            total = sum(self.avotes[a].values())
            return b, f'literal ({c}/{total} votes)'
        u = self._unchanged_literal(a)
        if u:
            return u
        # nearby: same region, consistent delta from the closest literals below and above
        keys = sorted(k for k in self.avotes if isinstance(k, int) and (is_ram(k) == is_ram(a))
                      and is_flash(k) == is_flash(a))
        i = bisect.bisect_right(keys, a)
        below = [k for k in keys[max(0, i - 4):i] if a - k < 0x4000]
        above = [k for k in keys[i:i + 4] if k - a < 0x400]
        for k in reversed(below):          # nearest base below first: "struct base + offset"
            (b, c), = self.avotes[k].most_common(1)
            agree = sum(1 for k2 in below + above if self.avotes[k2].most_common(1)[0][0] - k2 == b - k)
            return a + (b - k), f'delta from literal {k:#x} (+{a - k:#x}), {agree} nearby agree'
        for k in above:
            (b, c), = self.avotes[k].most_common(1)
            return a + (b - k), f'delta from literal {k:#x} ({a - k:#x})'
        return None, 'no literal nearby'


def load_functions(path):
    with open(path) as f:
        return json.load(f)


def port_symbols(old_sym_raw, porter, report):
    """Produce a new symbols dict. report: list of (section, key, old, new, how)."""
    new = json.loads(json.dumps(old_sym_raw))

    def rec(sec, key, old, val, how):
        report.append((sec, key, old, val, how))
        return f'{val:#010x}' if isinstance(val, int) else None

    def port_fn(sec, key, old):
        o = _h(old)
        v, how = porter.map_function(o)
        return rec(sec, key, old, v, how)

    def port_addr(sec, key, old):
        o = _h(old)
        if is_flash(o) and porter.old.containing(o & ~1) is not None and o not in porter.avotes:
            v, how = porter.map_function(o & ~1)
            if v is not None and o & 1:
                v |= 1
        else:
            v, how = porter.map_address(o)
        return rec(sec, key, old, v, how)

    for k, v in old_sym_raw.get('functions', {}).items():
        if not k.startswith('_'):
            new['functions'][k] = port_fn('functions', k, v)
    for k, v in old_sym_raw.get('globals', {}).items():
        if not k.startswith('_'):
            new['globals'][k] = port_addr('globals', k, v)
    for k, v in old_sym_raw.get('memory', {}).items():
        if k.startswith('_'):
            continue
        if k == 'stack_top':
            val = porter.new.u32(porter.new.base)
            new['memory'][k] = rec('memory', k, v, val, 'vector table [0]')
        else:
            new['memory'][k] = port_addr('memory', k, v)
    if 'slot_extents' in old_sym_raw:
        new['slot_extents'] = [[port_addr('slot_extents', f'{i}.{j}', x) for j, x in enumerate(pair)]
                               for i, pair in enumerate(old_sym_raw['slot_extents'])]
    for k, v in old_sym_raw.get('ipc', {}).items():
        if not k.startswith('_') and k in ('desc', 'buffers'):
            new['ipc'][k] = port_addr('ipc', k, v)
    if 'main_points' in old_sym_raw:
        for k, v in old_sym_raw['main_points'].items():
            if k.startswith('_') or k == 'loop_regs':
                continue
            m = porter.map_insn(_h(v))
            new['main_points'][k] = rec('main_points', k, v, m[0] if m else None, m[1] if m else 'unmatched')
    for k, s in old_sym_raw.get('sites', {}).items():
        if k.startswith('_'):
            continue
        a = _h(s['addr'])
        m = porter.map_pool(a) if 'word' in s else porter.map_insn(a)
        ns = dict(s)
        ns['addr'] = rec('sites', k, s['addr'], m[0] if m else None, m[1] if m else 'unmatched')
        new['sites'][k] = ns
    if 'shared_engine_state' in old_sym_raw:
        st = {}
        for k, v in old_sym_raw['shared_engine_state'].items():
            if k.startswith('_'):
                st[k] = v
                continue
            nv, how = porter.map_address(_h(k))
            report.append(('shared_engine_state', k, k, nv, how))
            st[f'{nv:#010x}' if nv is not None else f'UNPORTED {k}'] = v
        new['shared_engine_state'] = st
    new.pop('objects', None)  # informational only; regenerate by hand if needed
    return new


def read_schema(prog, addr, depth=0):
    """Decode a firmware JSON schema {entries*, count} -> {key: offset or nested dict}."""
    out = {}
    entries, count = prog.u32(addr), prog.u32(addr + 4)
    if entries is None or not count or count > 64:
        return out
    for i in range(count):
        e = entries + 20 * i
        key = prog.cstr(prog.u32(e))
        off, typ, _, nested = prog.u32(e + 4), prog.u32(e + 8), prog.u32(e + 12), prog.u32(e + 16)
        if key is None:
            continue
        if typ == 0x87 and nested and depth < 3:
            out[key] = {'offset': off, 'fields': read_schema(prog, nested, depth + 1)}
        else:
            out[key] = off
    return out
