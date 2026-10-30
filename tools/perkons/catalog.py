"""What the Mod Matrix (tools/modmatrix.py) offers: user-facing options from each mod's
mod.json, and a check of a supplied firmware image.

A mod lists its options in <mod>/mod.json (mods without one are not offered):

    {
      "options": [
        {
          "id": "fx-reverb",                 unique across all mods
          "title": "FX REVERB",
          "summary": "One or two sentences for the user.",
          "patches": ["fx_reverb"],          patch specs, as for `make build`
          "code": "rv",                      2 letters for the build tag (INFO.TXT)
          "conflicts": [],                   option ids that can't be combined (optional)
          "requires": []                     option ids it needs in the same build (optional)
        }
      ]
    }

Target version and risk come from the patch modules themselves (TARGET, RISK).
"""
import hashlib
import json
import os

from .fwimage import Image
from .mods import ROOT, load_patch, mod_dirs

RISKS = ['none', 'low', 'medium', 'high']
MAX_TAG = 11


class CatalogError(Exception):
    pass


def options():
    """All options from every mod's mod.json, with target and risk filled in."""
    out, seen = [], set()
    for d in mod_dirs():
        path = os.path.join(d, 'mod.json')
        if not os.path.exists(path):
            continue
        with open(path) as f:
            spec = json.load(f)
        for o in spec.get('options', []):
            if o['id'] in seen:
                raise CatalogError(f'option id {o["id"]!r} used twice ({path})')
            seen.add(o['id'])
            targets, risk = set(), 'none'
            for p in o['patches']:
                mod = load_patch(p.partition(':')[0])
                targets.add(mod.TARGET)
                if RISKS.index(mod.RISK) > RISKS.index(risk):
                    risk = mod.RISK
            targets.discard(None)
            if len(targets) > 1:
                raise CatalogError(f'option {o["id"]}: patches target different versions {targets}')
            out.append({'id': o['id'], 'title': o['title'], 'summary': o['summary'],
                        'patches': list(o['patches']), 'code': o['code'],
                        'conflicts': list(o.get('conflicts', [])), 'requires': list(o.get('requires', [])),
                        'mod': os.path.basename(d),
                        'target': targets.pop()[1:] if targets else None, 'risk': risk})
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


def check_selection(ids, version):
    """The chosen options, validated for this base version. Returns (options, patch specs)."""
    by_id = {o['id']: o for o in options()}
    chosen = []
    for i in ids:
        if i not in by_id:
            raise CatalogError(f'unknown option {i!r}')
        chosen.append(by_id[i])
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
    specs = list(dict.fromkeys(p for o in chosen for p in o['patches']))   # a shared patch once
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
