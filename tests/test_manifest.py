"""Each mod repo on disk (PERKONS_MODS) has a perkons-mods.json that matches its mods: the
Mod Matrix shows mods and their memory from it, so it must be regenerated (make manifest)
whenever a mod, or what it takes, changes."""
import json
import os
import shutil
import unittest

from fixtures import require_image
from perkons import repos
from perkons.mods import mod_dirs

import manifest


def repo_roots():
    return sorted({r for r, _ in (repos.repo_root(d) for d in mod_dirs()) if r})


@unittest.skipUnless(shutil.which('arm-none-eabi-gcc'), 'arm-none-eabi-gcc not installed')
class TestManifest(unittest.TestCase):
    def test_every_repo_manifest_is_current(self):
        roots = repo_roots()
        if not roots:
            self.skipTest('no mod repo on disk (PERKONS_MODS)')
        images = {'1.3.0': require_image('v1.3.0')}
        for root in roots:
            with self.subTest(repo=root):
                path = os.path.join(root, repos.MANIFEST)
                self.assertTrue(os.path.exists(path), f'no {repos.MANIFEST}: run make manifest MODS={root}')
                with open(path) as f:
                    on_disk = json.load(f)
                self.assertEqual(on_disk, manifest.build(root, images),
                                 f'{path} is out of date: run make manifest MODS={root}')
