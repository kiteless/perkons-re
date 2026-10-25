import unittest

from fixtures import IMAGES, require_image
from perkons.fwimage import Image


class TestContainer(unittest.TestCase):
    def test_official_images_roundtrip(self):
        for version in IMAGES:
            with self.subTest(version=version):
                with open(require_image(version), 'rb') as f:
                    raw = f.read()
                img = Image.parse(raw)
                self.assertEqual(f'v{img.version}', version)
                self.assertTrue(all(s.crc_ok for s in img.segments))
                self.assertEqual(img.build(recompute_crc=False), raw)
                self.assertEqual(img.build(recompute_crc=True), raw)

    def test_segment_layout(self):
        img = Image.load(require_image('v1.3.0'))
        self.assertEqual(img.segment('m4').addr, 0x08100000)
        self.assertEqual(img.segment('m7').addr, 0x08020000)
