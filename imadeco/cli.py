"""Command line interface for ImaDeco.

Usage:
    python -m imadeco decode FILE... [--json]
    python -m imadeco convert FILE -o OUTPUT.png
    python -m imadeco inspect FILE... [--json]      (v0.2)
    python -m imadeco verify FILE... [--json]       (v0.2)
    python -m imadeco salvage FILE -o OUTPUT.png     (v0.2)

Files may also be directories; a directory is expanded to the image files
it contains (non-recursive).

Exit codes: 0 success, 1 file/decode error or problem found,
2 usage error, 3 salvage succeeded with partial loss (ADR-10).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .decoders import bmp, gif, jpeg, png  # noqa: F401  (registration side effect)
from .encoder.png import encode_png
from .exceptions import ImageDecodeError
from .registry import DECODERS, detect_format
from .report import walk

_FIELD_LABELS = [
    ("format", "Format"), ("width", "Width"), ("height", "Height"),
    ("color", "Pixel layout"), ("precision", "Precision"),
    ("bit_depth", "Bit depth"), ("color_type", "Color type"),
    ("bpp", "Bits per pixel"), ("top_down", "Top-down rows"),
    ("compression", "Compression"), ("header_size", "DIB header size"),
    ("version", "GIF version"), ("frame_count", "Frames"),
    ("interlaced", "Interlaced"), ("transparent_index", "Transparent index"),
    ("canvas_size", "Canvas size"), ("components", "Sampling"),
    ("restart_interval", "Restart interval"),
]


def _read_bytes(path: str) -> bytes:
    p = Path(path)
    if not p.exists():
        raise ImageDecodeError(f"file not found: {path}")
    try:
        return p.read_bytes()
    except OSError as e:
        raise ImageDecodeError(f"cannot read {path}: {e}") from e


def _decode_file(path: str):
    data = _read_bytes(path)
    fmt = detect_format(data)
    return DECODERS[fmt].decode(data)


def _expand_files(paths: list[str]) -> list[str]:
    """Expand directories to contained image files; keep file paths as-is."""
    out = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file():
                    out.append(str(child))
        else:
            out.append(p)
    return out


def cmd_decode(args: argparse.Namespace) -> int:
    files = _expand_files(args.file)
    worst = 0
    for path in files:
        try:
            image = _decode_file(path)
        except ImageDecodeError as e:
            print(f"error: {e}", file=sys.stderr)
            worst = 1
            continue
        summary = image.summary()
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        else:
            width = summary.pop("width")
            height = summary.pop("height")
            print(f"{Path(path).name}: {width} x {height}")
            for key, label in _FIELD_LABELS:
                if key in summary:
                    print(f"  {label}: {summary[key]}")
    if len(files) > 1:
        print(f"processed {len(files)} file(s), {worst} error(s)")
    return worst


def cmd_convert(args: argparse.Namespace) -> int:
    image = _decode_file(args.file)
    out = Path(args.output)
    if out.suffix.lower() != ".png":
        raise ImageDecodeError(f"v0.1 converts to PNG only (got output name {args.output!r})")
    png_bytes = encode_png(image.width, image.height, image.color, image.pixels)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_bytes(png_bytes)
    tmp.replace(out)
    print(f"{Path(args.file).name} ({image.metadata.get('format')}) -> {out} "
          f"({image.width}x{image.height}, {image.color}, {len(png_bytes)} bytes)")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    files = _expand_files(args.file)
    worst = 0
    for path in files:
        try:
            data = _read_bytes(path)
            rep = walk(data)
        except ImageDecodeError as e:
            print(f"error: {e}", file=sys.stderr)
            worst = 1
            continue
        if args.json:
            doc = rep.to_json()
            doc["file"] = path
            print(json.dumps(doc, indent=2, sort_keys=True, default=str))
        else:
            print(rep.to_text(path))
        if not rep.ok:
            worst = 1
    if len(files) > 1:
        print(f"inspected {len(files)} file(s), {worst} damaged")
    return worst


def cmd_verify(args: argparse.Namespace) -> int:
    files = _expand_files(args.file)
    failed = warned = clean = 0
    for path in files:
        try:
            data = _read_bytes(path)
            rep = walk(data)
        except ImageDecodeError as e:
            print(f"{Path(path).name}: FAIL ({e})")
            failed += 1
            continue
        verdict = "FAIL" if rep.errors else ("WARN" if rep.warnings else "OK")
        if rep.errors:
            failed += 1
        elif rep.warnings:
            warned += 1
        else:
            clean += 1
        if args.json:
            doc = rep.to_json()
            doc["file"] = path
            doc["verdict"] = verdict
            print(json.dumps(doc, indent=2, sort_keys=True, default=str))
        else:
            print(f"{path}: {verdict}")
            for e in rep.errors:
                print(f"  error: {e}")
            for w in rep.warnings:
                print(f"  warning: {w}")
    if len(files) > 1:
        print(f"verified {len(files)} file(s): {clean} ok, "
              f"{warned} with warnings, {failed} failed")
    return 1 if failed else 0


def cmd_salvage(args: argparse.Namespace) -> int:
    data = _read_bytes(args.file)
    fmt = detect_format(data)
    decoder = DECODERS[fmt]
    image, recovered, total = decoder.salvage(data)
    out = Path(args.output)
    if out.suffix.lower() != ".png":
        raise ImageDecodeError(f"salvage writes PNG only (got output name {args.output!r})")
    png_bytes = encode_png(image.width, image.height, image.color, image.pixels)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_bytes(png_bytes)
    tmp.replace(out)
    if recovered is None:
        print(f"{Path(args.file).name} ({fmt}) was intact; wrote full image -> {out} "
              f"({image.width}x{image.height}, {image.color})")
        return 0
    print(f"{Path(args.file).name} ({fmt}): recovered {recovered} of {total} rows "
          f"-> {out} ({image.width}x{recovered}, {image.color}, partial image)")
    return 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imadeco",
        description="Decode JPEG, PNG, BMP and GIF images; inspect, verify and "
                    "salvage them; convert to PNG.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dec = sub.add_parser("decode", help="show image metadata")
    p_dec.add_argument("file", nargs="+", help="image file (or directory) to decode")
    p_dec.add_argument("--json", action="store_true", help="machine-readable output")
    p_dec.set_defaults(func=cmd_decode)

    p_con = sub.add_parser("convert", help="convert an image to PNG")
    p_con.add_argument("file", help="image file to convert")
    p_con.add_argument("-o", "--output", required=True, help="output .png path")
    p_con.set_defaults(func=cmd_convert)

    p_ins = sub.add_parser("inspect", help="show bitstream structure report")
    p_ins.add_argument("file", nargs="+", help="image file (or directory) to inspect")
    p_ins.add_argument("--json", action="store_true", help="machine-readable output")
    p_ins.set_defaults(func=cmd_inspect)

    p_ver = sub.add_parser("verify", help="strictly validate image structure")
    p_ver.add_argument("file", nargs="+", help="image file (or directory) to verify")
    p_ver.add_argument("--json", action="store_true", help="machine-readable output")
    p_ver.set_defaults(func=cmd_verify)

    p_sal = sub.add_parser("salvage", help="recover a damaged image to PNG, best effort")
    p_sal.add_argument("file", help="image file to salvage")
    p_sal.add_argument("-o", "--output", required=True, help="output .png path")
    p_sal.set_defaults(func=cmd_salvage)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ImageDecodeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

