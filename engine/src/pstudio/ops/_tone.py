"""Herramientas comunes de las ops: luminancia, escala perceptual y curvas tonales por LUT.

Las ops trabajan sobre scRGB float32 lineal (ver render/io.py). Las curvas tonales se definen
sobre la luminancia en una escala perceptual `p = Y^(1/2.2)` (0 = negro, 1 = blanco difuso) y
se aplican como una razón sobre RGB, `RGB · Y'/Y`. Así cambian la luz sin correr el tono ni la
saturación, cosa que sí pasa cuando la curva se aplica por separado a R, G y B.

Rendimiento (#42): la curva se evalúa una vez en numpy y se aplica por píxel con una LUT de la
razón Y'/Y indexada por **los bits del float32 de Y**: los bits altos (exponente y 10 bits de
mantisa) eligen la entrada y los 13 bajos interpolan linealmente dentro de ella (en un mismo
exponente, la mantisa es lineal en Y). Así la grilla es logarítmica (1024 puntos por octava,
de 2^-32 a 2^31) y por píxel no hace falta ninguna potencia: quedan luminancia, desplazamiento
de bits, dos búsquedas y una multiplicación, sin importar cuántas ops tonales se encadenen.
Varias curvas seguidas se componen en una sola LUT (ver ops/__init__.py).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pyvips

from pstudio.colorimetry import GAMMA, LUMA

EPS = 1e-6
# Índice = (bits(Y) >> 13) − _BASE, recortado a 0…65535 por el cast a ushort: Y de 2^-32 a
# 2^31 con 1024 puntos por octava. La primera entrada es el negro (Y = 0, subnormales). La última
# entrada recibe lo que se pasa de rango: los Y negativos (bit de signo: bits enormes) y los
# absurdos (≥ 2^31); también cuenta como negro.
LUT_SIZE = 65536
_SHIFT = 13
_PER_OCTAVE = 1 << (23 - _SHIFT)
_BASE = (127 - 32) * _PER_OCTAVE
TOP = LUT_SIZE - 1

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


# Y al inicio de cada entrada y su p: fijos, se calculan una vez.
_GRID_Y = ((np.arange(LUT_SIZE, dtype=np.uint32) + _BASE) << _SHIFT).view(np.float32)
_GRID_Y = _GRID_Y.astype(np.float64)
_GRID_P = _GRID_Y ** (1 / GAMMA)
_SAFE = _GRID_Y > EPS
_EPS_ENTRY = int(np.argmax(_SAFE))  # primera entrada con Y > EPS
# centro de cada entrada: para LUTs sin interpolar (error ≤ media entrada, 0.05% de Y)
GRID_MID = (
    (((np.arange(LUT_SIZE, dtype=np.uint32) + _BASE) << _SHIFT) + (1 << (_SHIFT - 1)))
    .view(np.float32)
    .astype(np.float64)
)


def log_bits(y: pyvips.Image) -> tuple[pyvips.Image, pyvips.Image]:
    """(índice ushort de la LUT logarítmica, fracción 0…1 dentro de la entrada) de una imagen
    float de una banda. Valores ≤ 2^-32 van a la entrada 0; negativos y ≥ 2^31, a la última."""
    bits = y.copy(format="uint")  # mismos bytes, leídos como entero
    idx = ((bits >> _SHIFT) - _BASE).cast("ushort")  # el cast recorta a 0…65535
    return idx, (bits & ((1 << _SHIFT) - 1)) * (1 / (1 << _SHIFT))


def _to_y(curve: Curve, p: np.ndarray) -> np.ndarray:
    return np.maximum(curve(p), 0.0) ** GAMMA


def lut_image(columns: list[np.ndarray]) -> pyvips.Image:
    arr = np.ascontiguousarray(np.stack(columns, axis=-1), dtype=np.float32)
    return pyvips.Image.new_from_memory(arr.tobytes(), LUT_SIZE, 1, len(columns), "float")


def tone_luts(curve: Curve) -> tuple[pyvips.Image, pyvips.Image]:
    """(valores, diferencias con la entrada siguiente), indexadas como en apply_tone_curve.

    Cada entrada tiene la razón g = Y'/Y. Donde Y ≤ EPS la razón no está definida o se
    dispara (un píxel fuera de gama con Y ≈ 0 pero canales grandes):
    - si la curva deja el negro en negro, se usa Y'/Y pero sin pasar de 1: ahí no se amplifica
      nada (son negros: el cambio es < Y'(EPS), y la LUT queda de una sola banda);
    - si lo levanta (blacks > 0), hay una segunda banda h y el cambio se suma como gris
      neutro: g = 1, h = Y' − Y.
    El píxel sale como RGB·g (+ h).
    """
    y_new = _to_y(curve, _GRID_P)
    black = float(_to_y(curve, np.zeros(1))[0])
    g = y_new / _GRID_Y
    lift = black > 0
    if lift:
        h = np.where(_SAFE, 0.0, y_new - _GRID_Y)
        g = np.where(_SAFE, g, 1.0)
    else:
        g[:_EPS_ENTRY] = np.minimum(g[:_EPS_ENTRY], 1.0)
    # la primera entrada es el negro exacto (Y = 0 y subnormales) y la última, los negativos:
    # constantes (el recorte del índice deja bits al azar en la parte que interpola)
    g[0] = g[TOP] = 1.0
    d_g = _steps(g)
    if not lift:
        return lut_image([g]), lut_image([d_g])
    h[0] = h[TOP] = black
    return lut_image([g, h]), lut_image([d_g, _steps(h)])


def _steps(v: np.ndarray) -> np.ndarray:
    d = np.append(np.diff(v), 0.0)
    d[0] = d[TOP - 1] = 0.0
    return d


def apply_tone_curve(img: pyvips.Image, curve: Curve) -> pyvips.Image:
    """Aplica `curve` (p → p') a la luminancia y escala RGB por la razón Y'/Y.

    Los píxeles con Y ≤ 0 (negro o fuera de gama) reciben el cambio del negro puro.
    """
    rgb, alpha = split_alpha(img)
    lut, step = tone_luts(curve)
    idx, frac = log_bits(luminance(rgb))
    v = idx.maplut(lut) + idx.maplut(step) * frac
    out = rgb * v if v.bands == 1 else rgb * v[0] + v[1]
    return join_alpha(out, alpha)


def compose(curves: list[Curve]) -> Curve:
    def composed(p: np.ndarray) -> np.ndarray:
        for c in curves:
            p = c(p)
        return p

    return composed
