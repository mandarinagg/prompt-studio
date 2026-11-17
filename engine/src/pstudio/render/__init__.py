"""Render: decode/encode, aplicación de planes en float32 lineal y preview con caché (#31)."""

from pstudio.render.io import (
    OriginalModifiedError,
    OriginalProtectedError,
    SourceInfo,
    decode,
    encode,
    sha256_file,
)
from pstudio.render.preview import PreviewCache, Proxy, make_proxy, render_preview

__all__ = [
    "OriginalModifiedError",
    "OriginalProtectedError",
    "PreviewCache",
    "Proxy",
    "SourceInfo",
    "decode",
    "encode",
    "make_proxy",
    "render_preview",
    "sha256_file",
]
