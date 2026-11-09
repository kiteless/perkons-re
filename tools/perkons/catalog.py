"""What the Mod Matrix (tools/modmatrix.py) offers: user-facing options from each mod's
mod.json, and a check of a supplied firmware image.

A mod lists its options in <mod>/mod.json (mods without one are not offered):

    {
      "options": [
        {
          "id": "fx-reverb",                 unique in its repo
          "title": "FX REVERB",              its short name
          "summary": "One or two sentences for the user.",
          "description": "...",              longer, optional
          "readme": "fx-reverb/README.md",   its page, from the repo root (optional; default:
                                             the mod's README.md if it has one)
          "patches": ["fx_reverb"],          patch specs, as for `make build`
          "code": "rv",                      2 letters for the build tag (INFO.TXT)
          "conflicts": [],                   option ids that can't be combined (optional)
          "requires": []                     option ids it needs in the same build (optional;
                                             another repo's as owner/name:id)
        }
      ]
    }

The target version comes from the patch modules themselves (TARGET). A mod in a
mod repo (perkons.repos: a perkons-repo.json above it) has the full id owner/name:id.
"""
import hashlib
import json
import os

from . import repos
from .fwimage import Image
from .mods import ROOT, load_patch, mod_dirs

MAX_TAG = 11


class CatalogError(Exception):
    pass


def options(dirs=None):
    """All options from every mod's mod.json (dirs: these mod directories, else
    mod_dirs()), with the target filled in."""
    out, seen = [], set()
    for d in mod_dirs() if dirs is None else dirs:
        path = os.path.join(d, 'mod.json')
        if not os.path.exists(path):
            continue
        with open(path) as f:
            spec = json.load(f)
        root, repo = repos.repo_root(d)
        q = (lambda i: repos.qualify(repo, i)) if repo else (lambda i: i)
        for o in spec.get('options', []):
            oid = q(o['id'])
            if oid in seen:
                raise CatalogError(f'option id {oid!r} used twice ({path})')
            seen.add(oid)
            targets = set()
            for p in o['patches']:
                mod = load_patch(p.partition(':')[0])
                targets.add(mod.TARGET)
            targets.discard(None)
            if len(targets) > 1:
                raise CatalogError(f'option {o["id"]}: patches target different versions {targets}')
            rel = os.path.relpath(d, root).replace(os.sep, '/') if root else os.path.basename(d)
            readme = o.get('readme') or (f'{rel}/README.md' if os.path.exists(os.path.join(d, 'README.md')) else None)
            out.append({'id': oid, 'title': o['title'], 'summary': o['summary'],
                        'description': o.get('description', ''),
                        'readme': f'https://github.com/{repo}/blob/main/{readme}' if repo and readme else None,
                        'readme_path': readme,
                        'patches': list(o['patches']), 'code': o['code'],
                        'conflicts': [q(c) for c in o.get('conflicts', [])],
                        'requires': [q(r) for r in o.get('requires', [])],
                        'kind': o.get('kind', 'mod'), 'mod': os.path.basename(d), 'dir': rel,
                        'repo': repo, 'ref': 'main', 'author': o.get('author', repo.split('/')[0] if repo else None),   # "": none shown
                        'local': root if repo else d,
                        'target': targets.pop()[1:] if targets else None})
    return out


def official_images():
    with open(os.path.join(ROOT, 'symbols', 'official-images.json')) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith('_')}


def supported_versions():
    return sorted(f[1:-8] for f in os.listdir(os.path.join(ROOT, 'symbols'))
                  if f.startswith('v') and f.endswith('-m7.json'))


def inspect(raw):
    """Read only what's needed to know what the file is: the container header (product,
    version), each segment's CRC, and the file's hash against the known official images.
    Raises CatalogError if it isn't a usable Pērkons image."""
    try:
        img = Image.parse(raw)
    except Exception as e:
        raise CatalogError(f'not a Perkons firmware image ({e})')
    if img.product != 'Perkons':
        raise CatalogError(f'not a Perkons firmware image (product {img.product!r})')
    if not all(s.crc_ok for s in img.segments):
        raise CatalogError('image is damaged (CRC mismatch)')
    sha = hashlib.sha256(raw).hexdigest()
    known = official_images().get(sha)
    return img, {'version': img.version, 'git': img.git, 'sha256': sha, 'official': bool(known),
                 'supported': img.version in supported_versions(),
                 'segments': [{'core': s.name, 'size': len(s.data)} for s in img.segments]}


FIRST_VOICE_SLOT = 5           # voice slots 1-4: the official voices
MAX_VOICE_SLOT = 16


def check_selection(ids, version, voices=(), offered=None):
    """The chosen options, validated for this base version. ids: mods (and voices, in any
    order); voices: the installed voices in slot order, from FIRST_VOICE_SLOT; offered: the
    options to choose from (else options()). Returns (options, patch specs); a voice's
    patch gets its slot as its argument."""
    by_id = {o['id']: o for o in (options() if offered is None else offered)}
    voices = list(voices)
    if len(set(voices)) != len(voices):
        raise CatalogError('a voice can be installed once')
    if len(voices) > MAX_VOICE_SLOT - FIRST_VOICE_SLOT + 1:
        raise CatalogError(f'at most {MAX_VOICE_SLOT - FIRST_VOICE_SLOT + 1} voices')
    ids = list(dict.fromkeys([i for i in ids if i not in voices] + voices))
    chosen = []
    for i in ids:
        if i not in by_id:
            raise CatalogError(f'unknown option {i!r}')
        o = by_id[i]
        if (o['kind'] == 'voice') != (i in voices):
            raise CatalogError(f'{o["title"]}: voices are installed in a slot, mods ticked')
        chosen.append(o)
    if not chosen:
        raise CatalogError('choose at least one mod')
    for o in chosen:
        if o['target'] not in (None, version):
            raise CatalogError(f'{o["title"]} needs firmware {o["target"]}, this is {version}')
        clash = set(o['conflicts']) & set(ids)
        if clash:
            raise CatalogError(f'{o["title"]} can\'t be combined with {", ".join(sorted(clash))}')
        missing = set(o['requires']) - set(ids)
        if missing:
            raise CatalogError(f'{o["title"]} needs {", ".join(sorted(missing))} too')
    owner = {}
    for o in chosen:                    # patch modules are found by name: one of each
        for p in o['patches']:
            name = p.partition(':')[0]
            if owner.setdefault(name, o.get('repo')) != o.get('repo'):
                raise CatalogError(f'patch {name!r} is in two repos ({owner[name]}, {o.get("repo")}): '
                                   f'they can\'t be built together')
    slot = {i: FIRST_VOICE_SLOT + n for n, i in enumerate(voices)}
    specs = list(dict.fromkeys(f'{p}:{slot[o["id"]]}' if o['id'] in slot else p
                               for o in chosen for p in o['patches']))   # a shared patch once
    return chosen, specs


def build_tag(chosen):
    """Short tag for INFO.TXT, e.g. mm-vmrvfz; falls back to a hash if too long."""
    tag = 'mm-' + ''.join(o['code'] for o in chosen)
    if len(tag) > MAX_TAG:
        tag = 'mm-' + hashlib.sha1('+'.join(o['id'] for o in chosen).encode()).hexdigest()[:MAX_TAG - 3]
    return tag


# -- RAM (MAIN / VOICE / STORE, see ram.py) ----------------------------------------------
# The Mod Matrix measures each option by building it alone (with what it requires) and
# keeps {option: {area: {owner: bytes}}}; a combination takes the union of the owners, so
# RAM two options share (the FX buffer) counts once. The real build checks it exactly.

def with_requires(ids, by_id=None):
    """ids plus everything they require, transitively (in a stable order)."""
    by_id = by_id or {o['id']: o for o in options()}
    out = []

    def add(i):
        if i in out or i not in by_id:
            return
        out.append(i)
        for r in by_id[i]['requires']:
            add(r)
    for i in ids:
        add(i)
    return out


def ram_used(ids, memory):
    """{area: bytes} for these options together, from a measurement (App.measure)."""
    owners = {}
    for i in ids:
        for area, own in memory['options'].get(i, {}).items():
            owners.setdefault(area, {}).update(own)
    return {a: sum(owners.get(a, {}).values()) for a in memory['areas']}


def check_memory(ids, memory):
    used = ram_used(ids, memory)
    for a, info in memory['areas'].items():
        if used[a] > info['size']:
            raise CatalogError(f'out of memory in {a.upper()}: these mods need {used[a]} B, '
                               f'{info["size"]} B available')


def canonical_owner(owner):
    """A RAM owner as every machine names it: a source in a mod repo (a path from ROOT,
    wherever the repo is on this machine) as owner/name:path-in-repo; others as they are."""
    path, sep, section = owner.rpartition(':')
    if not sep:
        return owner
    root, repo = repos.repo_root(os.path.join(ROOT, path))
    if not repo:
        return owner
    return f'{repo}:{os.path.relpath(os.path.join(ROOT, path), root).replace(os.sep, "/")}:{section}'


def measure(img, specs, symbols, work):
    """Build specs (no image written) and return what it takes: {ram: {area: {owner:
    bytes}}, takeovers, borrows}, owners canonical."""
    import contextlib
    import io
    import sys
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    from build import apply_specs
    with contextlib.redirect_stdout(io.StringIO()):
        p = apply_specs(img, specs, symbols, work)
    return {'ram': {a: {canonical_owner(k): size for k, (_, size) in own.items()} for a, own in p.ram.items()},
            'takeovers': p.ram_takeovers, 'borrows': p.ram_borrows}
