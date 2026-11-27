__version__ = "0.2.0"

from . import decoders as _decoders  # registration side effect
from .exceptions import (CorruptImageError, ImageDecodeError,
                         UnsupportedFeatureError, UnsupportedFormatError)
from .models import DecodedImage
from .registry import DECODERS, detect_format

__all__ = ["DecodedImage", "decode_file", "detect_format", "DECODERS",
           "ImageDecodeError", "UnsupportedFormatError",
           "UnsupportedFeatureError", "CorruptImageError"]


def decode_file(path) -> DecodedImage:
    """Convenience API: read and decode an image file (by magic bytes)."""
    from pathlib import Path
    data = Path(path).read_bytes()
    return DECODERS[detect_format(data)].decode(data)

