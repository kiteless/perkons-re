"""Out-of-tree mods.

A mod is a directory with this layout (every part optional except patches/):

    <mod>/patches/<name>.py   patch modules, same interface as patches/ in this repo
    <mod>/src/<core>/         C sources the patches compile
    <mod>/lib/                Python helpers the patches/tests import
    <mod>/tests/test_*.py     run by `make test` alongside the framework tests
    <mod>/symbols/<ver>-<core>.json   the mod's hook sites (merged into the framework's
                              symbols by perkons.emu.Symbols; ported with them)

PERKONS_MODS lists mod directories, or directories containing mods, separated by ':'.
(The Makefile reads it from the environment or from an untracked local.mk.) The Mod Matrix
adds the mods it downloaded for a build to EXTRA (perkons.repos).
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXTRA = []              # more mod directories (a Mod Matrix build's downloaded mods)

# The platform: patches in every build (the Mod Matrix's, `make build`, releases), so mods
# can count on them. voice_map: any engine on any voice, and the extra engines voice mods add.
PLATFORM = ('voice_map',)
# option ids that were mods and are now the platform: a mod that requires one (any repo's)
# has it already, and a repo that still offers one doesn't offer it
FORMER_MODS = ('voice-map',)


def in_platform(option_id):
    """Whether an option id (plain or owner/name:id) names what's now the platform."""
    return option_id.rpartition(':')[2] in FORMER_MODS


def with_platform(specs):
    """Patch specs with the platform's first (each once)."""
    names = {s.partition(':')[0] for s in specs}
    return [s for s in PLATFORM if s not in names] + list(specs)


def mod_dirs():
    out = []
    for entry in filter(None, os.environ.get('PERKONS_MODS', '').split(os.pathsep)):
        entry = os.path.abspath(os.path.expanduser(entry))
        if os.path.isdir(os.path.join(entry, 'patches')):
            out.append(entry)
        elif os.path.isdir(entry):
            out += sorted(os.path.join(entry, d) for d in os.listdir(entry)
                          if os.path.isdir(os.path.join(entry, d, 'patches')))
    return out + [d for d in EXTRA if d not in out]


def add_to_path(mod_dir):
    for sub in ('lib', 'patches'):
        d = os.path.join(mod_dir, sub)
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)


def load_patch(name):
    """Import patch module `name` from this repo's patches/ or any mod's patches/."""
    for d in [ROOT] + mod_dirs():
        path = os.path.join(d, 'patches', name + '.py')
        if os.path.exists(path):
            if d != ROOT:
                add_to_path(d)
            spec = importlib.util.spec_from_file_location(f'perkons_patch_{name}', path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(f'patch {name!r} not found in patches/ or PERKONS_MODS ({mod_dirs()})')


def symbol_overlays(path):
    """The mods' symbol files that go with framework symbols file `path` (same name)."""
    name = os.path.basename(path)
    return [f for f in (os.path.join(d, 'symbols', name) for d in mod_dirs()) if os.path.exists(f)]
