"""Herramientas comunes de las ops: luminancia, escala perceptual y curvas tonales por LUT.

Las ops trabajan sobre scRGB float32 lineal (ver render/io.py). Las curvas tonales se definen
sobre la luminancia en una escala perceptual `p = Y^(1/2.2)` (0 = negro, 1 = blanco difuso) y
se aplican como una razón sobre RGB, `RGB · Y'/Y`. Así cambian la luz sin correr el tono ni la
saturación, cosa que sí pasa cuando la curva se aplica por separado a R, G y B.

Rendimiento: la curva se evalúa una vez en numpy sobre una grilla de p ∈ [0, P_MAX] y se
aplica por píxel con una LUT con interpolación lineal (maplut de libvips). Por píxel queda una
potencia y una búsqueda, sin importar cuántas ops tonales se encadenen. Varias curvas seguidas
se componen en una sola LUT (ver ops/__init__.py).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pyvips

GAMMA = 2.2
# Luminancia Rec.709/sRGB lineal (los primarios del espacio de trabajo).
LUMA = (0.2126, 0.7152, 0.0722)
EPS = 1e-6
# Grilla de la LUT: 32768 puntos por unidad de p, así que p = 0 y p = 1 (negro y blanco) caen
# exactos en la grilla. Llega hasta p ≈ 2 (Y ≈ 4.6, más de 2 EV sobre el blanco difuso).
LUT_SIZE = 65536
LUT_SCALE = 32768.0
P_MAX = (LUT_SIZE - 1) / LUT_SCALE

Curve = Callable[[np.ndarray], np.ndarray]  # p → p' (numpy, vectorizada)


def split_alpha(img: pyvips.Image) -> tuple[pyvips.Image, pyvips.Image | None]:
    if img.bands == 4:
        return img.extract_band(0, n=3), img.extract_band(3)
    return img, None


def join_alpha(rgb: pyvips.Image, alpha: pyvips.Image | None) -> pyvips.Image:
    out = rgb if alpha is None else rgb.bandjoin(alpha)
    return out.copy(interpretation="scrgb").cast("float")


def luminance(rgb: pyvips.Image) -> pyvips.Image:
    return rgb.recomb([list(LUMA)])


def _lut(curve: Curve) -> tuple[pyvips.Image, pyvips.Image, float]:
    """LUT de Y' indexada por p, más la de diferencias (para interpolar) y la escala."""
    p = np.arange(LUT_SIZE) / LUT_SCALE
    y_new = np.maximum(curve(p), 0.0) ** GAMMA
    step = np.append(np.diff(y_new), 0.0)
    to_img = lambda a: pyvips.Image.new_from_array(a.astype(np.float32).reshape(1, -1))  # noqa: E731
    return to_img(y_new), to_img(step), LUT_SCALE


def apply_tone_curve(img: pyvips.Image, curve: Curve) -> pyvips.Image:
    """Aplica `curve` (p → p') a la luminancia y escala RGB por la razón Y'/Y.

    Por encima de P_MAX la curva se extiende con la ganancia del último punto de la grilla.
    """
    rgb, alpha = split_alpha(img)
    y = luminance(rgb)
    lut, step, scale = _lut(curve)

    p = (y > 0).ifthenelse(y, 0.0) ** (1 / GAMMA)
    x = _upto(p * scale)
    i = x.floor()
    idx = i.cast("ushort")
    y_lut = idx.maplut(lut) + idx.maplut(step) * (x - i)

    top_gain = float(lut.getpoint(LUT_SIZE - 1, 0)[0]) / P_MAX**GAMMA
    y_new = (p > P_MAX).ifthenelse(y * top_gain, y_lut)
    # Donde Y ≈ 0 la razón no está definida: se suma el cambio como gris neutro.
    safe = y > EPS
    ratio = safe.ifthenelse(y_new / safe.ifthenelse(y, 1.0), 1.0)
    offset = safe.ifthenelse(0.0, y_new - y)
    return join_alpha(rgb * ratio + offset, alpha)


def _upto(x: pyvips.Image) -> pyvips.Image:
    top = float(LUT_SIZE - 1)
    return (x > top).ifthenelse(top, x)


def compose(curves: list[Curve]) -> Curve:
    def composed(p: np.ndarray) -> np.ndarray:
        for c in curves:
            p = c(p)
        return p

    return composed
