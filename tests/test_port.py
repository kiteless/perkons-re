"""The symbol porter: an exact self-port, and a real backwards port to 1.2.1 where every
feature 1.2.1 actually has must pass its behavioural checks.

Needs Ghidra function exports (`make ghidra VER=v1.3.0` and `VER=v1.2.1`); skipped otherwise."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from fixtures import ROOT, require_image

FUNCS = os.path.join(ROOT, 'ghidra', 'out', '{v}', '{c}', 'functions.json')


def need_funcs(*versions):
    for v in versions:
        for c in ('m4', 'm7'):
            if not os.path.exists(FUNCS.format(v=v, c=c)):
                raise unittest.SkipTest(f'no Ghidra function export for {v} (make ghidra VER={v})')


def run_port(src, dst, src_img, dst_img, out):
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'port_symbols.py'), '--from', src, '--to', dst,
                        '--from-img', src_img, '--to-img', dst_img, '--out', out], capture_output=True, text=True)
    return r.stdout + r.stderr


def checks(output):
    return {line.split()[1]: line.startswith('PASS') for line in output.splitlines() if line[:4] in ('PASS', 'FAIL')}


class TestPort(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pk-port-')
        for c in ('m4', 'm7'):
            shutil.copy(os.path.join(ROOT, 'symbols', f'v1.3.0-{c}.json'), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_self_port_is_exact(self):
        need_funcs('v1.3.0')
        img = require_image('v1.3.0')
        out = run_port('v1.3.0', 'v1.3.0', img, img, self.tmp)
        self.assertTrue(all(checks(out).values()), out[-2000:])
        for c in ('m4', 'm7'):
            with open(os.path.join(self.tmp, f'v1.3.0-{c}.json')) as f:
                a = json.load(f)
            with open(os.path.join(self.tmp, f'v1.3.0-{c}.ported.json')) as f:
                b = json.load(f)
            for sec in ('functions', 'globals', 'memory', 'offsets', 'main_points', 'ipc'):
                for k, v in a.get(sec, {}).items():
                    if not k.startswith('_'):
                        with self.subTest(core=c, section=sec, key=k):
                            self.assertEqual(int(v, 16), int(b[sec][k], 16))
            for k, s in a.get('sites', {}).items():
                if not k.startswith('_'):
                    self.assertEqual(int(s['addr'], 16), int(b['sites'][k]['addr'], 16), k)
            self.assertEqual(a.get('slot_extents'), b.get('slot_extents'))
        # the mods' hook sites port with them, into <out>/mods/<mod>/
        from perkons.mods import symbol_overlays
        for c in ('m4', 'm7'):
            for o in symbol_overlays(os.path.join(ROOT, 'symbols', f'v1.3.0-{c}.json')):
                mod = os.path.basename(os.path.dirname(os.path.dirname(o)))
                with open(o) as f:
                    a = json.load(f)
                with open(os.path.join(self.tmp, 'mods', mod, f'v1.3.0-{c}.json')) as f:
                    b = json.load(f)
                for k, s in a['sites'].items():
                    if not k.startswith('_'):
                        with self.subTest(mod=mod, site=k):
                            self.assertEqual(int(s['addr'], 16), int(b['sites'][k]['addr'], 16))

    def test_backport_to_1_2_1(self):
        need_funcs('v1.3.0', 'v1.2.1')
        out = run_port('v1.3.0', 'v1.2.1', require_image('v1.3.0'), require_image('v1.2.1'), self.tmp)
        res = checks(out)
        # everything 1.2.1 has must check out ...
        for name in ('m7_boot', 'm7_params', 'm7_setters', 'm7_render', 'm7_extents', 'm7_system',
                     'm7_statics', 'm7_rand', 'm4_ipc', 'm4_json', 'm4_snprintf'):
            with self.subTest(check=name):
                self.assertTrue(res.get(name), out[-3000:])
        # ... and what it lacks (runtime sample loading, added in 1.3) must be reported, not faked
        self.assertFalse(res.get('m7_samples'))
