#!/usr/bin/env python3
"""Build a release: patches + version stamp, regression check, release folder.

  release.py <release.json> [--allow-dirty] [--no-emu]

release.json (usually kept with the mods it releases):
  {
    "name": "kiteless", "version": "0.1",
    "base": "v1.3.0", "base_image": "perkons_v1.3.0-0-force.img",
    "tag": "kiteless0.1",                      # <= 11 chars, shown in INFO.TXT
    "banner": "+ kiteless 0.1 (voice-map)",    # appended to the UART boot banner
    "patches": ["voice_map:bank"],
    "summary": "one line", "notes": ["...", "..."]
  }

Output: builds/releases/<name>-<version>/<base_image name> + RELEASE.md. The image keeps
the official file name because that's the name the bootloader is known to accept.
Refuses to build from uncommitted changes (framework or mods) unless --allow-dirty, so
every release maps to exact commits.
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from build import build_image, regression  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.mods import mod_dirs  # noqa: E402


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def git_state(path):
    def git(*a):
        return subprocess.run(['git', '-C', path, *a], capture_output=True, text=True).stdout.strip()
    top = git('rev-parse', '--show-toplevel')
    if not top:
        return None
    return {'repo': os.path.basename(top), 'commit': git('rev-parse', '--short=12', 'HEAD'),
            'dirty': bool(git('status', '--porcelain', '--untracked-files=no'))}


def find_base(name):
    for d in (ROOT, os.path.join(ROOT, 'firmware')):
        if os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    sys.exit(f'base image {name} not found in repo root or firmware/')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('release')
    ap.add_argument('--allow-dirty', action='store_true')
    ap.add_argument('--no-emu', action='store_true')
    a = ap.parse_args()
    with open(a.release) as f:
        rel = json.load(f)

    repos = {}
    for path in [ROOT, os.path.dirname(os.path.abspath(a.release))] + mod_dirs():
        st = git_state(path)
        if st:
            repos[st['repo']] = st
    dirty = [r for r, st in repos.items() if st['dirty']]
    if dirty and not a.allow_dirty:
        sys.exit(f'uncommitted changes in {", ".join(dirty)}; commit first or pass --allow-dirty')

    base_path = find_base(rel['base_image'])
    base = Image.load(base_path)
    if f'v{base.version}' != rel['base']:
        sys.exit(f'{rel["base_image"]} is v{base.version}, release says {rel["base"]}')
    out_dir = os.path.join(ROOT, 'builds', 'releases', f'{rel["name"]}-{rel["version"]}')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, rel['base_image'])

    specs = list(rel['patches']) + [f'version_stamp:{rel["tag"]}']
    img, _ = build_image(base, out, specs, os.path.join(ROOT, 'symbols', f'{rel["base"]}-m7.json'),
                         build_dir=os.path.join(out_dir, 'obj'),
                         extra_kwargs={'version_stamp': {'banner': rel.get('banner')}})
    bad = None if a.no_emu else regression(base, img, os.path.join(ROOT, 'symbols', f'{rel["base"]}-m7.json'))

    v = f'{base.major}.{base.minor}.{base.patch}'
    lines = [
        f'# {rel["name"]} {rel["version"]}', '',
        rel.get('summary', ''), '',
        '## Build', '',
        '| | |', '|---|---|',
        f'| based on | official Pērkons firmware **{v}** ({base.git}), `{rel["base_image"]}` sha256 `{sha256(base_path)[:16]}…` |',
        f'| patches | {", ".join(f"`{s}`" for s in rel["patches"])} |',
        f'| version tag | `{rel["tag"]}` |',
    ]
    for r, st in sorted(repos.items()):
        lines.append(f'| {r} | `{st["commit"]}`{" (**uncommitted changes**)" if st["dirty"] else ""} |')
    lines += [
        f'| image | `{os.path.basename(out)}` sha256 `{sha256(out)[:16]}…` |',
        f'| built | {datetime.date.today().isoformat()} |',
        f'| emulator regression | {"skipped" if bad is None else ("all outputs identical to the stock engine they run" if not bad else f"{len(bad)} differences, see build log")} |',
        '', '## Install', '',
        f'1. Copy `{os.path.basename(out)}` to the root of the SD card (only one `.img` there).',
        '2. Power off, hold all four voice trigger keys, power on; release when row 1 starts lighting.',
        '3. Rows light 1 → 3 → 2 → 4, then it boots. `INFO.TXT` on the card should then read:', '',
        '```',
        f'Current Controller   (CM4) version: {v} - {rel["tag"]}',
        f'Current Voice Engine (CM7) version: {v} - {rel["tag"]}',
        '```', '',
        f'To go back to stock, flash the official `{rel["base_image"]}` the same way.',
    ]
    if rel.get('notes'):
        lines += ['', '## Notes', ''] + [f'* {n}' for n in rel['notes']]
    with open(os.path.join(out_dir, 'RELEASE.md'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'\nrelease -> {out_dir}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
