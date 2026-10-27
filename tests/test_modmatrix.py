"""Mod Matrix: catalogue (mod.json options, image checks) and the local server's API.
The build test needs arm-none-eabi-gcc only if a mod has C code (this one doesn't)."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from fixtures import require_image
from perkons import catalog
from perkons.fwimage import Image

import modmatrix

OPTIONS = {'options': [
    {'id': 'tag', 'title': 'TAG BUILD', 'summary': 'Banner tag only.', 'patches': ['tag_build'], 'code': 'tg'},
    {'id': 'any', 'title': 'STAMP', 'summary': 'Stamp only.', 'patches': ['version_stamp:x'], 'code': 'st',
     'conflicts': ['tag']},
    {'id': 'needs', 'title': 'NEEDS TAG', 'summary': 'Needs the tag option.', 'patches': ['tag_build'],
     'code': 'nt', 'requires': ['tag']},
]}


class TestModMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(require_image('v1.3.0'), 'rb') as f:
            cls.raw = f.read()
        cls.tmp = tempfile.mkdtemp(prefix='pk-mm-')
        mod = os.path.join(cls.tmp, 'demo-mod')
        os.makedirs(os.path.join(mod, 'patches'))
        with open(os.path.join(mod, 'mod.json'), 'w') as f:
            json.dump(OPTIONS, f)
        cls.saved_mods = os.environ.get('PERKONS_MODS')
        os.environ['PERKONS_MODS'] = mod
        cls.server, cls.app = modmatrix.serve(0, intro=False)
        cls.url = f'http://127.0.0.1:{cls.server.server_address[1]}'
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if cls.saved_mods is None:
            os.environ.pop('PERKONS_MODS', None)
        else:
            os.environ['PERKONS_MODS'] = cls.saved_mods
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(cls.app.work, ignore_errors=True)

    def call(self, path, body=None, json_body=None):
        data = json.dumps(json_body).encode() if json_body is not None else body
        req = urllib.request.Request(self.url + path, data=data)
        if json_body is not None:
            req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers['Content-Type'] == 'application/json' else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    # -- catalogue ---------------------------------------------------------------------
    def test_options_take_target_and_risk_from_patches(self):
        opts = {o['id']: o for o in catalog.options()}
        self.assertEqual((opts['tag']['target'], opts['tag']['risk']), ('1.3.0', 'none'))
        self.assertEqual((opts['any']['target'], opts['any']['risk']), (None, 'low'))

    def test_selection_rules(self):
        with self.assertRaises(catalog.CatalogError):
            catalog.check_selection([], '1.3.0')
        with self.assertRaises(catalog.CatalogError):
            catalog.check_selection(['tag'], '1.2.2')                  # wrong version
        with self.assertRaises(catalog.CatalogError):
            catalog.check_selection(['tag', 'any'], '1.3.0')           # declared conflict
        with self.assertRaises(catalog.CatalogError):
            catalog.check_selection(['needs'], '1.3.0')                # missing requirement
        catalog.check_selection(['needs', 'tag'], '1.3.0')
        _, specs = catalog.check_selection(['tag'], '1.3.0')
        self.assertEqual(specs, ['tag_build'])

    def test_build_tag_fits_the_version_field(self):
        many = [{'id': f'o{i}', 'code': 'ab'} for i in range(8)]
        self.assertEqual(catalog.build_tag(many[:2]), 'mm-abab')
        self.assertLessEqual(len(catalog.build_tag(many)), catalog.MAX_TAG)

    def test_inspect(self):
        _, info = catalog.inspect(self.raw)
        self.assertEqual((info['version'], info['official'], info['supported']), ('1.3.0', True, True))
        modified = bytearray(self.raw)
        modified[-1] ^= 0xff
        with self.assertRaises(catalog.CatalogError):
            catalog.inspect(bytes(modified))                            # CRC
        with self.assertRaises(catalog.CatalogError):
            catalog.inspect(os.urandom(4096))

    # -- server --------------------------------------------------------------------------
    def test_server_rejects_junk_and_unknown_images(self):
        code, j = self.call('/api/inspect', body=os.urandom(2048))
        self.assertEqual(code, 400)
        self.assertIn('error', j)
        code, j = self.call('/api/build', json_body={'image': 'nope', 'options': ['tag']})
        self.assertEqual(code, 400)

    def test_server_serves_the_page(self):
        code, page = self.call('/')
        self.assertEqual(code, 200)
        self.assertIn(b'SLOP IT UP', page)

    def test_build_and_download(self):
        code, info = self.call('/api/inspect', body=self.raw)
        self.assertEqual((code, info['official']), (200, True))
        code, j = self.call('/api/build', json_body={'image': info['image'], 'options': ['tag'], 'checks': False})
        self.assertEqual(code, 200)
        for _ in range(600):
            _, snap = self.call(f'/api/job/{j["job"]}')
            if snap['state'] != 'running':
                break
            time.sleep(0.2)
        self.assertEqual(snap['state'], 'done', snap['log'][-8:])
        self.assertEqual(snap['name'], 'perkons_v1.3.0-0-force.img')
        code, data = self.call(snap['download'])
        img = Image.parse(data)
        self.assertTrue(all(s.crc_ok for s in img.segments))
        self.assertIn(b'mm-tg', img.segment('m4').data)                 # INFO.TXT stamp
        self.assertNotEqual(data, self.raw)
