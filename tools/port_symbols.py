#!/usr/bin/env python3
"""Port symbols to another firmware version and check the result.

  port_symbols.py --from v1.3.0 --to v1.2.1 [--out symbols/] [--from-img X.img] [--to-img Y.img]

Needs both versions imported into Ghidra first (`make ghidra VER=...`), which exports
the function lists. Writes symbols/<to>-{m4,m7}.json (unless they exist; then
<to>-*.ported.json), a report ghidra/out/<to>/port-report.md, then runs the behavioural
checks (tools/check_symbols.py) against the new image.
"""
import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from perkons.emu import Symbols  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.port import Porter, Program, load_functions, port_symbols  # noqa: E402
from perkons.probes import probe_m7  # noqa: E402
from perkons.symcheck import run_all  # noqa: E402


def verify_sites(raw, seg, rep):
    """A ported site is only kept if the instruction there is what the site promises."""
    from perkons.patch import thumb_bl
    fns = {k: int(v, 16) for k, v in raw.get('functions', {}).items() if isinstance(v, str) and v.startswith('0x')}
    for k, s in raw.get('sites', {}).items():
        if k.startswith('_') or not s.get('addr'):
            continue
        a = int(s['addr'], 16)
        cur = seg.data[a - seg.addr:a - seg.addr + 4]
        ok, why = True, ''
        if 'call' in s:
            t = fns.get(s['call'])
            ok = t is not None and cur == thumb_bl(a, t)
            why = f'instruction there is not bl {s["call"]}'
        elif 'bytes' in s:
            b = bytes.fromhex(s['bytes'])
            ok = seg.data[a - seg.addr:a - seg.addr + len(b)] == b
            why = 'instruction bytes differ (inspect: offsets or registers may have changed)'
        elif 'word' in s:
            ok = int.from_bytes(seg.data[a - seg.addr:a - seg.addr + 4], 'little') == int(s['word'], 16)
            why = 'word there is not the ported value'
        if not ok:
            s['addr'] = None
            for i, r in enumerate(rep):
                if r[0] == 'sites' and r[1] == k:
                    rep[i] = (r[0], r[1], r[2], None, f'rejected: {why}')


def find_img(ver):
    for p in glob.glob(os.path.join(ROOT, '*.img')) + glob.glob(os.path.join(ROOT, 'firmware', '*.img')):
        try:
            if f'v{Image.load(p).version}' == ver:
                return p
        except Exception:  # noqa: BLE001
            pass
    sys.exit(f'no official image for {ver} in repo root or firmware/')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='src', required=True)
    ap.add_argument('--to', dest='dst', required=True)
    ap.add_argument('--from-img')
    ap.add_argument('--to-img')
    ap.add_argument('--out', default=os.path.join(ROOT, 'symbols'))
    a = ap.parse_args()
    old_img = Image.load(a.from_img or find_img(a.src))
    new_img = Image.load(a.to_img or find_img(a.dst))
    report, outputs = [], {}
    for core in ('m7', 'm4'):
        print(f'== {core}: {a.src} -> {a.dst}')
        fo = os.path.join(ROOT, 'ghidra', 'out', a.src, core, 'functions.json')
        fn = os.path.join(ROOT, 'ghidra', 'out', a.dst, core, 'functions.json')
        for f in (fo, fn):
            if not os.path.exists(f):
                sys.exit(f'{f} missing: run `make ghidra VER=...` for both versions first')
        so, sn = old_img.segment(core), new_img.segment(core)
        porter = Porter(Program(so.data, so.addr, load_functions(fo)), Program(sn.data, sn.addr, load_functions(fn)))
        porter.run()
        with open(os.path.join(a.out, f'{a.src}-{core}.json')) as f:
            old_raw = json.load(f)
        rep = []
        new_raw = port_symbols(old_raw, porter, rep)
        verify_sites(new_raw, sn, rep)
        new_raw['_comment'] = (f'PORTED from {a.src} by tools/port_symbols.py; review ghidra/out/{a.dst}/port-report.md. '
                               + str(old_raw.get('_comment', '')))
        out = os.path.join(a.out, f'{a.dst}-{core}.json')
        if os.path.exists(out):
            out = out.replace('.json', '.ported.json')
        with open(out, 'w') as f:
            json.dump(new_raw, f, indent=2, ensure_ascii=False)
            f.write('\n')
        outputs[core] = out
        report += [(core,) + r for r in rep]
        miss = [r for r in rep if r[3] is None]
        print(f'  {len(rep) - len(miss)}/{len(rep)} symbol values ported -> {out}')

    # the M7 never references the IPC ring buffers (the M4 sets them up): take the M4's
    m7 = json.load(open(outputs['m7']))
    m4 = json.load(open(outputs['m4']))
    if 'ipc' in m7 and 'ipc' in m4:
        for k in ('desc', 'buffers'):
            if m4['ipc'].get(k) and m7['ipc'].get(k) != m4['ipc'][k]:
                report.append(('m7', 'ipc', k, m7['ipc'].get(k), int(m4['ipc'][k], 16), 'from the ported M4 symbols'))
                m7['ipc'][k] = m4['ipc'][k]
        with open(outputs['m7'], 'w') as f:
            json.dump(m7, f, indent=2, ensure_ascii=False)
            f.write('\n')

    lines = [f'# Symbol port {a.src} -> {a.dst}', '', '| core | section | key | old | new | how |', '|---|---|---|---|---|---|']
    for core, sec, key, old, new, how in report:
        nv = f'{new:#x}' if isinstance(new, int) else '**UNPORTED**'
        lines.append(f'| {core} | {sec} | {key} | {old} | {nv} | {how} |')
    rp = os.path.join(ROOT, 'ghidra', 'out', a.dst, 'port-report.md')
    with open(rp, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'report -> {rp}')

    print('== probing layout facts in the new image')
    s7 = Symbols(outputs['m7'])
    prep = []
    probe_m7(new_img, s7, prep)
    with open(outputs['m7'], 'w') as f:
        json.dump(s7.raw, f, indent=2, ensure_ascii=False)
        f.write('\n')
    for sec, key, old, new, how in prep:
        print(f'  {sec}.{key}: {old} -> {new if not isinstance(new, int) else hex(new)}  ({how})')
    with open(rp, 'a') as f:
        f.write('\n## Probes (M7 layout measured in the emulator)\n\n| section | key | old | new | how |\n|---|---|---|---|---|\n')
        for sec, key, old, new, how in prep:
            f.write(f'| {sec} | {key} | {old} | {new if not isinstance(new, int) else hex(new)} | {how} |\n')

    print('== behavioural checks on the ported symbols')
    res = run_all(new_img, Symbols(outputs['m7']), Symbols(outputs['m4']))
    for name, ok, detail in res:
        print(f'{"PASS" if ok else "FAIL"}  {name:14s} {detail.splitlines()[0] if detail else ""}')
    bad = sum(1 for r in res if not r[1])
    print(f'{len(res) - bad}/{len(res)} checks passed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
