"""End-to-end CLI tests via subprocess (exit codes, output, conversion)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from tests.fixtures import make_bmp24, make_gif, make_png
except ImportError:  # running from inside the tests directory
    from fixtures import make_bmp24, make_gif, make_png

LOGO = Path("/home/user/uploads/7d18773a-8719-4637-84ff-08620d46c0bc-IMG_9736.webp")
ROOT = Path(__file__).resolve().parents[1]


def run_cli(args):
    return subprocess.run([sys.executable, "-m", "imadeco", *args],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=120)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_decode_png_human_output(self):
        f = Path(self.tmp.name) / "img.png"
        f.write_bytes(make_png(2, 1, "RGB", bytes([1, 2, 3, 4, 5, 6])))
        proc = run_cli(["decode", str(f)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("2 x 1", proc.stdout)
        self.assertIn("PNG", proc.stdout)

    def test_decode_json_output(self):
        f = Path(self.tmp.name) / "img.png"
        f.write_bytes(make_png(2, 1, "RGB", bytes([1, 2, 3, 4, 5, 6])))
        proc = run_cli(["decode", str(f), "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["width"], 2)
        self.assertEqual(data["format"], "PNG")

    def test_convert_bmp_to_png(self):
        rows = [[(200, 100, 50), (1, 2, 3)], [(4, 5, 6), (7, 8, 9)]]
        src = Path(self.tmp.name) / "in.bmp"
        src.write_bytes(make_bmp24(2, 2, rows))
        out = Path(self.tmp.name) / "out.png"
        proc = run_cli(["convert", str(src), "-o", str(out)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out.exists())
        check = run_cli(["decode", str(out), "--json"])
        data = json.loads(check.stdout)
        self.assertEqual((data["width"], data["height"]), (2, 2))
        self.assertEqual(data["format"], "PNG")

    def test_convert_gif_to_png(self):
        src = Path(self.tmp.name) / "in.gif"
        src.write_bytes(make_gif(3, 2, [(255, 0, 0), (0, 255, 0)], [0, 1, 0, 1, 0, 1]))
        out = Path(self.tmp.name) / "out.png"
        proc = run_cli(["convert", str(src), "-o", str(out)])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_missing_file_exit_1(self):
        proc = run_cli(["decode", "/nonexistent/file.png"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error:", proc.stderr)

    def test_unsupported_file_exit_1(self):
        f = Path(self.tmp.name) / "data.xyz"
        f.write_bytes(b"hello world this is not an image")
        proc = run_cli(["decode", str(f)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Unsupported", proc.stderr)

    def test_usage_error_exit_2(self):
        proc = run_cli([])
        self.assertEqual(proc.returncode, 2)

    @unittest.skipUnless(LOGO.exists(), "logo fixture not present")
    def test_jpeg_logo_end_to_end(self):
        out = Path(self.tmp.name) / "logo.png"
        proc = run_cli(["convert", str(LOGO), "-o", str(out)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("720x416", proc.stdout)
        check = run_cli(["decode", str(out), "--json"])
        data = json.loads(check.stdout)
        self.assertEqual((data["width"], data["height"]), (720, 416))


if __name__ == "__main__":
    unittest.main()
