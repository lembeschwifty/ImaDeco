"""Tests for the v0.2 structure walk (ADR-8): inspect on good and bad files."""

import unittest

import fixtures
from imadeco.report import walk
from imadeco.exceptions import UnsupportedFormatError


def _png_bytes(w=8, h=6):
    px = bytearray()
    for y in range(h):
        for x in range(w):
            px += bytes([x * 30 % 256, y * 40 % 256, (x + y) % 256])
    return fixtures.make_png(w, h, "RGB", px)


def _bmp_bytes(w=6, h=5):
    return fixtures.make_bmp24(w, h, [[(i * 9, j * 9, 60) for i in range(w)]
                                     for j in range(h)])


def _gif_bytes(w=4, h=4):
    idx = [(x + y) % 4 for y in range(h) for x in range(w)]
    return fixtures.make_gif(w, h, [(255, 0, 0), (0, 255, 0), (0, 0, 255),
                                   (255, 255, 0)], idx)


class TestWalkPng(unittest.TestCase):
    def test_good_png_reports_ok(self):
        rep = walk(_png_bytes())
        self.assertEqual(rep.format, "PNG")
        self.assertEqual((rep.width, rep.height), (8, 6))
        self.assertTrue(rep.ok, rep.errors)
        self.assertFalse(rep.warnings)
        names = [e["name"] for e in rep.structure]
        self.assertEqual(names, ["signature", "IHDR", "IDAT", "IEND"])

    def test_truncated_png_reports_errors(self):
        data = _png_bytes()
        rep = walk(data[:len(data) // 2])
        self.assertFalse(rep.ok)
        self.assertTrue(any("truncated" in e for e in rep.errors), rep.errors)
        self.assertTrue(any("IEND" in e for e in rep.errors), rep.errors)

    def test_trailing_garbage_is_a_warning_not_an_error(self):
        rep = walk(_png_bytes() + b"JUNKJUNK")
        self.assertTrue(rep.ok)
        self.assertTrue(any("trailing" in w for w in rep.warnings))

    def test_bad_crc_is_an_error(self):
        data = bytearray(_png_bytes())
        data[40] ^= 0xFF  # corrupt inside IDAT: CRC mismatch
        rep = walk(bytes(data))
        self.assertFalse(rep.ok)
        self.assertTrue(any("CRC" in e for e in rep.errors), rep.errors)

    def test_text_chunk_metadata(self):
        import struct
        import zlib

        def chunk(t, body):
            return struct.pack(">I", len(body)) + t + body + struct.pack(
                ">I", zlib.crc32(t + body) & 0xFFFFFFFF)

        base = _png_bytes()
        text = chunk(b"tEXt", b"Comment\x00hello")
        iend_at = base.rfind(b"\x00\x00\x00\x00IEND")
        data = base[:iend_at] + text + base[iend_at:]
        rep = walk(data)
        self.assertTrue(rep.ok, rep.errors)
        self.assertIn(("Comment", "hello"), rep.metadata)


class TestWalkBmp(unittest.TestCase):
    def test_good_bmp_reports_ok(self):
        rep = walk(_bmp_bytes())
        self.assertEqual((rep.width, rep.height), (6, 5))
        self.assertTrue(rep.ok)
        self.assertEqual(rep.fields["Bits per pixel"], 24)

    def test_truncated_bmp_reports_error(self):
        data = _bmp_bytes()
        rep = walk(data[:14 + 40 + 20])  # only ~2 of 5 rows
        self.assertFalse(rep.ok)
        self.assertTrue(any("truncated pixel data" in e for e in rep.errors),
                        rep.errors)


class TestWalkGif(unittest.TestCase):
    def test_good_gif_reports_ok(self):
        rep = walk(_gif_bytes())
        self.assertEqual((rep.width, rep.height), (4, 4))
        self.assertTrue(rep.ok)
        self.assertEqual(rep.fields["Frames"], 1)
        names = [e["name"] for e in rep.structure]
        self.assertIn("trailer", names)

    def test_missing_trailer_is_an_error(self):
        data = _gif_bytes()
        rep = walk(data[:-1])  # strip trailer only
        # (fixture's last LZW subblock terminator is inside; strip trailer)
        self.assertFalse(rep.ok)
        self.assertTrue(any("trailer" in e for e in rep.errors), rep.errors)


class TestWalkUnknown(unittest.TestCase):
    def test_unknown_magic_raises(self):
        with self.assertRaises(UnsupportedFormatError):
            walk(b"not an image at all")


if __name__ == "__main__":
    unittest.main()

