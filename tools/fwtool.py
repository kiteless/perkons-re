#!/usr/bin/env python3
"""Perkons firmware image tool.

  fwtool.py info    <img>...                 show header, segments, CRC status
  fwtool.py unpack  <img> <outdir>           write <outdir>/{m4,m7}.bin + manifest.json
  fwtool.py pack    <outdir> <img>           rebuild an image from an unpacked dir (CRCs recomputed)
  fwtool.py verify  <img>...                 CRCs + byte-exact re-encode round trip
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from perkons.fwimage import Image, Segment  # noqa: E402


def cmd_info(paths):
    for p in paths:
        print(f'{p}:\n{Image.load(p).describe()}')


def cmd_unpack(path, outdir):
    img = Image.load(path)
    os.makedirs(outdir, exist_ok=True)
    manifest = {k: getattr(img, k) for k in ('product', 'field2', 'major', 'minor', 'patch', 'git')}
    manifest['segments'] = []
    for s in img.segments:
        fn = f'{s.name}.bin'
        with open(os.path.join(outdir, fn), 'wb') as f:
            f.write(s.data)
        manifest['segments'].append({'core': s.core, 'addr': f'0x{s.addr:08x}', 'file': fn})
    with open(os.path.join(outdir, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)
    print(img.describe())
    print(f'-> {outdir}')


def cmd_pack(indir, out):
    with open(os.path.join(indir, 'manifest.json')) as f:
        m = json.load(f)
    img = Image(**{k: m[k] for k in ('product', 'field2', 'major', 'minor', 'patch', 'git')})
    for s in m['segments']:
        with open(os.path.join(indir, s['file']), 'rb') as f:
            img.segments.append(Segment(core=s['core'], addr=int(s['addr'], 16), data=f.read()))
    img.save(out)
    print(Image.load(out).describe())
    print(f'-> {out}')


def cmd_verify(paths):
    ok = True
    for p in paths:
        raw = open(p, 'rb').read()
        img = Image.parse(raw)
        crc = all(s.crc_ok for s in img.segments)
        rt = img.build(recompute_crc=False) == raw
        print(f'{p}: crc={"OK" if crc else "FAIL"} roundtrip={"OK" if rt else "FAIL"}')
        ok &= crc and rt
    return 0 if ok else 1


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, args = argv[1], argv[2:]
    if cmd == 'info':
        cmd_info(args)
    elif cmd == 'unpack':
        cmd_unpack(*args)
    elif cmd == 'pack':
        cmd_pack(*args)
    elif cmd == 'verify':
        return cmd_verify(args)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
