"""PNG decoder. Chunks, zlib, all five scanline filters.

Supported: color types 0 (gray), 2 (RGB), 3 (palette), 4 (gray+alpha),
6 (RGBA); bit depths 1/2/4/8 (16-bit is reduced by dropping the low byte,
documented in the module); no interlacing in v0.1; tRNS transparency.
"""

from __future__ import annotations

import struct
import zlib

from ..exceptions import CorruptImageError, UnsupportedFeatureError
from ..models import DecodedImage
from ..registry import Decoder, register

COLOR_TYPE_NAMES = {0: "grayscale", 2: "RGB", 3: "palette", 4: "gray+alpha", 6: "RGBA"}
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


@register(b"\x89PNG\r\n\x1a\n", "PNG")
class PngDecoder(Decoder):
    format_name = "PNG"

    @classmethod
    def decode(cls, data: bytes) -> DecodedImage:
        if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise CorruptImageError("bad PNG signature")
        pos = 8
        ihdr = None
        idat = bytearray()
        palette = None
        trns = None
        while pos + 8 <= len(data):
            length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
            body = data[pos + 8: pos + 8 + length]
            if len(body) != length:
                raise CorruptImageError("truncated PNG chunk")
            if ctype == b"IHDR":
                ihdr = struct.unpack(">IIBBBBB", body)
            elif ctype == b"IDAT":
                idat.extend(body)
            elif ctype == b"PLTE":
                palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
            elif ctype == b"tRNS":
                trns = body
            elif ctype == b"IEND":
                break
            pos += 12 + length
        if ihdr is None or not idat:
            raise CorruptImageError("PNG missing IHDR or IDAT")

        width, height, bit_depth, color_type, compression, filter_method, interlace = ihdr
        if width <= 0 or height <= 0:
            raise CorruptImageError("bad PNG dimensions")
        if compression != 0 or filter_method != 0:
            raise CorruptImageError("bad PNG compression/filter method")
        if interlace != 0:
            raise UnsupportedFeatureError("interlaced PNG (Adam7) is out of v0.1 scope")
        if color_type not in _CHANNELS:
            raise CorruptImageError(f"bad PNG color type {color_type}")
        if color_type == 3:
            if bit_depth not in (1, 2, 4, 8):
                raise CorruptImageError(f"palette PNG with bit depth {bit_depth}")
            if palette is None:
                raise CorruptImageError("palette PNG without PLTE chunk")
        elif bit_depth not in (1, 2, 4, 8, 16):
            raise CorruptImageError(f"bad PNG bit depth {bit_depth}")

        channels = _CHANNELS[color_type]
        if bit_depth == 16:
            expand_bits = 16
        else:
            expand_bits = bit_depth
        samples_per_row = width * channels
        bytes_per_row = (samples_per_row * expand_bits + 7) // 8
        expected_raw = (bytes_per_row + 1) * height

        # Security (URL's audit): a small crafted IDAT can expand to an
        # enormous buffer (decompression bomb). Cap the decompression at
        # exactly what the header says the image needs, plus one byte to
        # detect over-long data.
        try:
            d = zlib.decompressobj()
            raw = d.decompress(bytes(idat), expected_raw + 1)
        except zlib.error as e:
            raise CorruptImageError(f"corrupt PNG image data: {e}") from e
        if len(raw) < expected_raw:
            raise CorruptImageError("PNG data shorter than expected")
        if len(raw) > expected_raw or d.unconsumed_tail:
            raise CorruptImageError("PNG data larger than the header allows "
                                    "(possible decompression bomb)")

        # Undo per-scanline filters into unpacked samples (one byte each,
        # values still 0..2^bits-1 for sub-byte depths).
        rows = cls._defilter(raw, height, bytes_per_row, channels)
        samples = cls._unpack_rows(rows, width, height, expand_bits, channels)

        pixels, color = cls._to_representation(
            samples, width, height, color_type, palette, trns, bit_depth)

        return DecodedImage(
            pixels, width, height, color,
            metadata={"format": "PNG", "bit_depth": bit_depth,
                      "color_type": f"{color_type} ({COLOR_TYPE_NAMES[color_type]})",
                      "interlaced": False},
        )

    @classmethod
    def _defilter(cls, raw, height, bytes_per_row, channels):
        """Strict full-image defilter: every row must be present and valid."""
        rows = []
        prev = bytearray(bytes_per_row)
        pos = 0
        for _y in range(height):
            if pos + 1 + bytes_per_row > len(raw):
                raise CorruptImageError("PNG ends mid-scanline")
            ftype = raw[pos]
            row = bytearray(raw[pos + 1: pos + 1 + bytes_per_row])
            pos += 1 + bytes_per_row
            row = cls._defilter_row(row, prev, ftype, channels)
            rows.append(row)
            prev = row
        return rows

    @staticmethod
    def _unpack_rows(rows, width, height, bits, channels):
        """Return per-row lists of integer samples (one entry per sample)."""
        if bits == 16:
            out = []
            for row in rows:
                samples = []
                for i in range(0, len(row), 2):
                    samples.append((row[i] << 8 | row[i + 1]) >> 8)  # drop low byte
                out.append(samples)
            return out
        if bits == 8:
            return [list(row) for row in rows]
        per_byte = 8 // bits
        mask = (1 << bits) - 1
        out = []
        for row in rows:
            samples = []
            for byte in row:
                for s in range(per_byte - 1, -1, -1):
                    samples.append((byte >> (s * bits)) & mask)
            out.append(samples[: width * channels])
        return out

    @staticmethod
    def _to_representation(samples, width, height, color_type, palette, trns, bit_depth):
        # Scale sub-byte depths to 0..255 for gray/palette uniformity.
        scale = 255 // ((1 << bit_depth) - 1) if bit_depth < 8 else 1

        if color_type == 0:
            has_trns = trns is not None and len(trns) >= 2
            key = struct.unpack(">H", trns[:2])[0] >> 8 if has_trns else None
            if has_trns:
                out = bytearray(width * height * 4)
                i = 0
                for row in samples:
                    for v in row:
                        v8 = v * scale
                        out[i:i + 4] = b"\x00\x00\x00\x00" if v == key else bytes((v8, v8, v8, 255))
                        i += 4
                return bytes(out), "RGBA"
            out = bytearray(width * height)
            i = 0
            for row in samples:
                for v in row:
                    out[i] = v * scale
                    i += 1
            return bytes(out), "L"

        if color_type == 2:
            has_trns = trns is not None and len(trns) >= 6
            key = struct.unpack(">HHH", trns[:6]) if has_trns else None
            key = tuple(c >> 8 for c in key) if key else None
            if has_trns:
                out = bytearray(width * height * 4)
                i = 0
                for row in samples:
                    for j in range(0, len(row), 3):
                        px = tuple(row[j:j + 3])
                        if px == key:
                            out[i:i + 4] = b"\x00\x00\x00\x00"
                        else:
                            out[i:i + 4] = bytes(px) + b"\xff"
                        i += 4
                return bytes(out), "RGBA"
            out = bytearray(width * height * 3)
            out[:] = b"".join(bytes(row) for row in samples)
            return bytes(out), "RGB"

        if color_type == 3:
            alpha = list(trns) if trns is not None else []
            out = bytearray(width * height * 4)
            i = 0
            for row in samples:
                for idx in row:
                    if idx >= len(palette):
                        raise CorruptImageError("PNG palette index out of range")
                    r, g, b = palette[idx]
                    a = alpha[idx] if idx < len(alpha) else 255
                    out[i:i + 4] = bytes((r, g, b, a))
                    i += 4
            return bytes(out), "RGBA"

        if color_type == 4:  # gray + alpha
            out = bytearray(width * height * 4)
            i = 0
            for row in samples:
                for j in range(0, len(row), 2):
                    g, a = row[j], row[j + 1]
                    out[i:i + 4] = bytes((g, g, g, a))
                    i += 4
            return bytes(out), "RGBA"

        # color_type == 6: RGBA
        out = bytearray(width * height * 4)
        out[:] = b"".join(bytes(row) for row in samples)
        return bytes(out), "RGBA"

    # ---- v0.2: structure walk (ADR-8) and salvage (ADR-9) ----

    @classmethod
    def walk(cls, data: bytes):
        from ..report import StructureReport
        rep = StructureReport("PNG", len(data))
        if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
            rep.error("bad PNG signature")
            return rep
        rep.structure.append({"name": "signature", "offset": 0, "size": 8})
        pos = 8
        seen_iend = False
        idat_bytes = 0
        ihdr = None
        while pos + 8 <= len(data):
            length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
            if length > 0x7FFFFFFF:
                rep.error(f"implausible chunk length {length} at offset {pos}")
                break
            body = data[pos + 8: pos + 8 + length]
            crc_stored = data[pos + 8 + length: pos + 12 + length]
            entry = {"name": ctype.decode("latin-1"), "offset": pos, "size": length}
            if len(body) != length:
                rep.error(f"chunk {ctype.decode('latin-1')} at {pos} is truncated")
                rep.structure.append(entry)
                break
            if len(crc_stored) == 4:
                crc_calc = zlib.crc32(data[pos + 4: pos + 8 + length]) & 0xFFFFFFFF
                if struct.unpack(">I", crc_stored)[0] != crc_calc:
                    rep.error(f"bad CRC in chunk {ctype.decode('latin-1')} at {pos}")
            else:
                rep.error(f"chunk {ctype.decode('latin-1')} at {pos} has no CRC")
            if ctype == b"IHDR" and length == 13:
                ihdr = struct.unpack(">IIBBBBB", body)
            elif ctype == b"IDAT":
                idat_bytes += length
            elif ctype == b"PLTE":
                if length % 3 != 0:
                    rep.error(f"PLTE length {length} is not a multiple of 3")
                entry["colors"] = length // 3
            elif ctype == b"tEXt":
                parts = body.split(b"\x00", 1)
                if len(parts) == 2:
                    rep.metadata.append(
                        (parts[0].decode("latin-1"), parts[1].decode("latin-1")))
            elif ctype == b"IEND":
                seen_iend = True
                pos += 12 + length
                rep.structure.append(entry)
                break
            rep.structure.append(entry)
            pos += 12 + length
        if ihdr is None:
            rep.error("no IHDR chunk")
        else:
            width, height, bit_depth, color_type, comp, filt, interlace = ihdr
            rep.width, rep.height = width, height
            rep.fields.update({
                "Bit depth": bit_depth,
                "Color type": f"{color_type} ({COLOR_TYPE_NAMES.get(color_type, '?')})",
                "Compression": comp,
                "Filter method": filt,
                "Interlace": "Adam7" if interlace else "none",
            })
            if width == 0 or height == 0:
                rep.error("zero image dimension")
            if comp != 0 or filt != 0:
                rep.error(f"bad compression/filter method ({comp}/{filt})")
            if interlace != 0:
                rep.warn("interlaced PNG (Adam7); decode is out of v0.1 scope")
            if color_type not in _CHANNELS:
                rep.error(f"bad color type {color_type}")
        if idat_bytes == 0:
            rep.error("no IDAT data")
        else:
            rep.fields["IDAT bytes"] = idat_bytes
        if not seen_iend:
            rep.error("no IEND chunk")
        elif pos != len(data):
            rep.warn(f"{len(data) - pos} bytes of trailing data after IEND")
        return rep

    @classmethod
    def salvage(cls, data: bytes):
        """Best-effort decode of a damaged PNG: keep every complete row.

        Returns (DecodedImage, recovered_rows, total_rows). Raises
        CorruptImageError if not even the header and one row survive.
        """
        from ..exceptions import UnrecoverableImageError
        try:
            return cls.decode(data), None, None  # healthy file
        except UnsupportedFeatureError:
            raise
        except (CorruptImageError, zlib.error):
            pass
        # Re-walk chunks; header must still be intact to attempt recovery.
        if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise UnrecoverableImageError("PNG header unrecoverable")
        pos = 8
        ihdr = None
        idat = bytearray()
        palette = None
        trns = None
        while pos + 8 <= len(data):
            try:
                length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
            except struct.error:
                break
            body = data[pos + 8: pos + 8 + length]
            if len(body) < length:
                if ctype == b"IDAT":
                    idat.extend(body)  # keep what survived
                break
            if ctype == b"IHDR":
                ihdr = struct.unpack(">IIBBBBB", body)
            elif ctype == b"IDAT":
                idat.extend(body)
            elif ctype == b"PLTE":
                palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
            elif ctype == b"tRNS":
                trns = body
            elif ctype == b"IEND":
                break
            pos += 12 + length
        if ihdr is None or not idat:
            raise UnrecoverableImageError("PNG header or image data unrecoverable")
        width, height, bit_depth, color_type, comp, filt, interlace = ihdr
        if (width <= 0 or height <= 0 or comp != 0 or filt != 0 or interlace != 0
                or color_type not in _CHANNELS):
            raise UnrecoverableImageError("PNG header unrecoverable")
        if color_type == 3:
            if bit_depth not in (1, 2, 4, 8) or palette is None:
                raise UnrecoverableImageError("palette PNG unrecoverable")
        elif bit_depth not in (1, 2, 4, 8, 16):
            raise UnrecoverableImageError("bad PNG bit depth")

        channels = _CHANNELS[color_type]
        expand_bits = 16 if bit_depth == 16 else bit_depth
        bytes_per_row = (width * channels * expand_bits + 7) // 8
        d = zlib.decompressobj()
        raw = bytearray()
        try:
            raw.extend(d.decompress(bytes(idat), (bytes_per_row + 1) * height + 1))
        except zlib.error:
            pass  # keep whatever decompressed before the error
        # Defilter row by row; stop at the first incomplete/bad row.
        rows = []
        prev = bytearray(bytes_per_row)
        rpos = 0
        for _y in range(height):
            if rpos + 1 + bytes_per_row > len(raw):
                break
            ftype = raw[rpos]
            row = bytearray(raw[rpos + 1: rpos + 1 + bytes_per_row])
            rpos += 1 + bytes_per_row
            try:
                row = cls._defilter_row(row, prev, ftype, channels)
            except CorruptImageError:
                break
            rows.append(row)
            prev = row
        if not rows:
            raise UnrecoverableImageError("no complete PNG rows recovered")
        recovered = len(rows)
        samples = cls._unpack_rows(rows, width, recovered, expand_bits, channels)
        pixels, color = cls._to_representation(
            samples, width, recovered, color_type, palette, trns, bit_depth)
        image = DecodedImage(
            pixels, width, recovered, color,
            metadata={"format": "PNG", "bit_depth": bit_depth,
                      "color_type": f"{color_type} ({COLOR_TYPE_NAMES[color_type]})",
                      "interlaced": False})
        return image, recovered, height

    @staticmethod
    def _defilter_row(row, prev, ftype, channels):
        """Defilter one scanline (shared strict/lenient helper)."""
        bytes_per_row = len(row)
        if ftype == 0:
            return row
        if ftype == 1:
            for i in range(channels, bytes_per_row):
                row[i] = (row[i] + row[i - channels]) & 0xFF
        elif ftype == 2:
            for i in range(bytes_per_row):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(bytes_per_row):
                left = row[i - channels] if i >= channels else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(bytes_per_row):
                a = row[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[i] = (row[i] + pred) & 0xFF
        else:
            raise CorruptImageError(f"bad PNG filter type {ftype}")
        return row
