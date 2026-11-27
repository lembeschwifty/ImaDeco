"""JPEG decoder (baseline, SOF0). Pure stdlib.

Huffman, IDCT, YCbCr conversion, restart markers and chroma subsampling are
implemented from the JPEG spec. This decoder was first built and byte-verified
against a reference photograph; it consumes the entropy stream exactly to
the file trailer.
"""

from __future__ import annotations

import math

from ..exceptions import CorruptImageError, UnsupportedFeatureError
from ..models import DecodedImage
from ..registry import Decoder, register

ZIGZAG = [
     0,  1,  8, 16,  9,  2,  3, 10,
    17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
]

COS = [[math.cos((2 * x + 1) * u * math.pi / 16) for u in range(8)] for x in range(8)]


class _BitReader:
    def __init__(self, data, start):
        self.d = data
        self.i = start
        self.b = 0
        self.n = 0

    def bit(self) -> int:
        if self.n == 0:
            if self.i >= len(self.d):
                raise CorruptImageError("JPEG data ends mid-stream")
            byte = self.d[self.i]
            self.i += 1
            if byte == 0xFF:
                nxt = self.d[self.i] if self.i < len(self.d) else 0
                if nxt == 0x00:
                    self.i += 1
                elif 0xD0 <= nxt <= 0xD7:
                    raise CorruptImageError("JPEG restart marker inside a block")
                elif nxt in (0xD9, 0xDA) or 0xC0 <= nxt <= 0xFE:
                    raise CorruptImageError("JPEG marker inside entropy data")
                else:
                    raise CorruptImageError("bad JPEG stuffing")
            self.b = byte
            self.n = 8
        self.n -= 1
        return (self.b >> self.n) & 1

    def restart_align(self):
        self.n = 0
        while self.i < len(self.d) and self.d[self.i] != 0xFF:
            self.i += 1
        if self.i + 1 >= len(self.d) or not 0xD0 <= self.d[self.i + 1] <= 0xD7:
            raise CorruptImageError("expected JPEG restart marker")
        self.i += 2


def _build_huffman(seg):
    out = {}
    i = 0
    while i < len(seg):
        tc_th = seg[i]
        i += 1
        counts = list(seg[i:i + 16])
        i += 16
        total = sum(counts)
        symbols = list(seg[i:i + total])
        i += total
        table = {}
        code = 0
        k = 0
        for length in range(16):
            for _ in range(counts[length]):
                table[(length + 1, code)] = symbols[k]
                k += 1
                code += 1
            code <<= 1
        out[tc_th] = table
    return out


def _idct8(blk):
    out = [0.0] * 64
    for x in range(8):
        cx = COS[x]
        for y in range(8):
            cy = COS[y]
            s = 0.0
            for u in range(8):
                cu = 0.7071067811865476 if u == 0 else 1.0
                base = u * 8
                bx = cx[u]
                for v in range(8):
                    s += (blk[base + v] * cu
                          * (0.7071067811865476 if v == 0 else 1.0)
                          * bx * cy[v])
            out[y * 8 + x] = s * 0.25
    return out


@register(b"\xff\xd8\xff", "JPEG")
class JpegDecoder(Decoder):
    format_name = "JPEG"

    @classmethod
    def decode(cls, data: bytes) -> DecodedImage:
        if len(data) < 4:
            raise CorruptImageError("JPEG file too short")
        pos = 2
        qt: dict[int, list[int]] = {}
        huff_dc: dict[int, dict] = {}
        huff_ac: dict[int, dict] = {}
        frame = None
        restart_interval = 0
        scan_pos = None
        scomp = None

        while pos < len(data) - 1:
            if data[pos] != 0xFF:
                pos += 1
                continue
            m = data[pos + 1]
            if m in (0xD8, 0xD9, 0x01) or 0xD0 <= m <= 0xD7:
                pos += 2
                continue
            if m == 0xFF:
                pos += 1
                continue
            if pos + 4 > len(data):
                raise CorruptImageError("truncated JPEG marker")
            seg_len = (data[pos + 2] << 8) | data[pos + 3]
            if seg_len < 2 or pos + 2 + seg_len > len(data):
                raise CorruptImageError("truncated JPEG segment")
            seg = data[pos + 4: pos + 2 + seg_len]
            if m == 0xC4:
                for k, v in _build_huffman(bytes(seg)).items():
                    (huff_dc if k >> 4 == 0 else huff_ac)[k & 15] = v
            elif m == 0xDB:
                qt[seg[0]] = list(seg[1:65]) if len(seg) >= 65 else None
                if qt[seg[0]] is None:
                    raise CorruptImageError("bad JPEG quantization table")
            elif m in (0xC0, 0xC1):
                frame = cls._parse_sof(seg)
            elif m == 0xC2:
                raise UnsupportedFeatureError("progressive JPEG (SOF2) is out of v0.1 scope")
            elif m in (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                raise UnsupportedFeatureError("JPEG arithmetic/lossless/hierarchical coding is unsupported")
            elif m == 0xDD:
                restart_interval = (seg[0] << 8) | seg[1]
            elif m == 0xDA:
                ns = seg[0]
                scomp = [(seg[1 + 2 * s], seg[2 + 2 * s] >> 4, seg[2 + 2 * s] & 15)
                         for s in range(ns)]
                scan_pos = pos + 2 + seg_len
                break
            pos += 2 + seg_len

        if frame is None or scan_pos is None:
            raise CorruptImageError("JPEG has no frame or scan data")
        height, width, comps, precision = frame
        if precision != 8:
            raise UnsupportedFeatureError(f"JPEG precision {precision} (only 8-bit supported)")
        if len(comps) == 1:
            color = "L"
        elif len(comps) == 3:
            color = "RGB"
        else:
            raise UnsupportedFeatureError("JPEG with 4 components (CMYK) is unsupported")

        planes = cls._decode_scan(data, scan_pos, width, height, comps,
                                  scomp, qt, huff_dc, huff_ac, restart_interval)
        pixels = cls._to_pixels(width, height, color, planes)
        return DecodedImage(
            pixels, width, height, color,
            metadata={"format": "JPEG", "precision": precision,
                      "components": [(c[0], c[1], c[2]) for c in comps],
                      "restart_interval": restart_interval},
        )

    @staticmethod
    def _parse_sof(seg):
        height = (seg[1] << 8) | seg[2]
        width = (seg[3] << 8) | seg[4]
        nc = seg[5]
        if height <= 0 or width <= 0 or nc not in (1, 3):
            raise UnsupportedFeatureError("JPEG frame with unusual geometry/components")
        comps = []
        for c in range(nc):
            comps.append((seg[6 + 3 * c], seg[7 + 3 * c] >> 4,
                          seg[7 + 3 * c] & 15, seg[8 + 3 * c]))
        return height, width, comps, seg[0]

    @staticmethod
    def _decode_scan(data, scan_pos, width, height, comps, scomp,
                     qt, huff_dc, huff_ac, restart_interval):
        hmax = max(c[1] for c in comps)
        vmax = max(c[2] for c in comps)
        mcux = (width + 8 * hmax - 1) // (8 * hmax)
        mcuy = (height + 8 * vmax - 1) // (8 * vmax)
        planes = []
        for (_cid, hs, vs, _tq) in comps:
            planes.append([[0.0] * (mcux * hs * 8) for _ in range(mcuy * vs * 8)])

        br = _BitReader(data, scan_pos)
        dc_pred = [0] * len(comps)
        mcu_count = 0

        def recv(table):
            code = 0
            length = 0
            while True:
                code = (code << 1) | br.bit()
                length += 1
                sym = table.get((length, code))
                if sym is not None:
                    return sym
                if length > 16:
                    raise CorruptImageError("bad JPEG Huffman code")

        def read_bits(n):
            v = 0
            for _ in range(n):
                v = (v << 1) | br.bit()
            return v

        def extend(v, t):
            return v - (1 << t) + 1 if v < (1 << (t - 1)) else v

        for my in range(mcuy):
            for mx in range(mcux):
                if restart_interval and mcu_count and mcu_count % restart_interval == 0:
                    br.restart_align()
                    dc_pred = [0] * len(comps)
                for ci, (_cid, hs, vs, tq) in enumerate(comps):
                    _cs, tdc, tac = scomp[ci]
                    qtab = qt.get(tq)
                    if qtab is None:
                        raise CorruptImageError("missing JPEG quantization table")
                    for by in range(vs):
                        for bx in range(hs):
                            blk = [0] * 64
                            t = recv(huff_dc[tdc])
                            if t:
                                dc_pred[ci] += extend(read_bits(t), t)
                            blk[0] = dc_pred[ci]
                            k = 1
                            while k < 64:
                                rs = recv(huff_ac[tac])
                                if rs == 0:
                                    break
                                r = rs >> 4
                                if r == 15:
                                    k += 16
                                    continue
                                t = rs & 15
                                k += r
                                if k > 63:
                                    break
                                v = read_bits(t)
                                blk[k] = extend(v, t)
                                k += 1
                            flat = [0] * 64
                            for i in range(64):
                                zi = ZIGZAG[i]
                                flat[zi] = blk[i] * qtab[zi]
                            pix = _idct8(flat)
                            ox = (mx * hs + bx) * 8
                            oy = (my * vs + by) * 8
                            pl = planes[ci]
                            for yy in range(8):
                                row = pl[oy + yy]
                                for xx in range(8):
                                    row[ox + xx] = pix[yy * 8 + xx] + 128
                mcu_count += 1
        return planes

    @staticmethod
    def _to_pixels(width, height, color, planes):
        if color == "L":
            yp = planes[0]
            out = bytearray(width * height)
            i = 0
            for y in range(height):
                row = yp[y]
                for x in range(width):
                    out[i] = max(0, min(255, int(row[x])))
                    i += 1
            return bytes(out)

        yp, cbp, crp = planes[0], planes[1], planes[2]
        yh = len(yp)
        yw = len(yp[0])
        ch = len(cbp)
        cw = len(cbp[0])
        out = bytearray(width * height * 3)
        i = 0
        for y in range(height):
            yrow = yp[y]
            cbrow = cbp[y * ch // yh]
            crrow = crp[y * ch // yh]
            for x in range(width):
                lum = yrow[x]
                cb = cbrow[x * cw // yw] - 128
                cr = crrow[x * cw // yw] - 128
                out[i] = max(0, min(255, int(lum + 1.402 * cr)))
                out[i + 1] = max(0, min(255, int(lum - 0.344136 * cb - 0.714136 * cr)))
                out[i + 2] = max(0, min(255, int(lum + 1.772 * cb)))
                i += 3
        return bytes(out)

    # ---- v0.2: structure walk (ADR-8). Salvage (ADR-9) is deferred: the
    # entropy stream has no row-aligned resync point short of a restart
    # marker, so partial JPEG recovery needs restart-interval-aware scan
    # resumption planned for a later release. ----

    _MARKER_NAMES = {
        0xC0: "SOF0 (baseline DCT)", 0xC1: "SOF1 (extended sequential)",
        0xC2: "SOF2 (progressive)", 0xC4: "DHT (Huffman table)",
        0xDB: "DQT (quantization table)", 0xDD: "DRI (restart interval)",
        0xDA: "SOS (scan)", 0xD9: "EOI (end of image)", 0xD8: "SOI",
        0xE0: "APP0 (JFIF)", 0xE1: "APP1 (EXIF)", 0xEE: "APP14 (Adobe)",
        0xFE: "COM (comment)",
    }

    @classmethod
    def walk(cls, data: bytes):
        from ..report import StructureReport
        rep = StructureReport("JPEG", len(data))
        if len(data) < 4 or data[:2] != b"\xff\xd8":
            rep.error("bad JPEG signature or file too short")
            return rep
        rep.structure.append({"name": "SOI", "offset": 0, "size": 2})
        pos = 2
        frame = None
        restart_interval = 0
        seen_sos = False
        while pos < len(data) - 1:
            if data[pos] != 0xFF:
                pos += 1
                continue
            m = data[pos + 1]
            if m in (0x01,) or 0xD0 <= m <= 0xD7:
                pos += 2
                continue
            if m == 0xFF:
                pos += 1
                continue
            if m == 0xD9:
                rep.structure.append({"name": "EOI", "offset": pos, "size": 2})
                pos += 2
                break
            if pos + 4 > len(data):
                rep.error(f"truncated marker at offset {pos}")
                return rep
            seg_len = (data[pos + 2] << 8) | data[pos + 3]
            name = cls._MARKER_NAMES.get(m, f"marker 0xFF{m:02X}")
            if seg_len < 2 or pos + 2 + seg_len > len(data):
                rep.error(f"segment {name} at {pos} is truncated")
                return rep
            seg = data[pos + 4: pos + 2 + seg_len]
            entry = {"name": name, "offset": pos, "size": seg_len + 2}
            if m in (0xC0, 0xC1):
                frame = cls._parse_sof(seg)
                entry["size_px"] = f"{(seg[3] << 8) | seg[4]}x{(seg[1] << 8) | seg[2]}"
            elif m == 0xC2:
                rep.error("progressive JPEG (SOF2) is out of v0.1 scope")
            elif m in (0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                rep.error("arithmetic/lossless/hierarchical JPEG is unsupported")
            elif m == 0xDD:
                restart_interval = (seg[0] << 8) | seg[1]
            elif m == 0xFE:
                rep.metadata.append(("Comment", seg.decode("latin-1", "replace")))
            elif m == 0xDA:
                seen_sos = True
                rep.structure.append(entry)
                pos += 2 + seg_len
                break
            rep.structure.append(entry)
            pos += 2 + seg_len
        if frame is not None:
            height, width, comps, precision = frame
            rep.width, rep.height = width, height
            rep.fields["Precision"] = f"{precision} bits"
            rep.fields["Sampling"] = [(c[0], c[1], c[2]) for c in comps]
            if len(comps) == 1:
                rep.fields["Color"] = "grayscale"
            elif len(comps) == 3:
                rep.fields["Color"] = "YCbCr"
            else:
                rep.warn("unusual component count (CMYK?)")
        else:
            rep.error("no SOF frame found")
        if restart_interval:
            rep.fields["Restart interval"] = restart_interval
        if seen_sos:
            if data[-2:] == b"\xff\xd9":
                rep.structure.append({"name": "EOI", "offset": len(data) - 2,
                                     "size": 2})
            else:
                rep.error("missing EOI at end of file (truncated scan?)")
        else:
            rep.error("no scan (SOS) found")
        return rep

    @classmethod
    def salvage(cls, data: bytes):
        from ..exceptions import SalvageUnsupportedError
        raise SalvageUnsupportedError(
            "JPEG salvage is planned for a later release: the entropy stream "
            "has no row-aligned recovery point, so partial recovery needs "
            "restart-interval-aware scan resumption")

