"""Ops de color (#12): white_balance, auto_white_balance, saturation, vibrance, auto_exposure.

Funciones puras `(scRGB float32, op) → scRGB float32`; en su valor neutro devuelven la misma
imagen y nunca tocan el alpha.

- white_balance: adaptación cromática en el espacio de conos (Bradford), como corrige una
  cámara. temperature_shift ±100 multiplica L/S por 2^(±TEMP_EV/2)·2^(∓TEMP_EV/2), o sea hasta
  TEMP_EV de diferencia entre rojo y azul; tint_shift ±100 lleva M (verde) hasta ∓TINT_EV.
  Después se normaliza para que el gris conserve su luminancia. Es una matriz 3×3 (recomb).
- auto_white_balance: estima el color del iluminante (analysis.py) y lo lleva a neutro con la
  misma adaptación. gray_world: el promedio de lo poco saturado es gris. white_patch: el 1% más
  luminoso (sin recortados) es blanco. La corrección se limita a MAX_AUTO_WB_EV por canal para
  no destrozar escenas de un solo color (un atardecer, una pared verde).
- saturation: rgb' = Y + (rgb − Y)·k con k = 1 + s (s = amount/100): −100 da blanco y negro,
  +100 duplica la distancia al gris. Conserva la luminancia exacta. También es una 3×3.
- vibrance: como saturation, pero k = 1 + s·(1 − c), donde c = (máx − mín)/máx es la
  saturación actual del píxel medida en escala perceptual (RGB^(1/2.2)): sube los colores
  apagados y casi no toca los ya saturados. (Medida en lineal, hasta un marrón apagado da
  c ≈ 0.6 y la op casi no hacía nada en las fotos de prueba.)
- auto_exposure: mira la clave de la escena (media geométrica de Y). Si está dentro de
  [KEY_LOW, KEY_HIGH] no hace nada: una foto de producto sobre blanco o un nocturno pueden ser
  claros u oscuros a propósito. Fuera de ese rango la lleva al borde más cercano, pero solo
  oscurece si la foto está lavada (sin tonos profundos: p1 > WASHED_OUT_P1): oscurecer el
  fondo blanco de una foto de producto lo volvía gris. Al aclarar no
  empuja a recortado lo que hoy está bien: el p99 de lo no recortado queda ≤ 1. Resultado entre
  ±MAX_AUTO_EV, escalado por strength.
"""

from __future__ import annotations

import math

import numpy as np
import pyvips

from pstudio.analysis import ImageStats, analyze
from pstudio.ops._tone import (
    EPS,
    GAMMA,
    GRID_MID,
    LUMA,
    TOP,
    join_alpha,
    log_bits,
    luminance,
    lut_image,
    split_alpha,
)
from pstudio.schema.plan import AutoExposure, AutoWhiteBalance, Saturation, Vibrance, WhiteBalance

TEMP_EV = 0.6  # diferencia L/S en conos (EV) con ±100: ≈ 1 EV entre rojo y azul en RGB
TINT_EV = 0.5  # cambio máximo del verde (en EV) con tint_shift = ±100
MAX_AUTO_WB_EV = 1.0
KEY_LOW, KEY_HIGH = 0.10, 0.45  # banda muerta de la clave (Y lineal)
WASHED_OUT_P1 = 0.10
MAX_AUTO_EV = 2.0

# sRGB lineal (D65) → XYZ, y Bradford XYZ → LMS.
_RGB2XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
_BRADFORD = np.array(
    [
        [0.8951, 0.2664, -0.1614],
        [-0.7502, 1.7135, 0.0367],
        [0.0389, -0.0685, 1.0296],
    ]
)
_RGB2LMS = _BRADFORD @ _RGB2XYZ
_LMS2RGB = np.linalg.inv(_RGB2LMS)
_LUMA = np.array(LUMA)


def _apply_matrix(img: pyvips.Image, m: np.ndarray) -> pyvips.Image:
    rgb, alpha = split_alpha(img)
    return join_alpha(rgb.recomb(m.tolist()), alpha)


def _lms_gain_matrix(gains: np.ndarray) -> np.ndarray:
    """Matriz RGB→RGB que multiplica los conos por `gains`, conservando la Y del gris."""
    m = _LMS2RGB @ np.diag(gains) @ _RGB2LMS
    grey_y = _LUMA @ m @ np.ones(3)
    return m / grey_y


def white_balance_matrix(op: WhiteBalance) -> np.ndarray:
    t, g = op.temperature_shift / 100, op.tint_shift / 100
    half = TEMP_EV / 2 * t
    gains = 2.0 ** np.array([half, -TINT_EV * g, -half])
    return _lms_gain_matrix(gains)


def white_balance(img: pyvips.Image, op: WhiteBalance) -> pyvips.Image:
    return img if op.is_noop() else _apply_matrix(img, white_balance_matrix(op))


def auto_white_balance_matrix(
    img: pyvips.Image, op: AutoWhiteBalance, stats: ImageStats | None = None
) -> np.ndarray:
    stats = stats or analyze(img)
    illum = np.array(stats.gray_world_rgb if op.method == "gray_world" else stats.white_patch_rgb)
    lms = _RGB2LMS @ np.maximum(illum, EPS)
    target = _RGB2LMS @ np.full(3, max(float(_LUMA @ illum), EPS))  # gris de igual luminancia
    limit = 2.0**MAX_AUTO_WB_EV
    gains = np.clip(target / np.maximum(lms, EPS), 1 / limit, limit)
    return _lms_gain_matrix(gains)


def auto_white_balance(
    img: pyvips.Image, op: AutoWhiteBalance, stats: ImageStats | None = None
) -> pyvips.Image:
    return _apply_matrix(img, auto_white_balance_matrix(img, op, stats))


def saturation_matrix(op: Saturation) -> np.ndarray:
    k = 1 + op.amount / 100
    return k * np.eye(3) + (1 - k) * np.tile(_LUMA, (3, 1))


def saturation(img: pyvips.Image, op: Saturation) -> pyvips.Image:
    return img if op.is_noop() else _apply_matrix(img, saturation_matrix(op))


def vibrance_lut(op: Vibrance) -> pyvips.Image:
    """k en función de r = mín/máx, indexada por los bits de r (_tone.log_bits).

    c = (h^(1/γ) − l^(1/γ)) / h^(1/γ) = 1 − r^(1/γ), así que k = 1 + s·r^(1/γ). r < 0 (algún
    canal negativo: fuera de gama) cuenta como c = 1, y r > 1 (todos negativos) como c = 0.
    """
    k = 1 + op.amount / 100 * np.minimum(GRID_MID, 1.0) ** (1 / GAMMA)
    k[0] = k[TOP] = 1.0
    return lut_image([k])


def vibrance(img: pyvips.Image, op: Vibrance) -> pyvips.Image:
    if op.is_noop():
        return img
    rgb, alpha = split_alpha(img)
    y = luminance(rgb)
    r, g, b = rgb[0], rgb[1], rgb[2]
    hi, lo = r.bandrank([g, b], index=2), r.bandrank([g, b], index=0)
    idx, _ = log_bits(lo / hi)  # sin luz (máx = 0) libvips da 0: k = 1, no hay color
    k = idx.maplut(vibrance_lut(op))
    # = Y + (RGB − Y)·k, con la imagen de 3 bandas leída una sola vez
    return join_alpha(rgb * k + y * (1 - k), alpha)


def auto_exposure_ev(img: pyvips.Image, op: AutoExposure, stats: ImageStats | None = None) -> float:
    stats = stats or analyze(img)
    key = max(stats.log_mean_luminance, 1e-4)
    ev = 0.0
    if key < KEY_LOW:
        ev = math.log2(KEY_LOW / key)
    elif key > KEY_HIGH and stats.percentiles["p1"] > WASHED_OUT_P1:
        ev = math.log2(KEY_HIGH / key)
    if ev > 0:
        # no recortar lo que hoy está bien expuesto: el p99 de lo no recortado queda ≤ 1
        headroom = math.log2(1.0 / max(stats.p99_unclipped, 1e-4))
        ev = min(ev, max(headroom, 0.0))
    return op.strength * max(-MAX_AUTO_EV, min(MAX_AUTO_EV, ev))


def auto_exposure(
    img: pyvips.Image, op: AutoExposure, stats: ImageStats | None = None
) -> pyvips.Image:
    if op.is_noop():
        return img
    ev = auto_exposure_ev(img, op, stats)
    if ev == 0:
        return img
    rgb, alpha = split_alpha(img)
    return join_alpha(rgb * (2.0**ev), alpha)


# Ops automáticas: miden la imagen (analysis.py). Aceptan `stats` ya calculadas para que
# apply_plan las mida sobre una copia chica en lugar de recalcular la imagen entera.
AUTO = {"auto_white_balance": auto_white_balance, "auto_exposure": auto_exposure}

OPS = {
    "white_balance": white_balance,
    "auto_white_balance": auto_white_balance,
    "saturation": saturation,
    "vibrance": vibrance,
    "auto_exposure": auto_exposure,
}
