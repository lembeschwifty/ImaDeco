"""Minimal PNG encoder (ADR-004). 8-bit L, RGB and RGBA; no interlacing."""

from __future__ import annotations

import struct
import zlib

_COLOR_TYPES = {"L": (0, 1), "RGB": (2, 3), "RGBA": (6, 4)}


def encode_png(width: int, height: int, color: str, pixels: bytes) -> bytes:
    """Encode an interleaved pixel buffer as a valid PNG file."""
    if color not in _COLOR_TYPES:
        raise ValueError(f"unsupported color {color!r} for PNG encoding")
    spp = _COLOR_TYPES[color][1]
    if len(pixels) != width * height * spp:
        raise ValueError("pixel buffer size does not match dimensions")
    color_type = _COLOR_TYPES[color][0]

    raw = bytearray()
    stride = width * spp
    for y in range(height):
        raw.append(0)  # filter type None
        raw.extend(pixels[y * stride:(y + 1) * stride])

    def chunk(ctype: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + ctype + body
                + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))

