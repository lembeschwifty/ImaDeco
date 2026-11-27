"""Structure reports for inspect/verify (ADR-8: walk before decode).

A StructureReport describes what a format parser saw in the file without
requiring a successful pixel decode: the container structure, key header
fields, and any anomalies. `verify` judges these reports; `inspect` prints
them. Parsers must be able to produce a report for corrupt files, so
walking never raises on bad content; it records errors instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StructureReport:
    """Result of walking an image's container structure."""

    format: str
    file_size: int
    width: int | None = None
    height: int | None = None
    fields: dict = field(default_factory=dict)   # header-level facts
    structure: list = field(default_factory=list)  # entries: {name, offset, size, ...}
    metadata: list = field(default_factory=list)  # (key, value) pairs
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def to_json(self) -> dict:
        return {
            "format": self.format,
            "file_size": self.file_size,
            "width": self.width,
            "height": self.height,
            "fields": self.fields,
            "structure": self.structure,
            "metadata": self.metadata,
            "warnings": self.warnings,
            "errors": self.errors,
            "ok": self.ok,
        }

    def to_text(self, name: str) -> str:
        lines = [f"{name}: {self.format}, {self.file_size} bytes"]
        if self.width is not None and self.height is not None:
            lines.append(f"  Dimensions: {self.width} x {self.height}")
        for key, value in self.fields.items():
            lines.append(f"  {key}: {value}")
        if self.structure:
            lines.append(f"  Structure ({len(self.structure)} items):")
            for entry in self.structure:
                extra = "".join(f", {k}={v}" for k, v in entry.items()
                                if k not in ("name", "offset", "size"))
                lines.append(f"    {entry['name']} @ {entry['offset']} "
                             f"({entry['size']} bytes{extra})")
        for key, value in self.metadata:
            lines.append(f"  {key}: {value}")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        for e in self.errors:
            lines.append(f"  error: {e}")
        lines.append(f"  Verdict: {'OK' if self.ok else 'CORRUPT'}"
                     + (" (with warnings)" if self.warnings else ""))
        return "\n".join(lines)


def walk(data: bytes) -> StructureReport:
    """Dispatch to the registered decoder's structure walk."""
    from .registry import DECODERS, detect_format
    fmt = detect_format(data)
    decoder = DECODERS[fmt]
    return decoder.walk(data)

