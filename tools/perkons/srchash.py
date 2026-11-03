"""Content hashes of what a build depends on, for the caches in .cache/ (gitignored): the
framework's build inputs, every mod's (not their tests or docs) and the toolchain. Any
change to any of them gives a new key, so a cache entry is never stale."""
import functools
import hashlib
import os
import subprocess

from .mods import ROOT, mod_dirs

CACHE = os.path.join(ROOT, '.cache')
FRAMEWORK = ('tools/perkons', 'src', 'include', 'symbols', 'patches')
SKIP = {'tests', 'docs', 'tools', '__pycache__', '.git'}       # inside a mod: not build inputs
EXTS = ('.py', '.c', '.h', '.json', '.S', '.ld')


def _files(top):
    for d, subs, names in os.walk(top):
        subs[:] = sorted(s for s in subs if s not in SKIP)
        for n in sorted(names):
            if n.endswith(EXTS):
                yield os.path.join(d, n)


@functools.lru_cache(maxsize=None)
def _gcc():
    try:
        return subprocess.run(['arm-none-eabi-gcc', '-dumpfullversion'], capture_output=True, text=True).stdout
    except OSError:
        return ''


def sources():
    """Hash of the framework's and every mod's build inputs and the compiler version."""
    h = hashlib.sha256(_gcc().encode())
    for top in [os.path.join(ROOT, d) for d in FRAMEWORK] + mod_dirs():
        for f in _files(top):
            h.update(os.path.relpath(f, ROOT).encode() + b'\0')
            with open(f, 'rb') as fh:
                h.update(fh.read())
    return h.hexdigest()


def key(*parts):
    """A cache key: the sources' hash plus whatever else the result depends on."""
    h = hashlib.sha256(sources().encode())
    for p in parts:
        h.update(b'\0' + (p if isinstance(p, bytes) else str(p).encode()))
    return h.hexdigest()[:24]


def path(kind, k, ext):
    d = os.path.join(CACHE, kind)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, k + ext)
