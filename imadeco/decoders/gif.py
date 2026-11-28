"""GIF decoder. LZW decompression, palettes, first frame, interlace.

v0.1 decodes the first frame and counts the rest; transparency from the
graphic control extension is honored (output RGBA when present, else RGB).
"""

from __future__ import annotations

import struct

from ..exceptions import CorruptImageError
from ..models import DecodedImage
from ..registry import Decoder, register


@register(b"GIF8", "GIF")
class GifDecoder(Decoder):
    format_name = "GIF"

    @classmethod
    def decode(cls, data: bytes) -> DecodedImage:
        if len(data) < 13:
            raise CorruptImageError("GIF file too short")
        version = data[:6]
        if version not in (b"GIF87a", b"GIF89a"):
            raise CorruptImageError("bad GIF signature")
        width, height, flags, _bg, _aspect = struct.unpack("<HHBBB", data[6:13])
        pos = 13
        global_palette = None
        if flags & 0x80:
            n = 2 << (flags & 0x07)
            if pos + n * 3 > len(data):
                raise CorruptImageError("truncated GIF global palette")
            global_palette = [(data[pos + i * 3], data[pos + i * 3 + 1], data[pos + i * 3 + 2])
                               for i in range(n)]
            pos += n * 3

        transparent_index = None
        frame = None
        frame_count = 0
        while pos < len(data):
            b = data[pos]
            if b == 0x3B:  # trailer
                break
            if b == 0x21:  # extension
                pos += 2
                if data[pos - 1] == 0xF9 and pos + 5 <= len(data):  # graphic control
                    packed = data[pos + 1]
                    _delay, tidx = struct.unpack("<HB", data[pos + 2: pos + 5])
                    if packed & 0x01:
                        transparent_index = tidx
                    pos += 5  # size, packed, delay(2), transparent index
                pos = cls._skip_subblocks(data, pos)
                continue
            if b == 0x2C:  # image descriptor
                frame_count += 1
                left, top, fw, fh, iflags = struct.unpack("<HHHHB", data[pos + 1: pos + 10])
                pos += 10
                local_palette = None
                if iflags & 0x80:
                    n = 2 << (iflags & 0x07)
                    if pos + n * 3 > len(data):
                        raise CorruptImageError("truncated GIF local palette")
                    local_palette = [(data[pos + i * 3], data[pos + i * 3 + 1], data[pos + i * 3 + 2])
                                     for i in range(n)]
                    pos += n * 3
                interlaced = bool(iflags & 0x40)
                palette = local_palette or global_palette
                if palette is None:
                    raise CorruptImageError("GIF frame without any palette")
                indices, pos = cls._read_lzw(data, pos, fw * fh)
                if frame is None:
                    frame = (fw, fh, indices, palette, interlaced, transparent_index)
                continue
            raise CorruptImageError(f"unknown GIF block 0x{b:02X} at {pos}")

        if frame is None:
            raise CorruptImageError("GIF contains no image frame")
        fw, fh, indices, palette, interlaced, tidx = frame
        rows = cls._deinterlace(indices, fw, fh) if interlaced else [
            indices[y * fw:(y + 1) * fw] for y in range(fh)]

        has_alpha = tidx is not None
        spp = 4 if has_alpha else 3
        out = bytearray(fw * fh * spp)
        i = 0
        for row in rows:
            for idx in row:
                if idx >= len(palette):
                    raise CorruptImageError("GIF palette index out of range")
                r, g, b = palette[idx]
                if has_alpha:
                    a = 0 if idx == tidx else 255
                    out[i:i + 4] = bytes((r, g, b, a))
                    i += 4
                else:
                    out[i:i + 3] = bytes((r, g, b))
                    i += 3

        return DecodedImage(
            bytes(out), fw, fh, "RGBA" if has_alpha else "RGB",
            metadata={"format": "GIF", "version": version.decode(),
                      "frame_count": frame_count, "interlaced": interlaced,
                      "transparent_index": tidx,
                      "canvas_size": f"{width}x{height}"},
        )

    @staticmethod
    def _skip_subblocks(data, pos):
        while pos < len(data):
            size = data[pos]
            pos += 1
            if size == 0:
                return pos
            pos += size
        raise CorruptImageError("unterminated GIF extension")

    # ---- LZW: one decoder core, two policies (ADR: dedup of v0.2 pilot
    # finding). Strict mode raises CorruptImageError on any anomaly and
    # requires the full pixel count; lenient mode (salvage) returns
    # whatever decoded before the damage. ----

    @staticmethod
    def _lzw_decode(data, pos, need, strict):
        """Core LZW decompression. Returns (indices, new_pos)."""
        def fail(msg):
            if strict:
                raise CorruptImageError(msg)
            raise _LenientStop()

        if pos >= len(data):
            fail("GIF LZW data missing")
        min_code_size = data[pos]
        if not 2 <= min_code_size <= 8:
            fail(f"bad GIF LZW min code size {min_code_size}")
        pos += 1
        stream = bytearray()
        while pos < len(data):
            size = data[pos]
            pos += 1
            if size == 0:
                break
            stream.extend(data[pos:pos + size])
            pos += size
        clear_code = 1 << min_code_size
        end_code = clear_code + 1
        code_size = min_code_size + 1
        dict_size = end_code + 1
        table = None
        out = []
        bitpos = 0
        total_bits = len(stream) * 8
        prev = None
        while bitpos + code_size <= total_bits:
            byte_i = bitpos >> 3
            chunk = int.from_bytes(stream[byte_i:byte_i + 3].ljust(3, b"\x00"), "little")
            code = (chunk >> (bitpos & 7)) & ((1 << code_size) - 1)
            bitpos += code_size
            if code == clear_code:
                table = [(i,) for i in range(clear_code)]
                table += [(), ()]  # clear + end placeholders
                code_size = min_code_size + 1
                dict_size = end_code + 1
                prev = None
                continue
            if code == end_code:
                break
            if table is None:
                fail("GIF LZW stream did not start with clear code")
            if code < len(table) and table[code]:
                entry = table[code]
            elif code == dict_size and prev is not None:
                entry = prev + (prev[0],)
            else:
                fail("corrupt GIF LZW code")
            out.extend(entry)
            if prev is not None:
                table.append(prev + (entry[0],))
                dict_size += 1
                if code_size < 12 and dict_size == (1 << code_size):
                    code_size += 1
            prev = entry
            if len(out) >= need:
                break
        if len(out) < need and strict:
            raise CorruptImageError("GIF LZW data produced too few pixels")
        return out[:need], pos

    @classmethod
    def _read_lzw(cls, data, pos, need):
        """Strict LZW: full pixel count or raise."""
        return cls._lzw_decode(data, pos, need, strict=True)

    @classmethod
    def _lzw_partial(cls, data, pos, need):
        """Lenient LZW (salvage): decode until the stream ends, return what
        we got."""
        try:
            indices, _pos = cls._lzw_decode(data, pos, need, strict=False)
            return indices
        except _LenientStop:
            return []

    @staticmethod
    def _deinterlace(indices, width, height):
        rows = [None] * height
        src = 0
        for start, step in ((0, 8), (4, 8), (2, 4), (1, 2)):
            for y in range(start, height, step):
                rows[y] = indices[src * width:(src + 1) * width]
                src += 1
        return rows

    # ---- v0.2: structure walk (ADR-8) and salvage (ADR-9) ----

    @classmethod
    def walk(cls, data: bytes):
        from ..report import StructureReport
        rep = StructureReport("GIF", len(data))
        if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
            rep.error("bad GIF signature or file too short")
            return rep
        rep.structure.append({"name": "header", "offset": 0, "size": 13})
        version = data[:6].decode("ascii")
        width, height, flags, _bg, _aspect = struct.unpack("<HHBBB", data[6:13])
        rep.width, rep.height = width, height
        rep.fields["Version"] = version
        rep.fields["Canvas size"] = f"{width}x{height}"
        rep.fields["Global palette"] = bool(flags & 0x80)
        pos = 13
        if flags & 0x80:
            n = 2 << (flags & 0x07)
            if pos + n * 3 > len(data):
                rep.error("truncated global palette")
                return rep
            rep.structure.append({"name": "global palette", "offset": pos,
                                 "size": n * 3, "colors": n})
            pos += n * 3
        frames = 0
        extensions = 0
        seen_trailer = False
        while pos < len(data):
            b = data[pos]
            if b == 0x3B:
                seen_trailer = True
                rep.structure.append({"name": "trailer", "offset": pos, "size": 1})
                pos += 1
                break
            if b == 0x21:
                start = pos
                label = data[pos + 1] if pos + 1 < len(data) else -1
                try:
                    pos = cls._skip_subblocks(data, pos + 2)
                except CorruptImageError as e:
                    rep.error(str(e))
                    return rep
                extensions += 1
                rep.structure.append({"name": f"extension 0x{label:02X}",
                                     "offset": start, "size": pos - start})
                continue
            if b == 0x2C:
                start = pos
                if pos + 10 > len(data):
                    rep.error("truncated image descriptor")
                    return rep
                _l, _t, fw, fh, iflags = struct.unpack("<HHHHB", data[pos + 1:pos + 10])
                pos += 10
                if iflags & 0x80:
                    n = 2 << (iflags & 0x07)
                    if pos + n * 3 > len(data):
                        rep.error("truncated local palette")
                        return rep
                    pos += n * 3
                if pos >= len(data):
                    rep.error("truncated image data")
                    return rep
                try:
                    pos = cls._skip_subblocks(data, pos + 1)  # LZW min code byte + subblocks
                except CorruptImageError as e:
                    rep.error(str(e))
                    return rep
                frames += 1
                rep.structure.append({"name": "image descriptor", "offset": start,
                                     "size": pos - start,
                                     "frame_size": f"{fw}x{fh}",
                                     "interlaced": bool(iflags & 0x40)})
                continue
            rep.error(f"unknown block 0x{b:02X} at offset {pos}")
            return rep
        rep.fields["Frames"] = frames
        rep.fields["Extensions"] = extensions
        if frames == 0:
            rep.error("no image frames")
        if not seen_trailer:
            rep.error("missing trailer (file truncated)")
        elif pos != len(data):
            rep.warn(f"{len(data) - pos} bytes of trailing data after trailer")
        return rep

    @classmethod
    def salvage(cls, data: bytes):
        """Recover the first frame's complete rows from a damaged GIF.

        Interlaced frames and files with an unreadable header are refused.
        """
        from ..exceptions import SalvageUnsupportedError, UnrecoverableImageError
        try:
            return cls.decode(data), None, None
        except CorruptImageError:
            pass
        if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
            raise UnrecoverableImageError("GIF header unrecoverable")
        width, height, flags, _bg, _aspect = struct.unpack("<HHBBB", data[6:13])
        pos = 13
        global_palette = None
        if flags & 0x80:
            n = 2 << (flags & 0x07)
            if pos + n * 3 > len(data):
                raise UnrecoverableImageError("GIF global palette unrecoverable")
            global_palette = [(data[pos + i * 3], data[pos + i * 3 + 1],
                               data[pos + i * 3 + 2]) for i in range(n)]
            pos += n * 3
        transparent_index = None
        while pos < len(data):
            b = data[pos]
            if b == 0x3B:
                raise UnrecoverableImageError("GIF contains no image frame to salvage")
            if b == 0x21:
                pos += 2
                if pos - 1 < len(data) and data[pos - 1] == 0xF9 and pos + 4 <= len(data):
                    packed = data[pos]
                    if packed & 0x01:
                        transparent_index = data[pos + 3]
                    pos += 4
                try:
                    pos = cls._skip_subblocks(data, pos)
                except CorruptImageError:
                    break
                continue
            if b == 0x2C:
                if pos + 10 > len(data):
                    raise UnrecoverableImageError("GIF image descriptor unrecoverable")
                _l, _t, fw, fh, iflags = struct.unpack("<HHHHB", data[pos + 1:pos + 10])
                if iflags & 0x40:
                    raise SalvageUnsupportedError(
                        "salvage of interlaced GIF frames is planned for a later release")
                pos += 10
                palette = global_palette
                if iflags & 0x80:
                    n = 2 << (iflags & 0x07)
                    if pos + n * 3 > len(data):
                        raise UnrecoverableImageError("GIF local palette unrecoverable")
                    palette = [(data[pos + i * 3], data[pos + i * 3 + 1],
                                data[pos + i * 3 + 2]) for i in range(n)]
                    pos += n * 3
                if palette is None:
                    raise UnrecoverableImageError("GIF frame has no palette")
                indices = cls._lzw_partial(data, pos, fw * fh)
                recovered = len(indices) // fw
                if recovered == 0:
                    raise UnrecoverableImageError("no complete GIF rows recovered")
                has_alpha = transparent_index is not None
                spp = 4 if has_alpha else 3
                out = bytearray(fw * recovered * spp)
                i = 0
                for idx in indices[:fw * recovered]:
                    if idx >= len(palette):
                        raise UnrecoverableImageError("GIF palette index out of range")
                    r, g, b = palette[idx]
                    if has_alpha:
                        out[i:i + 4] = bytes((r, g, b,
                                              0 if idx == transparent_index else 255))
                        i += 4
                    else:
                        out[i:i + 3] = bytes((r, g, b))
                        i += 3
                image = DecodedImage(
                    bytes(out), fw, recovered, "RGBA" if has_alpha else "RGB",
                    metadata={"format": "GIF", "version": data[:6].decode(),
                              "frame_count": 1, "interlaced": False,
                              "transparent_index": transparent_index,
                              "canvas_size": f"{width}x{height}"})
                return image, recovered, fh
            raise UnrecoverableImageError(f"unknown GIF block 0x{b:02X} at {pos}")
        raise UnrecoverableImageError("GIF contains no image frame to salvage")


class _LenientStop(Exception):
    """Internal: a lenient (salvage) LZW hit damage and keeps what it has."""
