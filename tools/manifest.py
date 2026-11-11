#!/usr/bin/env python3
"""Write a mod repo's perkons-mods.json: what the Mod Matrix reads to offer its mods.

  manifest.py REPO_DIR [--image official.img ...] [--check]

REPO_DIR is a mod repo (perkons-repo.json at its root, its mods below: perkons.repos). The
manifest lists every option of every mod in it, as its mod.json says, with its target and,
per firmware version, the RAM it adds to the platform (MAIN, VOICE, STORE), measured by
building it with what it requires: an official image for each supported version is needed (given
with --image, or found in the framework's root or firmware/). Mods from other repos that
these require must be on disk too (PERKONS_MODS). --check: don't write, exit 1 if the
manifest on disk differs (it's out of date).

Commit the manifest with the mods: the Mod Matrix shows mods and their memory from it, and
only downloads a mod when a build needs it.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from perkons import catalog, repos  # noqa: E402
from perkons.fwimage import Image  # noqa: E402
from perkons.mods import PLATFORM, mod_dirs  # noqa: E402


def find_images(given):
    """{version: path} of official images: given ones, else the framework's root and firmware/."""
    known = catalog.official_images()
    paths = list(given) or [os.path.join(d, f) for d in (ROOT, os.path.join(ROOT, 'firmware'))
                            if os.path.isdir(d) for f in sorted(os.listdir(d)) if f.endswith('.img')]
    out = {}
    for p in paths:
        with open(p, 'rb') as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        if sha in known:
            out.setdefault(known[sha]['version'], p)
        elif given:
            sys.exit(f'{p}: not an official image')
    return {v: p for v, p in out.items() if v in catalog.supported_versions()}


def build(repo_dir, images):
    repo_dir = os.path.abspath(repo_dir)
    root, repo = repos.repo_root(os.path.join(repo_dir, repos.REPO_FILE))
    if root != repo_dir:
        sys.exit(f'{repo_dir}: no {repos.REPO_FILE} (a mod repo has one at its root)')
    with open(os.path.join(root, repos.REPO_FILE)) as f:
        info = json.load(f)
    if repo_dir not in [os.path.dirname(d) for d in mod_dirs()]:
        os.environ['PERKONS_MODS'] = os.pathsep.join(filter(None, [os.environ.get('PERKONS_MODS'), repo_dir]))
    everything = catalog.options()
    by_id = {o['id']: o for o in everything}
    ours = [o for o in everything if o.get('repo') == repo]
    work = tempfile.mkdtemp(prefix='pk-manifest-')
    symbols = {v: os.path.join(ROOT, 'symbols', f'v{v}-m7.json') for v in images}
    platform = {v: catalog.measure(Image.load(path), list(PLATFORM), symbols[v], os.path.join(work, '_platform', v))
                for v, path in images.items()}
    mods = []
    for o in ours:
        prefix = repo + ':'
        plain = lambda i: i[len(prefix):] if i.startswith(prefix) else i    # noqa: E731
        memory = {}
        for version, path in sorted(images.items()):
            if o['target'] not in (None, version):
                continue
            for r in o['requires']:
                if r not in by_id:
                    sys.exit(f'{o["id"]} requires {r}, which isn\'t on disk (PERKONS_MODS)')
            got = catalog.measure(Image.load(path), catalog.option_specs(o['id'], by_id), symbols[version],
                                  os.path.join(work, o['id'].replace('/', '_').replace(':', '_'), version))
            memory[f'v{version}'] = catalog.beyond(got, platform[version])
        entry = {'id': plain(o['id']), 'dir': o['dir'], 'title': o['title'], 'summary': o['summary']}
        if o['description']:
            entry['description'] = o['description']
        if o['readme_path']:
            entry['readme'] = o['readme_path']
        if o['author'] != repo.split('/')[0]:
            entry['author'] = o['author']
        entry.update({'patches': o['patches'], 'code': o['code'], 'kind': o['kind'],
                      'requires': [plain(r) for r in o['requires']], 'conflicts': [plain(c) for c in o['conflicts']],
                      'target': o['target'], 'memory': memory})
        mods.append(entry)
    return {'format': repos.MANIFEST_FORMAT, 'repo': repo, 'description': info.get('description', ''),
            'mods': mods}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('repo_dir')
    ap.add_argument('--image', action='append', default=[])
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    images = find_images(a.image)
    if not images:
        sys.exit('no official firmware image found: give one with --image')
    text = json.dumps(build(a.repo_dir, images), indent=1, sort_keys=False) + '\n'
    path = os.path.join(a.repo_dir, repos.MANIFEST)
    if a.check:
        old = open(path).read() if os.path.exists(path) else ''
        if old != text:
            sys.exit(f'{path} is out of date: run tools/manifest.py {a.repo_dir}')
        return
    with open(path, 'w') as f:
        f.write(text)
    print(f'wrote {path}: {len(json.loads(text)["mods"])} options, firmware {", ".join(sorted(images))}')


if __name__ == '__main__':
    main()
