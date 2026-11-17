"""Render: decode/encode y (desde #11) aplicación de planes sobre imágenes en float32 lineal."""

from pstudio.render.io import (
    OriginalModifiedError,
    OriginalProtectedError,
    SourceInfo,
    decode,
    encode,
    sha256_file,
)

__all__ = [
    "OriginalModifiedError",
    "OriginalProtectedError",
    "SourceInfo",
    "decode",
    "encode",
    "sha256_file",
]
