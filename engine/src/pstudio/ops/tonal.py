"""Ops tonales (#11): exposure, contrast, highlights, shadows, whites, blacks.

Todas son funciones puras `(scRGB float32, op) → scRGB float32`, globales (sin máscara
espacial) y **monótonas**: nunca invierten el orden de los tonos (verificado en los tests). En
su valor neutro devuelven la misma imagen.

`exposure` multiplica la luz lineal por 2^ev. Las demás son curvas sobre la escala perceptual
p (ver _tone.py), con s = amount/100:
- contrast:   potencia alrededor del gris medio (p₀ = 0.18^(1/2.2) ≈ 0.459), k = 2.5^s.
              Conserva 0, p₀ y 1; por encima del blanco no cambia.
- shadows:    en EV respecto del gris medio (e = log2(Y/0.18)): sube hasta 3·s EV las sombras
              profundas (e ≤ −6) y el efecto se apaga con un smoothstep hasta 0 en e = 0. Medios
              y altas luces no cambian. El negro puro sigue negro. Pendiente máx. 0.75 < 1:
              monótona. (Una versión en p, con pico en 1/3, daba solo +1.8 EV en el contraluz
              de tests/fixtures y el árbol seguía negro.)
- highlights: p + 0.115·s·B(1−p), con B(q) = 6.75·q·(1−q)², pico en p = 2/3. Conserva 0 y 1.
- whites:     p + 0.25·s·p³ (mueve el punto blanco: s = 1 lleva p = 1 a 1.25).
- blacks:     p + 0.25·s·(1−p)³ (mueve el punto negro; con s < 0 aplasta las sombras a 0).
En highlights, whites y blacks las constantes son las máximas que mantienen la pendiente
≥ 0.2 (≥ 0 en contrast y blacks). Fuera de [0, 1] el peso se evalúa en el borde, sin saltos.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pyvips

from pstudio.ops._tone import GAMMA, Curve, apply_tone_curve, join_alpha, split_alpha
from pstudio.schema.plan import Blacks, Contrast, Exposure, Highlights, Shadows, Whites

MID_GREY = 0.18
PIVOT = MID_GREY ** (1 / GAMMA)  # gris medio en escala perceptual
CONTRAST_MAX_K = 2.5
SHADOWS_MAX_EV = 3.0
SHADOWS_RANGE_EV = 6.0
HIGHLIGHTS_STRENGTH = 0.115
ENDPOINT_STRENGTH = 0.25


def exposure(img: pyvips.Image, op: Exposure) -> pyvips.Image:
    """Multiplica la luz lineal por 2^ev, igual que cambiar la exposición en cámara."""
    if op.is_noop():
        return img
    rgb, alpha = split_alpha(img)
    return join_alpha(rgb * (2.0**op.ev), alpha)


# ------------------------------------------------------------------ curvas (numpy, p → p')
def contrast_curve(op: Contrast) -> Curve:
    k = CONTRAST_MAX_K ** (op.amount / 100)

    def curve(p: np.ndarray) -> np.ndarray:
        q = np.clip(p, 0.0, 1.0)
        low = PIVOT * (q / PIVOT) ** k
        high = 1 - (1 - PIVOT) * ((1 - q) / (1 - PIVOT)) ** k
        return np.where(p > 1, p, np.where(q < PIVOT, low, high))

    return curve


def shadows_curve(op: Shadows) -> Curve:
    s = op.amount / 100

    def curve(p: np.ndarray) -> np.ndarray:
        y = np.maximum(p, 0.0) ** GAMMA
        ev = np.log2(np.maximum(y, 1e-12) / MID_GREY)
        t = np.clip(-ev / SHADOWS_RANGE_EV, 0.0, 1.0)
        return (y * 2.0 ** (s * SHADOWS_MAX_EV * t * t * (3 - 2 * t))) ** (1 / GAMMA)

    return curve


def _bump(weight: Callable[[np.ndarray], np.ndarray], strength: float):
    def make(op: Highlights | Whites | Blacks) -> Curve:
        s = op.amount / 100
        return lambda p: p + strength * s * weight(np.clip(p, 0.0, 1.0))

    return make


highlights_curve = _bump(lambda q: 6.75 * (1 - q) * q**2, HIGHLIGHTS_STRENGTH)
whites_curve = _bump(lambda q: q**3, ENDPOINT_STRENGTH)
blacks_curve = _bump(lambda q: (1 - q) ** 3, ENDPOINT_STRENGTH)

# Ops que son una curva de luminancia: apply_plan compone las consecutivas en una sola LUT.
CURVES: dict[str, Callable] = {
    "contrast": contrast_curve,
    "shadows": shadows_curve,
    "highlights": highlights_curve,
    "whites": whites_curve,
    "blacks": blacks_curve,
}


def _curve_op(name: str):
    make = CURVES[name]

    def apply(img: pyvips.Image, op) -> pyvips.Image:
        return img if op.is_noop() else apply_tone_curve(img, make(op))

    apply.__name__ = name
    return apply


OPS = {"exposure": exposure, **{name: _curve_op(name) for name in CURVES}}
