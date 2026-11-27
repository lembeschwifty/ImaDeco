"""Tests for the v0.2 verify/inspect/salvage CLI surface (ADR-9, ADR-10)."""

import os
import tempfile
import unittest
from pathlib import Path

import fixtures
from imadeco import cli

from test_inspect import _png_bytes, _bmp_bytes, _gif_bytes


class _CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        p = self.dir / name
        p.write_bytes(data)
        return str(p)


class TestVerifyCli(_CliTest):
    def test_verify_clean_directory_exits_zero(self):
        self.write("good.png", _png_bytes())
        self.write("good.bmp", _bmp_bytes())
        self.write("good.gif", _gif_bytes())
        rc = cli.main(["verify", str(self.dir)])
        self.assertEqual(rc, 0)

    def test_verify_mixed_directory_exits_one_with_summary(self):
        self.write("good.png", _png_bytes())
        data = _png_bytes()
        self.write("cut.png", data[:len(data) // 2])
        rc = cli.main(["verify", str(self.dir)])
        self.assertEqual(rc, 1)

    def test_verify_json_output(self):
        import json
        p = self.write("good.png", _png_bytes())
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["verify", p, "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["format"], "PNG")
        self.assertEqual(doc["verdict"], "OK")
        self.assertTrue(doc["ok"])

    def test_verify_missing_file_fails(self):
        rc = cli.main(["verify", str(self.dir / "nope.png")])
        self.assertEqual(rc, 1)


class TestInspectCli(_CliTest):
    def test_inspect_human_output(self):
        import io
        from contextlib import redirect_stdout
        p = self.write("good.png", _png_bytes())
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["inspect", p])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("PNG", out)
        self.assertIn("Dimensions: 8 x 6", out)
        self.assertIn("Verdict: OK", out)

    def test_inspect_damaged_file_exits_one(self):
        data = _png_bytes()
        p = self.write("cut.png", data[:len(data) // 2])
        rc = cli.main(["inspect", p])
        self.assertEqual(rc, 1)


class TestSalvageCli(_CliTest):
    def test_salvage_truncated_png_recovers_top_rows_exit_3(self):
        full = _png_bytes(8, 6)
        p = self.write("cut.png", full[:len(full) // 2])
        out = str(self.dir / "rec.png")
        rc = cli.main(["salvage", p, "-o", out])
        self.assertEqual(rc, 3)
        self.assertTrue(Path(out).exists())
        # The recovered image must re-decode cleanly.
        from imadeco import decode_file
        img = decode_file(out)
        self.assertEqual(img.width, 8)
        self.assertLess(img.height, 6)
        self.assertGreaterEqual(img.height, 1)

    def test_salvage_healthy_file_exits_zero(self):
        p = self.write("good.png", _png_bytes())
        out = str(self.dir / "rec.png")
        rc = cli.main(["salvage", p, "-o", out])
        self.assertEqual(rc, 0)
        from imadeco import decode_file
        img = decode_file(out)
        self.assertEqual((img.width, img.height), (8, 6))

    def test_salvage_truncated_bmp_exit_3(self):
        data = _bmp_bytes(6, 5)
        p = self.write("cut.bmp", data[:14 + 40 + 40])  # 2 of 5 rows survive
        out = str(self.dir / "rec.png")
        rc = cli.main(["salvage", p, "-o", out])
        self.assertEqual(rc, 3)
        from imadeco import decode_file
        img = decode_file(out)
        self.assertEqual(img.width, 6)
        self.assertEqual(img.height, 2)

    def test_salvage_truncated_gif_exit_3(self):
        data = _gif_bytes(4, 4)
        p = self.write("cut.gif", data[:len(data) - 10])
        out = str(self.dir / "rec.png")
        rc = cli.main(["salvage", p, "-o", out])
        self.assertEqual(rc, 3)
        from imadeco import decode_file
        img = decode_file(out)
        self.assertEqual(img.width, 4)
        self.assertGreaterEqual(img.height, 1)
        self.assertLess(img.height, 4)

    def test_salvage_garbage_exits_one(self):
        p = self.write("junk.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        rc = cli.main(["salvage", p, "-o", str(self.dir / "x.png")])
        self.assertEqual(rc, 1)

    def test_salvage_rejects_non_png_output_name(self):
        p = self.write("good.png", _png_bytes())
        rc = cli.main(["salvage", p, "-o", str(self.dir / "x.bmp")])
        self.assertEqual(rc, 1)


class TestBatchDecode(_CliTest):
    def test_decode_directory_with_bad_file_reports_error(self):
        self.write("good.png", _png_bytes())
        data = _png_bytes()
        self.write("cut.png", data[:20])
        rc = cli.main(["decode", str(self.dir)])
        self.assertEqual(rc, 1)

    def test_decode_directory_all_good(self):
        self.write("good.png", _png_bytes())
        self.write("good.bmp", _bmp_bytes())
        rc = cli.main(["decode", str(self.dir)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
