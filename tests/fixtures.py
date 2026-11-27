"""Shared test fixtures: independent writers for BMP, GIF and PNG inputs.

These writers are deliberately NOT the code under test: they emit the
simplest valid files (uncompressed BMP, literal-code GIF LZW, filter-0
PNG) so decoder bugs cannot hide behind a matching encoder bug.
"""

from __future__ import annotations

import struct
import zlib


def make_bmp24(width, height, pixels_rgb, top_down=False):
    """pixels_rgb: list of rows (top-to-bottom), each row = list of (r,g,b)."""
    row_bytes = ((width * 3 + 3) // 4) * 4
    data_size = row_bytes * height
    offset = 14 + 40
    h = -height if top_down else height
    out = bytearray()
    out += struct.pack("<2sIHHI", b"BM", offset + data_size, 0, 0, offset)
    out += struct.pack("<IiiHHIIiiII", 40, width, h, 1, 24, 0,
                       data_size, 2835, 2835, 0, 0)
    rows = pixels_rgb if top_down else list(reversed(pixels_rgb))
    for row in rows:
        line = bytearray()
        for (r, g, b) in row:
            line += bytes((b, g, r))
        line += b"\x00" * (row_bytes - len(line))
        out += line
    return bytes(out)


def make_bmp8(width, height, palette, indices, top_down=False):
    """8-bit paletted BMP. palette: list of (r,g,b); indices: rows of ints."""
    row_bytes = ((width + 3) // 4) * 4
    data_size = row_bytes * height
    offset = 14 + 40 + len(palette) * 4
    h = -height if top_down else height
    out = bytearray()
    out += struct.pack("<2sIHHI", b"BM", offset + data_size, 0, 0, offset)
    out += struct.pack("<IiiHHIIiiII", 40, width, h, 1, 8, 0,
                       data_size, 2835, 2835, len(palette), len(palette))
    for (r, g, b) in palette:
        out += bytes((b, g, r, 0))
    rows = indices if top_down else list(reversed(indices))
    for row in rows:
        line = bytes(row) + b"\x00" * (row_bytes - width)
        out += line
    return bytes(out)


def _lzw_literals(indices, min_code_size):
    """Emit each index preceded by a CLEAR so the decoder's dictionary never
    grows and all codes stay at the minimum width. Verbose but provably
    valid, and completely independent of the decoder's compression logic."""
    clear = 1 << min_code_size
    end = clear + 1
    code_size = min_code_size + 1
    bits = []

    def emit(code):
        bits.append((code, code_size))

    for idx in indices:
        emit(clear)
        emit(idx)
    emit(end)
    out = bytearray()
    bitpos = 0
    acc = 0
    for code, size in bits:
        acc |= code << bitpos
        bitpos += size
        while bitpos >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            bitpos -= 8
    if bitpos:
        out.append(acc & 0xFF)
    return bytes(out)


def _subblocks(blob):
    out = bytearray()
    for i in range(0, len(blob), 255):
        chunk = blob[i:i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def make_gif(width, height, palette, indices, transparent_index=None,
             interlaced=False, extra_frames=0, local_palette_frame=None):
    """Build a GIF. palette: list of (r,g,b); indices: flat list of ints."""
    out = bytearray(b"GIF89a")
    n = 1 << max(1, (len(palette) - 1).bit_length())
    size_field = (n - 1).bit_length() - 1
    out += struct.pack("<HHBBB", width, height, 0x80 | size_field, 0, 0)
    for i in range(n):
        if i < len(palette):
            r, g, b = palette[i]
        else:
            r, g, b = 0, 0, 0
        out += bytes((r, g, b))
    if transparent_index is not None:
        out += b"\x21\xF9\x04\x01" + struct.pack("<HB", 0, transparent_index) + b"\x00"

    def image_block(w, h, idx, interlace):
        blk = bytearray(b"\x2C")
        blk += struct.pack("<HHHHB", 0, 0, w, h, 0x40 if interlace else 0)
        if n <= 256:
            mcs = 8 if n == 256 else max(2, (n - 1).bit_length())
        else:
            mcs = 8
        blk.append(mcs)
        blk += _subblocks(_lzw_literals(idx, mcs))
        return bytes(blk)

    if interlaced:
        # GIF stores interlaced rows in 4 passes; reorder for storage so the
        # decoder has to undo it.
        storage = []
        for start, step in ((0, 8), (4, 8), (2, 4), (1, 2)):
            for y in range(start, height, step):
                storage.extend(indices[y * width:(y + 1) * width])
        indices = storage
    out += image_block(width, height, indices, interlaced)
    for _ in range(extra_frames):
        # extra frames: tiny 1x1 image reusing the global palette
        out += image_block(1, 1, [0], False)
    out += b"\x3B"
    return bytes(out)


def make_png(width, height, color, pixels):
    """Simple filter-0 PNG (used to feed the decoder with third-party-style data)."""
    spp = {"L": 1, "RGB": 3, "RGBA": 4}[color]
    ctype = {"L": 0, "RGB": 2, "RGBA": 6}[color]
    raw = bytearray()
    stride = width * spp
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride:(y + 1) * stride]

    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(
            ">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw)))
            + chunk(b"IEND", b""))

