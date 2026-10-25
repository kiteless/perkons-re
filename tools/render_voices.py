#!/usr/bin/env python3
"""Render Perkons voices offline by emulating the M7 DSP firmware.

  render_voices.py <img> <symbols.json> <outdir> [--voices 1,2,3,4] [--seconds 1.0]
                   [--params 2048,2048,2048,2048] [--compare <other_outdir>]

Writes <outdir>/v{voice}_a{algo}_m{mode}.wav for every combination plus
<outdir>/report.json (class, peak, RMS, M7 instructions per sample).

With --compare, also diffs each WAV against the same name in another directory.
That's the regression check: a patch that shouldn't change a voice's sound must
render bit-identical audio.
"""
import argparse
import hashlib
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from perkons.emu import M7Emu, Symbols, write_wav  # noqa: E402
from perkons.fwimage import Image  # noqa: E402

RATE = 48000
# 480 MHz M7 / 48 kHz = 10000 cycles per sample for *everything*. Instruction counts
# aren't cycles (FPU ops, flash wait states, cache misses), so treat this as relative.
CYCLES_PER_SAMPLE = 480_000_000 // RATE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('symbols')
    ap.add_argument('outdir')
    ap.add_argument('--voices', default='1,2,3,4')
    ap.add_argument('--seconds', type=float, default=1.0)
    ap.add_argument('--params', default='2048,2048,2048,2048')
    ap.add_argument('--compare')
    a = ap.parse_args()

    img = Image.load(a.img)
    sym = Symbols(a.symbols)
    params = [int(x) for x in a.params.split(',')]
    n = int(a.seconds * RATE)
    report = []
    for v in [int(x) - 1 for x in a.voices.split(',')]:
        for algo in range(3):
            for mode in range(3):
                # fresh machine per render so voices don't leak state into each other
                e = M7Emu(img.segment('m7').data, sym, img.segment('m4').data).boot_voices()
                e.set_params(v, params)
                e.set_algo_mode(v, algo, mode)
                e.trigger(v)
                e.count_insns(True)
                e.insn_count = 0
                probe = e.render(v, 256)
                ips = e.insn_count / 256
                e.count_insns(False)
                samples = probe + e.render(v, n - 256)
                name = f'v{v + 1}_a{algo}_m{mode}.wav'
                write_wav(os.path.join(a.outdir, name), samples, RATE)
                peak = max(abs(s) for s in samples)
                rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                row = {'file': name, 'voice': v + 1, 'algo': algo, 'mode': mode, 'slot_class': e.class_of(e.slot(v)),
                       'peak': peak, 'rms': round(rms, 1), 'insns_per_sample': round(ips, 1),
                       'pct_of_budget': round(100 * ips / CYCLES_PER_SAMPLE, 2),
                       'sha1': hashlib.sha1(bytes(str(samples), 'ascii')).hexdigest()[:12]}
                if a.compare:
                    other = os.path.join(a.compare, 'report.json')
                    ref = {r['file']: r for r in json.load(open(other))} if os.path.exists(other) else {}
                    row['matches_ref'] = ref.get(name, {}).get('sha1') == row['sha1']
                report.append(row)
                print(f"{name:16s} {row['slot_class']:12s} peak={peak:6d} rms={rms:8.1f} "
                      f"insn/sample={ips:7.1f} ({row['pct_of_budget']:5.2f}%)"
                      + (f"  ref={'SAME' if row['matches_ref'] else 'DIFF'}" if a.compare else ''))
    with open(os.path.join(a.outdir, 'report.json'), 'w') as f:
        json.dump(report, f, indent=1)


if __name__ == '__main__':
    main()
