"""JPEG decoder tests.

Ground truth: the fixture is a real photograph file, decoded
earlier in this project by a decoder whose output was independently
validated (vision-checked against the original image; the entropy stream
was verified to be consumed exactly to the file trailer). Quadrant means
and dimensions are pinned to that validated decode.
"""

import unittest
from pathlib import Path

from imadeco import DECODERS

LOGO = Path("/home/user/uploads/7d18773a-8719-4637-84ff-08620d46c0bc-IMG_9736.webp")


def _quadrant_mean(img, x0, x1, y0, y1):
    rs = gs = bs = 0
    n = (x1 - x0) * (y1 - y0)
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = img.pixel(x, y)
            rs += r; gs += g; bs += b
    return (rs // n, gs // n, bs // n)


@unittest.skipUnless(LOGO.exists(), "logo fixture not present in this environment")
class JpegLogoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(LOGO, "rb") as f:
            cls.img = DECODERS["JPEG"].decode(f.read())

    def test_dimensions_and_format(self):
        self.assertEqual(self.img.width, 720)
        self.assertEqual(self.img.height, 416)
        self.assertEqual(self.img.metadata["format"], "JPEG")
        self.assertEqual(self.img.color, "RGB")

    def test_quadrant_means_match_validated_decode(self):
        # Values recorded from the vision-validated decode (session log).
        cases = [
            ((0, 80, 0, 60), (70, 44, 35)),
            ((640, 720, 0, 60), (82, 71, 41)),
            ((0, 80, 356, 416), (39, 11, 17)),
            ((640, 720, 356, 416), (24, 37, 38)),
        ]
        for (x0, x1, y0, y1), expected in cases:
            got = _quadrant_mean(self.img, x0, x1, y0, y1)
            for g, e in zip(got, expected):
                self.assertLessEqual(abs(g - e), 3,
                                     f"quadrant {(x0,y0)} mean {got} != {expected}")

    def test_image_is_not_flat(self):
        r0 = self.img.pixel(10, 10)
        r1 = self.img.pixel(360, 208)
        self.assertNotEqual(r0, r1)


class JpegRoundTripTest(unittest.TestCase):
    @unittest.skipUnless(LOGO.exists(), "logo fixture not present")
    def test_jpeg_png_roundtrip_preserves_pixels(self):
        """JPEG decode -> PNG encode -> PNG decode must preserve every pixel."""
        from imadeco.encoder.png import encode_png
        with open(LOGO, "rb") as f:
            img = DECODERS["JPEG"].decode(f.read())
        png = encode_png(img.width, img.height, img.color, img.pixels)
        back = DECODERS["PNG"].decode(png)
        self.assertEqual((back.width, back.height), (img.width, img.height))
        self.assertEqual(back.color, img.color)
        self.assertEqual(back.pixels, img.pixels)


class JpegErrorTest(unittest.TestCase):
    def test_garbage_rejected(self):
        from imadeco import CorruptImageError
        with self.assertRaises(CorruptImageError):
            DECODERS["JPEG"].decode(b"\xff\xd8\xff\xe0" + b"\x00" * 100)


if __name__ == "__main__":
    unittest.main()

