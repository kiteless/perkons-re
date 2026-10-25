"""Out-of-tree mods.

A mod is a directory with this layout (every part optional except patches/):

    <mod>/patches/<name>.py   patch modules, same interface as patches/ in this repo
    <mod>/src/<core>/         C sources the patches compile
    <mod>/lib/                Python helpers the patches/tests import
    <mod>/tests/test_*.py     run by `make test` alongside the framework tests

PERKONS_MODS lists mod directories, or directories containing mods, separated by ':'.
(The Makefile reads it from the environment or from an untracked local.mk.)
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def mod_dirs():
    out = []
    for entry in filter(None, os.environ.get('PERKONS_MODS', '').split(os.pathsep)):
        entry = os.path.abspath(os.path.expanduser(entry))
        if os.path.isdir(os.path.join(entry, 'patches')):
            out.append(entry)
        elif os.path.isdir(entry):
            out += sorted(os.path.join(entry, d) for d in os.listdir(entry)
                          if os.path.isdir(os.path.join(entry, d, 'patches')))
    return out


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
