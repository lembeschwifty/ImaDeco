"""GIF decoder tests. The fixture writer emits uncompressed LZW literals,
so the pixel values in these GIFs are independent ground truth.
"""

import unittest

from imadeco import DECODERS
from fixtures import make_gif


def decode(gif_bytes):
    return DECODERS["GIF"].decode(gif_bytes)


class GifBasicTest(unittest.TestCase):
    PALETTE = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (9, 9, 9)]

    def test_basic_first_frame(self):
        idx = [0, 1, 2, 3, 3, 2, 1, 0]
        img = decode(make_gif(4, 2, self.PALETTE, idx))
        self.assertEqual((img.width, img.height), (4, 2))
        self.assertEqual(img.color, "RGB")
        self.assertEqual(img.pixel(0, 0), (255, 0, 0))
        self.assertEqual(img.pixel(3, 0), (9, 9, 9))
        self.assertEqual(img.pixel(0, 1), (9, 9, 9))  # idx[4] = 3
        self.assertEqual(img.pixel(3, 1), (255, 0, 0))  # idx[7] = 0
        self.assertEqual(img.metadata["frame_count"], 1)

    def test_transparency_makes_rgba(self):
        idx = [0, 1, 2, 3]
        img = decode(make_gif(2, 2, self.PALETTE, idx, transparent_index=1))
        self.assertEqual(img.color, "RGBA")
        self.assertEqual(img.pixel(1, 0), (0, 255, 0, 0))  # transparent
        self.assertEqual(img.pixel(0, 0), (255, 0, 0, 255))

    def test_frame_counting(self):
        idx = [0, 1]
        img = decode(make_gif(2, 1, self.PALETTE, idx, extra_frames=3))
        self.assertEqual(img.metadata["frame_count"], 4)
        self.assertEqual((img.width, img.height), (2, 1))

    def test_interlaced(self):
        # 8-row interlaced image; decoder must reconstruct row order.
        w, h = 2, 8
        idx = []
        for y in range(h):
            idx.extend([y, y])  # row y painted with value y in both columns
        img = decode(make_gif(w, h, [(i * 16, i * 8, i * 4) for i in range(16)], idx,
                              interlaced=True))
        self.assertTrue(img.metadata["interlaced"])
        for y in range(h):
            r, g, b = img.pixel(0, y)
            self.assertEqual(r, y * 16, f"row {y} came back in the wrong order")

    def test_truncated_lzw(self):
        from imadeco import CorruptImageError
        good = make_gif(4, 2, self.PALETTE, [0] * 8)
        with self.assertRaises(CorruptImageError):
            decode(good[: len(good) // 2])


if __name__ == "__main__":
    unittest.main()

