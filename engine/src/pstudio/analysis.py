"""Analizadores deterministas de imagen: histograma, recorte y balance de blancos estimado.

Los usan las ops automáticas (`auto_exposure`, `auto_white_balance`) y, desde M2, el proveedor
de planes por reglas. Nada de IA: misma imagen → mismos números.

La imagen se reduce con promedio por bloques (`shrink`) a ≤ ANALYSIS_SIZE px de lado antes de
medir, así el costo no depende de la resolución y la preview (más chica) y el export dan
estadísticas casi iguales. Los píxeles totalmente transparentes no cuentan.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pyvips

from pstudio.colorimetry import GAMMA, LUMA

ANALYSIS_SIZE = 512
HIST_BINS = 64
CLIP_HIGH = 0.99  # Y lineal desde el cual un píxel se considera recortado en blanco
CLIP_LOW = 0.0005  # Y lineal (p ≈ 0.03) por debajo del cual se considera negro recortado
WHITE_PATCH_FRACTION = 0.01  # white_patch: promedio del 1% más luminoso que no esté recortado
# gray_world solo promedia píxeles poco saturados: (máx − mín)/máx < GRAY_WORLD_MAX_CHROMA.
# Con todos los píxeles, una pared roja o un mantel verde "son" el iluminante y la corrección
# tiñe la foto del color opuesto (probado con las fotos de tests/fixtures).
GRAY_WORLD_MAX_CHROMA = 0.5


@dataclass(frozen=True)
class ImageStats:
    width: int  # tamaño de la imagen analizada (tras reducir)
    height: int
    pixels: int  # píxeles que cuentan (alpha > 0)
    mean_luminance: float  # Y lineal
    log_mean_luminance: float  # media geométrica de Y (la "clave" de la escena)
    percentiles: dict[str, float]  # Y lineal en p1, p5, p50, p95, p99
    clipped_highlights: float  # fracción con Y ≥ CLIP_HIGH o algún canal ≥ 1
    clipped_shadows: float  # fracción con Y ≤ CLIP_LOW
    histogram: list[float]  # HIST_BINS bins de p = Y^(1/2.2) en [0, 1], suma 1
    gray_world_rgb: tuple[float, float, float]  # promedio RGB lineal de lo poco saturado
    white_patch_rgb: tuple[float, float, float]  # promedio del 1% más luminoso no recortado
    p99_unclipped: float  # p99 de Y entre lo no recortado (cuánto margen hay hasta el blanco)

    def to_dict(self) -> dict:
        return asdict(self)


def reduce_for_analysis(img: pyvips.Image) -> pyvips.Image:
    factor = max(img.width, img.height) / ANALYSIS_SIZE
    if factor <= 1:
        return img
    f = math.ceil(factor)
    return img.shrink(f, f)


def analyze(img: pyvips.Image) -> ImageStats:
    """Estadísticas de una imagen scRGB float (3 o 4 bandas)."""
    small = reduce_for_analysis(img)
    arr = small.numpy().reshape(-1, small.bands).astype(np.float64)
    rgb = arr[:, :3]
    if small.bands == 4:
        rgb = rgb[arr[:, 3] > 0]
    if rgb.size == 0:
        rgb = np.zeros((1, 3))
    y = np.maximum(rgb @ np.array(LUMA), 0.0)

    clipped = (y >= CLIP_HIGH) | (rgb.max(axis=1) >= 1.0)
    dark = y <= CLIP_LOW
    usable = ~clipped & ~dark
    pool = rgb[usable] if usable.any() else rgb

    hi, lo = pool.max(axis=1), pool.min(axis=1)
    chroma = (hi - lo) / np.maximum(hi, 1e-9)
    greyish = pool[chroma < GRAY_WORLD_MAX_CHROMA]
    if len(greyish) < 0.02 * len(pool):  # casi todo saturado: se usa todo
        greyish = pool

    y_pool = pool @ np.array(LUMA)
    n_top = max(1, round(len(y_pool) * WHITE_PATCH_FRACTION))
    top = pool[np.argpartition(y_pool, len(y_pool) - n_top)[-n_top:]]

    p = np.clip(y, 0.0, 1.0) ** (1 / GAMMA)
    hist, _ = np.histogram(p, bins=HIST_BINS, range=(0.0, 1.0))
    pct = np.percentile(y, [1, 5, 50, 95, 99])
    return ImageStats(
        width=small.width,
        height=small.height,
        pixels=len(y),
        mean_luminance=float(y.mean()),
        log_mean_luminance=float(np.exp(np.log(np.maximum(y, 1e-4)).mean())),
        percentiles={f"p{k}": float(v) for k, v in zip((1, 5, 50, 95, 99), pct, strict=True)},
        clipped_highlights=float(clipped.mean()),
        clipped_shadows=float(dark.mean()),
        histogram=(hist / len(y)).tolist(),
        gray_world_rgb=tuple(float(v) for v in greyish.mean(axis=0)),
        white_patch_rgb=tuple(float(v) for v in top.mean(axis=0)),
        p99_unclipped=float(np.percentile(y[~clipped], 99)) if (~clipped).any() else 1.0,
    )
