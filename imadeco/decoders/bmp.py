"""BMP decoder. BITMAPINFOHEADER (and COREHEADER), BI_RGB only.

Supports 1/4/8-bit paletted, 24-bit and 32-bit; top-down and bottom-up
rows; row padding. Output is RGB (paletted and 24-bit) or RGBA (32-bit).
"""

from __future__ import annotations

import struct

from ..exceptions import CorruptImageError, UnsupportedFeatureError
from ..models import DecodedImage
from ..registry import Decoder, register

@register(b"BM", "BMP")
class BmpDecoder(Decoder):
    format_name = "BMP"

    @classmethod
    def decode(cls, data: bytes) -> DecodedImage:
        if len(data) < 26:
            raise CorruptImageError("BMP file too short")
        _sig, _fsize, _res1, _res2, pixel_offset = struct.unpack("<2sIHHI", data[:14])
        if data[:2] != b"BM":
            raise CorruptImageError("bad BMP signature")

        header_size = struct.unpack("<I", data[14:18])[0]
        if header_size == 12:  # BITMAPCOREHEADER
            width, height, planes, bpp = struct.unpack("<HHHH", data[18:26])
            compression = 0
            palette_bpp = 3
        elif header_size >= 40:  # BITMAPINFOHEADER or later
            width, height, planes, bpp = struct.unpack("<iiHH", data[18:30])
            compression = struct.unpack("<I", data[30:34])[0]
            palette_bpp = 4
        else:
            raise CorruptImageError(f"unknown BMP header size {header_size}")
        if planes != 1:
            raise CorruptImageError(f"BMP planes {planes} (expected 1)")
        top_down = height < 0
        height = abs(height)
        if width <= 0 or height == 0:
            raise CorruptImageError("bad BMP dimensions")
        if compression != 0:
            raise UnsupportedFeatureError(
                f"BMP compression {compression} is out of v0.1 scope (BI_RGB only)")

        if bpp in (1, 4, 8):
            colors_used = 1 << bpp
            if header_size >= 40:
                colors_used = struct.unpack("<I", data[46:50])[0] or (1 << bpp)
            palette_start = 14 + header_size
            palette = []
            for i in range(colors_used):
                off = palette_start + i * palette_bpp
                if off + palette_bpp > len(data):
                    raise CorruptImageError("truncated BMP palette")
                b, g, r = data[off], data[off + 1], data[off + 2]
                palette.append((r, g, b))
        elif bpp not in (24, 32):
            raise UnsupportedFeatureError(f"BMP with {bpp} bits per pixel is out of v0.1 scope")

        row_bytes = ((width * bpp + 31) // 32) * 4
        needed = pixel_offset + row_bytes * height
        if len(data) < needed:
            raise CorruptImageError("truncated BMP pixel data")

        color = "RGBA" if bpp == 32 else "RGB"
        spp = 4 if bpp == 32 else 3
        out = bytearray(width * height * spp)
        for row_idx in range(height):
            src_row = height - 1 - row_idx if not top_down else row_idx
            base = pixel_offset + src_row * row_bytes
            row = data[base: base + row_bytes]
            i = row_idx * width * spp
            if bpp == 24:
                for x in range(width):
                    b, g, r = row[x * 3: x * 3 + 3]
                    out[i] = r; out[i + 1] = g; out[i + 2] = b
                    i += 3
            elif bpp == 32:
                for x in range(width):
                    b, g, r, a = row[x * 4: x * 4 + 4]
                    out[i] = r; out[i + 1] = g; out[i + 2] = b; out[i + 3] = a
                    i += 4
            else:
                per_byte = 8 // bpp
                mask = (1 << bpp) - 1
                for x in range(width):
                    byte = row[x // per_byte]
                    shift = (per_byte - 1 - (x % per_byte)) * bpp
                    idx = (byte >> shift) & mask
                    if idx >= len(palette):
                        raise CorruptImageError("BMP palette index out of range")
                    r, g, b = palette[idx]
                    out[i] = r; out[i + 1] = g; out[i + 2] = b
                    i += 3

        return DecodedImage(
            bytes(out), width, height, color,
            metadata={"format": "BMP", "bpp": bpp, "top_down": top_down,
                      "header_size": header_size, "compression": "BI_RGB"},
        )

    # ---- v0.2: structure walk (ADR-8) and salvage (ADR-9) ----

    @classmethod
    def walk(cls, data: bytes):
        from ..report import StructureReport
        rep = StructureReport("BMP", len(data))
        if len(data) < 18 or data[:2] != b"BM":
            rep.error("bad BMP signature or file too short")
            return rep
        _sig, fsize, _r1, _r2, pixel_offset = struct.unpack("<2sIHHI", data[:14])
        header_size = struct.unpack("<I", data[14:18])[0]
        rep.fields["Declared file size"] = fsize
        rep.fields["Pixel data offset"] = pixel_offset
        rep.structure.append({"name": "BITMAPFILEHEADER", "offset": 0, "size": 14})
        if fsize != len(data):
            if fsize > len(data):
                rep.error(f"file truncated: header says {fsize} bytes, file has {len(data)}")
            else:
                rep.warn(f"file has {len(data) - fsize} bytes more than the header declares")
        if header_size == 12:
            if len(data) < 26:
                rep.error("truncated BITMAPCOREHEADER")
                return rep
            width, height, planes, bpp = struct.unpack("<HHHH", data[18:26])
            compression = 0
        elif header_size >= 40:
            if len(data) < 34:
                rep.error("truncated BITMAPINFOHEADER")
                return rep
            width, height, planes, bpp = struct.unpack("<iiHH", data[18:30])
            compression = struct.unpack("<I", data[30:34])[0]
        else:
            rep.error(f"unknown DIB header size {header_size}")
            return rep
        rep.structure.append({"name": "DIB header", "offset": 14, "size": header_size})
        top_down = height < 0
        rep.width, rep.height = abs(width), abs(height)
        rep.fields.update({
            "Width": width, "Height": height, "Planes": planes,
            "Bits per pixel": bpp,
            "Compression": "BI_RGB" if compression == 0 else str(compression),
            "Top-down rows": top_down,
        })
        if planes != 1:
            rep.error(f"planes {planes} (expected 1)")
        if width == 0 or height == 0:
            rep.error("zero image dimension")
        if compression != 0:
            rep.error(f"compression {compression} is out of v0.1 scope (BI_RGB only)")
        if bpp not in (1, 4, 8, 24, 32):
            rep.error(f"{bpp} bits per pixel is not a supported BMP variant")
        row_bytes = ((abs(width) * max(bpp, 1) + 31) // 32) * 4
        needed = pixel_offset + row_bytes * abs(height)
        have = len(data) - pixel_offset
        if have < 0:
            rep.error("pixel data offset points past the end of the file")
        else:
            rep.fields["Pixel data available"] = f"{have} of {row_bytes * abs(height)} bytes"
            if have < row_bytes * abs(height):
                rep.error(f"truncated pixel data: {have} of {row_bytes * abs(height)} bytes")
        return rep

    @classmethod
    def salvage(cls, data: bytes):
        """Keep every complete pixel row the file still contains."""
        from ..exceptions import UnrecoverableImageError
        try:
            return cls.decode(data), None, None
        except UnsupportedFeatureError:
            raise
        except CorruptImageError:
            pass
        if len(data) < 34 or data[:2] != b"BM":
            raise UnrecoverableImageError("BMP header unrecoverable")
        _sig, _fsize, _r1, _r2, pixel_offset = struct.unpack("<2sIHHI", data[:14])
        header_size = struct.unpack("<I", data[14:18])[0]
        if header_size == 12:
            if len(data) < 26:
                raise UnrecoverableImageError("BMP header unrecoverable")
            width, height, planes, bpp = struct.unpack("<HHHH", data[18:26])
            compression = 0
        else:
            width, height, planes, bpp = struct.unpack("<iiHH", data[18:30])
            compression = struct.unpack("<I", data[30:34])[0]
        if compression != 0 or planes != 1 or width <= 0:
            raise UnrecoverableImageError("BMP header unrecoverable")
        top_down = height < 0
        total = abs(height)
        row_bytes = ((width * bpp + 31) // 32) * 4
        avail_rows = max(0, (len(data) - pixel_offset) // row_bytes)
        recovered = min(total, avail_rows)
        if recovered == 0:
            raise UnrecoverableImageError("no complete BMP rows recovered")
        # Rebuild a valid BMP from the surviving rows, then decode strictly.
        rows = data[pixel_offset: pixel_offset + recovered * row_bytes]
        if top_down:
            kept_rows = rows
        else:
            # Bottom-up file: the surviving top rows sit at the END of the
            # pixel data. Re-emit them top-down to keep visual row order.
            kept_rows = b"".join(
                rows[(recovered - 1 - src) * row_bytes:
                     (recovered - src) * row_bytes]
                for src in range(recovered))
        sub = bytearray()
        sub += struct.pack("<2sIHHI", b"BM", 14 + header_size + len(kept_rows), 0, 0,
                           14 + header_size)
        sub += data[14:14 + header_size]
        sub += kept_rows
        # force top-down height in the rebuilt header
        if header_size == 12:
            sub[22:26] = struct.pack("<HH", width, -recovered)
        else:
            sub[22:26] = struct.pack("<i", -recovered)
        image = cls.decode(bytes(sub))
        return image, recovered, total

