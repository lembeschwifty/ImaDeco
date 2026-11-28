"""PNG decoder tests fed by the independent fixture writer, plus encoder
round trips. Fixture PNGs are built by tests/fixtures.py (not by the code
under test) for decode-side truth; encoder round trips validate that our
own encoder and decoder agree.
"""

import unittest

from imadeco import DECODERS
from imadeco.encoder.png import encode_png
try:
    from tests.fixtures import make_png
except ImportError:  # running from inside the tests directory
    from fixtures import make_png


def decode(png_bytes):
    return DECODERS["PNG"].decode(png_bytes)


class PngDecodeTest(unittest.TestCase):
    def test_rgb(self):
        w, h = 3, 2
        pixels = bytes([
            255, 0, 0,  0, 255, 0,  0, 0, 255,
            1, 2, 3,    4, 5, 6,    7, 8, 9,
        ])
        img = decode(make_png(w, h, "RGB", pixels))
        self.assertEqual((img.width, img.height), (w, h))
        self.assertEqual(img.color, "RGB")
        self.assertEqual(img.pixels, pixels)
        self.assertEqual(img.pixel(0, 0), (255, 0, 0))
        self.assertEqual(img.pixel(2, 1), (7, 8, 9))

    def test_grayscale(self):
        pixels = bytes([0, 64, 128, 255, 10, 20])
        img = decode(make_png(3, 2, "L", pixels))
        self.assertEqual(img.color, "L")
        self.assertEqual(img.pixels, pixels)

    def test_rgba(self):
        pixels = bytes([1, 2, 3, 4, 5, 6, 7, 8])
        img = decode(make_png(1, 2, "RGBA", pixels))
        self.assertEqual(img.color, "RGBA")
        self.assertEqual(img.pixels, pixels)

    def test_interlaced_rejected(self):
        import struct, zlib
        # hand-build IHDR with interlace=1
        def chunk(t, body):
            return struct.pack(">I", len(body)) + t + body + struct.pack(
                ">I", zlib.crc32(t + body) & 0xFFFFFFFF)
        blob = (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 1))
                + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
                + chunk(b"IEND", b""))
        from imadeco import UnsupportedFeatureError
        with self.assertRaises(UnsupportedFeatureError):
            decode(blob)


class PngRoundTripTest(unittest.TestCase):
    def test_roundtrip_all_color_modes(self):
        cases = [
            ("L", 5, 4, bytes(range(20))),
            ("RGB", 3, 2, bytes(range(18))),
            ("RGBA", 2, 2, bytes(range(16))),
        ]
        for color, w, h, pixels in cases:
            png = encode_png(w, h, color, pixels)
            img = decode(png)
            self.assertEqual((img.width, img.height), (w, h))
            self.assertEqual(img.color, color)
            self.assertEqual(img.pixels, pixels, f"roundtrip failed for {color}")


class PngSecurityTest(unittest.TestCase):
    def test_decompression_bomb_rejected(self):
        """A tiny IDAT claiming huge dimensions must fail fast, not
        allocate the full expansion (URL's audit finding)."""
        import struct, zlib
        # 1,000,000 x 1,000,000 RGB declared: 3,000,001,000 bytes expected.
        bomb_data = zlib.compress(b"\x00" * 300)  # decompresses small, but...
        def chunk(t, body):
            return struct.pack(">I", len(body)) + t + body + struct.pack(
                ">I", zlib.crc32(t + body) & 0xFFFFFFFF)
        blob = (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 10 ** 6, 10 ** 6, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", bomb_data)
                + chunk(b"IEND", b""))
        from imadeco import CorruptImageError
        with self.assertRaises(CorruptImageError):
            decode(blob)

    def test_overlong_idat_rejected(self):
        """Correct dimensions but more decompressed data than allowed."""
        import struct, zlib
        # 2x1 RGB needs 8 bytes (2 rows x (1 + 3)); supply 16.
        def chunk(t, body):
            return struct.pack(">I", len(body)) + t + body + struct.pack(
                ">I", zlib.crc32(t + body) & 0xFFFFFFFF)
        blob = (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"\x00" * 16))
                + chunk(b"IEND", b""))
        from imadeco import CorruptImageError
        with self.assertRaises(CorruptImageError):
            decode(blob)


if __name__ == "__main__":
    unittest.main()
