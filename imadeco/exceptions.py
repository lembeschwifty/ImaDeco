"""Error types for ImaDeco."""


class ImageDecodeError(Exception):
    """Base class for all image decoding errors."""


class UnsupportedFormatError(ImageDecodeError):
    """The file's magic bytes do not match any supported format."""


class UnsupportedFeatureError(ImageDecodeError):
    """The format is supported but this file uses a feature out of v0.1 scope."""


class CorruptImageError(ImageDecodeError):
    """The file matches a supported format but its data is truncated or invalid."""


class UnrecoverableImageError(ImageDecodeError):
    """Salvage failed: too little of the file survives to recover any pixels."""


class SalvageUnsupportedError(ImageDecodeError):
    """Salvage is not implemented for this format yet (planned for a later
    release); the format is otherwise supported for strict decode."""

