"""BMP decoder tests. Fixtures are written by the independent BMP writer
in tests/fixtures.py, so expected pixels are ground truth.
"""

import unittest

from imadeco import DECODERS
from fixtures import make_bmp24, make_bmp8


def decode(bmp_bytes):
    return DECODERS["BMP"].decode(bmp_bytes)


class Bmp24Test(unittest.TestCase):
    def test_basic_bottom_up(self):
        rows = [
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
            [(1, 2, 3), (4, 5, 6), (7, 8, 9)],
        ]
        img = decode(make_bmp24(3, 2, rows))
        self.assertEqual((img.width, img.height), (3, 2))
        self.assertEqual(img.color, "RGB")
        self.assertEqual(img.pixel(0, 0), (255, 0, 0))
        self.assertEqual(img.pixel(2, 1), (7, 8, 9))
        flat = b"".join(bytes(px) for row in rows for px in row)
        self.assertEqual(img.pixels, flat)

    def test_row_padding_odd_width(self):
        # width 3 at 24bpp needs 1 padding byte per row; truncation here
        # would fail loudly.
        rows = [[(10 * x, 5 * x, x) for x in range(3)] for _ in range(4)]
        img = decode(make_bmp24(3, 4, rows))
        self.assertEqual(img.pixel(2, 3), tuple(rows[3][2]))

    def test_top_down(self):
        rows = [
            [(1, 1, 1), (2, 2, 2)],
            [(3, 3, 3), (4, 4, 4)],
        ]
        img = decode(make_bmp24(2, 2, rows, top_down=True))
        self.assertTrue(img.metadata["top_down"])
        self.assertEqual(img.pixel(0, 0), (1, 1, 1))
        self.assertEqual(img.pixel(1, 1), (4, 4, 4))


class Bmp8Test(unittest.TestCase):
    def test_paletted(self):
        palette = [(250, 10, 30), (20, 200, 40), (30, 40, 250)]
        indices = [[0, 1, 2], [2, 1, 0]]
        img = decode(make_bmp8(3, 2, palette, indices))
        self.assertEqual(img.pixel(0, 0), (250, 10, 30))
        self.assertEqual(img.pixel(2, 0), (30, 40, 250))
        self.assertEqual(img.pixel(0, 1), (30, 40, 250))
        self.assertEqual(img.metadata["bpp"], 8)


class BmpErrorTest(unittest.TestCase):
    def test_truncated(self):
        from imadeco import CorruptImageError
        good = make_bmp24(4, 4, [[(1, 2, 3)] * 4 for _ in range(4)])
        with self.assertRaises(CorruptImageError):
            decode(good[:60])

    def test_compression_rejected(self):
        import struct
        from imadeco import UnsupportedFeatureError
        blob = bytearray(make_bmp24(2, 2, [[(0, 0, 0)] * 2 for _ in range(2)]))
        blob[30:34] = struct.pack("<I", 1)  # BI_RLE8
        with self.assertRaises(UnsupportedFeatureError):
            decode(bytes(blob))


if __name__ == "__main__":
    unittest.main()

