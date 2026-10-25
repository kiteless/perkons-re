"""version_stamp finds its targets by marker, so it must work on every official version."""
import struct
import unittest

from fixtures import IMAGES, require_image
from perkons.emu import Symbols
from perkons.fwimage import Image
from perkons.mods import load_patch
from perkons.patch import Patcher

vs = load_patch('version_stamp')


class TestVersionStamp(unittest.TestCase):
    def stamp(self, version, tag='kiteless0.1', banner=None):
        p = Patcher(Image.load(require_image(version)))
        vs.apply(p, tag, banner=banner)
        return p.result()

    def test_all_official_versions(self):
        for version in IMAGES:
            with self.subTest(version=version):
                img = Image.parse(self.stamp(version).build())
                for s in img.segments:
                    self.assertTrue(s.crc_ok)
                    i = s.data.find(b'__FVERSION__')
                    self.assertEqual(s.data[i + 24:i + 36], b'kiteless0.1\0')
                    j = s.data.rfind(b'FW version: %d.%d.%d @ ')  # the new copy, in the cave
                    k = s.data.find(b' + kiteless0.1', j)
                    self.assertGreater(k, j, 'stamped banner string present')
                    addr = s.addr + j
                    self.assertEqual(sum(1 for o in range(0, len(s.data) - 3, 4)
                                         if struct.unpack_from('<I', s.data, o)[0] == addr), 1,
                                     'exactly one literal now points at the stamped banner')

    def test_rejects_bad_tags(self):
        for tag in ('', 'twelve_chars', 'has space', 'ünicode'):
            with self.subTest(tag=tag), self.assertRaises((ValueError, UnicodeEncodeError)):
                self.stamp('v1.3.0', tag)
