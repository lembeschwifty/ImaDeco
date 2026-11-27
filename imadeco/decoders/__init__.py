"""ImaDeco: format decoders.

Importing this package registers every decoder (ADR-001 side effect).
"""

from . import bmp, gif, jpeg, png  # noqa: F401

__all__ = ["bmp", "gif", "jpeg", "png"]

