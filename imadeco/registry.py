"""Decoder interface and format registry (ADR-001: strategy pattern)."""

from __future__ import annotations

from .exceptions import UnsupportedFormatError

DECODERS: dict[str, type] = {}
MAGIC: list[tuple[bytes, str]] = []


def register(magic: bytes, format_name: str):
    """Class decorator: register a Decoder for a format and its magic bytes."""
    def wrap(cls):
        DECODERS[format_name] = cls
        MAGIC.append((magic, format_name))
        return cls
    return wrap


class Decoder:
    """Base class for format decoders. Subclass and @register."""

    format_name: str = ""

    @classmethod
    def decode(cls, data: bytes):
        """Return a DecodedImage for the raw file bytes. Raise on bad input."""
        raise NotImplementedError


def detect_format(data: bytes) -> str:
    """Return the format name for these file bytes, or raise."""
    for magic, name in MAGIC:
        if data.startswith(magic):
            return name
    raise UnsupportedFormatError(
        "Unsupported file type: magic bytes do not match JPEG, PNG, BMP or GIF "
        f"(got {data[:8].hex()})")

