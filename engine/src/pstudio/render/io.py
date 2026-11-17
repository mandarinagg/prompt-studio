"""Entrada/salida de imágenes: decode → float32 lineal → encode (docs/MEDIA_PIPELINE.md).

Espacio de trabajo: **scRGB** de libvips, es decir RGB lineal con primarios sRGB/Rec.709 y
blanco D65, en float32. Los valores fuera de 0…1 se conservan, así que un rojo de Display P3
sobrevive como (1.27, −0.04, −0.02) y vuelve exacto a P3. El alpha, si existe, viaja como
cuarta banda en 0…1.

Conversión de color:
- sin perfil, o con un perfil sRGB: fórmulas de libvips (ida y vuelta exacta en 8 bits);
- cualquier otro perfil (Display P3, Adobe RGB, CMYK…): LittleCMS vía `icc_import`.

Regla no negociable 2: **nunca escribir sobre originales.** `encode` se niega si el destino es
el original o alguno de los protegidos, escribe primero un temporal y lo renombra al final, y
verifica que el hash del original siga igual después de exportar.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pyvips

Format = Literal["jpeg", "png", "webp", "tiff"]
ColorSpace = Literal["sRGB", "Display P3"]
Metadata = Literal["keep", "strip"]

SUFFIXES: dict[str, Format] = {
    ".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp",
    ".tif": "tiff", ".tiff": "tiff",
}  # fmt: skip
_LOADERS = {"jpegload": "jpeg", "pngload": "png", "webpload": "webp", "tiffload": "tiff"}


class OriginalProtectedError(Exception):
    """Se intentó escribir sobre un original."""


class OriginalModifiedError(Exception):
    """El hash del original cambió durante la operación (no debería pasar nunca)."""


@dataclass(frozen=True)
class SourceInfo:
    path: Path
    sha256: str
    format: Format
    width: int  # ya orientado según EXIF
    height: int
    has_alpha: bool
    bit_depth: int
    profile: str  # "none", "sRGB" o la descripción del perfil embebido
    orientation: int  # valor EXIF original (1 = normal)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def icc_description(profile: bytes) -> str:
    """Descripción ('desc') de un perfil ICC v2 o v4; "" si no se puede leer."""
    try:
        (count,) = struct.unpack_from(">I", profile, 128)
        for i in range(count):
            sig, off, size = struct.unpack_from(">4sII", profile, 132 + 12 * i)
            if sig != b"desc":
                continue
            kind = profile[off : off + 4]
            if kind == b"desc":  # v2: largo ASCII + texto
                (n,) = struct.unpack_from(">I", profile, off + 8)
                return profile[off + 12 : off + 12 + n].rstrip(b"\0").decode("latin-1")
            if kind == b"mluc":  # v4: 'mluc', reservado, n.º de registros, tamaño de registro y
                # registros (idioma, país, largo, offset) en UTF-16BE; se toma el primero
                length, n_off = struct.unpack_from(">II", profile, off + 20)
                return profile[off + n_off : off + n_off + length].decode("utf-16-be")
            return ""
    except struct.error, UnicodeDecodeError:
        return ""
    return ""


def _is_srgb(description: str) -> bool:
    return "srgb" in description.lower().replace(" ", "")


def decode(path: str | Path) -> tuple[pyvips.Image, SourceInfo]:
    """Abre un original (solo lectura) y lo lleva a scRGB float32 lineal, ya orientado."""
    path = Path(path).resolve()
    if path.suffix.lower() not in SUFFIXES:
        raise ValueError(f"formato no soportado: {path.suffix or '(sin extensión)'}")
    digest = sha256_file(path)
    # revalidate: libvips cachea por nombre de archivo; si el original cambió en disco,
    # sin esto devolvería los píxeles viejos con el hash nuevo.
    img = pyvips.Image.new_from_file(str(path), revalidate=True)
    loader = img.get("vips-loader") if img.get_typeof("vips-loader") else ""
    fmt = _LOADERS.get(loader.removesuffix("_source").removesuffix("_buffer"))
    if fmt is None:
        raise ValueError(f"{path.name}: el contenido no es JPEG/PNG/WebP/TIFF ({loader})")
    orientation = img.get("orientation") if img.get_typeof("orientation") else 1
    img = img.autorot()

    bit_depth = {"uchar": 8, "char": 8, "ushort": 16, "short": 16}.get(img.format, 32)
    icc = img.get("icc-profile-data") if img.get_typeof("icc-profile-data") else b""
    description = icc_description(icc) if icc else ""
    cmyk = img.interpretation == "cmyk"

    if (icc and not _is_srgb(description)) or cmyk:
        # icc_import conserva la banda alpha; sin perfil, un CMYK usa el perfil CMYK genérico.
        lab = img.icc_import(embedded=bool(icc), input_profile="cmyk", intent="relative")
        linear = lab.colourspace("scrgb")
        profile = description or "CMYK genérico"
    else:
        linear = img.colourspace("scrgb")
        profile = "sRGB" if icc else "none"

    info = SourceInfo(
        path=path,
        sha256=digest,
        format=fmt,
        width=linear.width,
        height=linear.height,
        has_alpha=linear.hasalpha(),
        bit_depth=bit_depth,
        profile=profile,
        orientation=orientation,
    )
    return linear.cast("float"), info


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve() or (a.exists() and b.exists() and a.samefile(b))
    except OSError:
        return False


def encode(
    img: pyvips.Image,
    dest: str | Path,
    *,
    source: SourceInfo | None = None,
    protected: tuple[Path, ...] = (),
    quality: int = 92,
    color_space: ColorSpace = "sRGB",
    depth: Literal[8, 16] = 8,
    metadata: Metadata = "keep",
    overwrite: bool = False,
) -> Path:
    """Guarda una imagen scRGB float en `dest` (formato según la extensión) y devuelve la ruta.

    `depth=16` solo aplica a PNG y TIFF. JPEG no tiene alpha: se aplana sobre blanco.
    """
    dest = Path(dest).resolve()
    fmt = SUFFIXES.get(dest.suffix.lower())
    if fmt is None:
        raise ValueError(f"extensión de salida no soportada: {dest.suffix}")
    originals = (*protected, *((source.path,) if source else ()))
    if any(_same_file(dest, p) for p in originals):
        raise OriginalProtectedError(f"{dest.name} es un original: nunca se escribe encima")
    if dest.exists() and not overwrite:
        raise FileExistsError(f"{dest.name} ya existe")
    if not 1 <= quality <= 100:
        raise ValueError("quality debe estar entre 1 y 100")
    if depth == 16 and fmt not in ("png", "tiff"):
        raise ValueError(f"{fmt} no admite 16 bits por canal")

    if fmt == "jpeg" and img.hasalpha():
        img = img.flatten(background=[1.0, 1.0, 1.0], max_alpha=1.0)  # scRGB: 1.0 = blanco

    if color_space == "sRGB":
        out = img.colourspace("rgb16" if depth == 16 else "srgb")
        profile = "srgb"
    else:
        out = img.colourspace("lab").icc_export(output_profile="p3", intent="relative", depth=depth)
        profile = "p3"
    out = out.cast("ushort" if depth == 16 else "uchar")
    if out.get_typeof("icc-profile-data"):
        out = out.copy()
        out.remove("icc-profile-data")  # se embebe el perfil de salida correcto

    keep = pyvips.ForeignKeep.ALL if metadata == "keep" else pyvips.ForeignKeep.ICC
    options: dict = {"keep": keep, "profile": profile}
    if fmt == "jpeg":
        # 4:4:4 con Q alto: libvips ya lo hace desde Q 90 (spike #2); se fija explícito.
        options |= {"Q": quality, "optimize_coding": True,
                    "subsample_mode": "off" if quality >= 90 else "auto"}  # fmt: skip
    elif fmt == "webp":
        options |= {"Q": quality, "lossless": quality == 100}
    elif fmt == "png":
        options |= {"compression": 6}
    else:
        options |= {"compression": "deflate", "predictor": "horizontal"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.stem}.{secrets.token_hex(4)}.tmp{dest.suffix}")
    try:
        out.write_to_file(str(tmp), **options)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)

    if source is not None and sha256_file(source.path) != source.sha256:
        raise OriginalModifiedError(f"el original {source.path.name} cambió durante el export")
    return dest
