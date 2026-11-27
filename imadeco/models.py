"""Internal decoded-image representation (ADR-006)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DecodedImage:
    """A fully decoded image in a uniform representation.

    pixels: interleaved sample bytes. For color 'L' one byte per pixel,
    'RGB' three bytes per pixel, 'RGBA' four. Top-down row order.
    """

    pixels: bytes
    width: int
    height: int
    color: str  # 'L' | 'RGB' | 'RGBA'
    metadata: dict = field(default_factory=dict)

    @property
    def samples_per_pixel(self) -> int:
        return {"L": 1, "RGB": 3, "RGBA": 4}[self.color]

    @property
    def row_bytes(self) -> int:
        return self.width * self.samples_per_pixel

    def pixel(self, x: int, y: int) -> tuple:
        spp = self.samples_per_pixel
        i = (y * self.width + x) * spp
        return tuple(self.pixels[i:i + spp])

    def summary(self) -> dict:
        m = dict(self.metadata)
        m.update({"width": self.width, "height": self.height, "color": self.color})
        return m

