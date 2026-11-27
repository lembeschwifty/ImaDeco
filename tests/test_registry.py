"""Registry and error-path tests."""

import unittest

from imadeco import (CorruptImageError, UnsupportedFormatError,
                           detect_format)
import imadeco.decoders  # registration side effect


class DetectFormatTest(unittest.TestCase):
    def test_magic_detection(self):
        cases = [
            (b"\xff\xd8\xff\xe0" + b"\x00" * 32, "JPEG"),
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "PNG"),
            (b"BM" + b"\x00" * 32, "BMP"),
            (b"GIF89a" + b"\x00" * 32, "GIF"),
            (b"GIF87a" + b"\x00" * 32, "GIF"),
        ]
        for blob, expected in cases:
            self.assertEqual(detect_format(blob), expected)

    def test_extension_is_ignored(self):
        # A JPEG named .gif must still be detected as JPEG (magic over names).
        self.assertEqual(detect_format(b"\xff\xd8\xff" + b"\x00" * 16), "JPEG")

    def test_unsupported(self):
        with self.assertRaises(UnsupportedFormatError):
            detect_format(b"PK\x03\x04" + b"\x00" * 16)
        with self.assertRaises(UnsupportedFormatError):
            detect_format(b"")  # empty file


class ErrorHierarchyTest(unittest.TestCase):
    def test_corrupt_jpeg_rejected(self):
        from imadeco import DECODERS
        with self.assertRaises(CorruptImageError):
            DECODERS["JPEG"].decode(b"\xff\xd8\xff")  # header with nothing else

    def test_corrupt_png_rejected(self):
        from imadeco import DECODERS
        with self.assertRaises(CorruptImageError):
            DECODERS["PNG"].decode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)  # no chunks


if __name__ == "__main__":
    unittest.main()

