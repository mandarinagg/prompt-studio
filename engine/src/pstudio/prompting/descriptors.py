"""Descriptores de la imagen para los proveedores: lo que "ven" de la foto, en pocos números.

Salen de los analizadores deterministas (analysis.py), se generan localmente y son solo texto:
ningún píxel sale del equipo (regla 3 de CLAUDE.md). El formato es el que usaron los casos de
evals/prompts (y el spike #5), así los evals y el uso real ven lo mismo.
"""

from __future__ import annotations

import math

from pstudio.analysis import ImageStats
from pstudio.colorimetry import GAMMA

MID_GREY = 0.18


def white_balance_label(rgb: tuple[float, float, float]) -> str:
    """Dominante estimada a partir del gris promedio (gray world sobre lo poco saturado)."""
    r, g, b = (max(v, 1e-6) for v in rgb)
    warmth = math.log2(r / b)  # > 0 cálido
    tint = math.log2(g / math.sqrt(r * b))  # > 0 verdoso
    if warmth > 0.8:
        label = "muy cálido"
    elif warmth > 0.3:
        label = "cálido"
    elif warmth < -0.8:
        label = "muy frío"
    elif warmth < -0.3:
        label = "frío"
    else:
        label = "neutro"
    if tint > 0.25:
        label += ", verdoso"
    elif tint < -0.25:
        label += ", magenta"
    return label


def describe(stats: ImageStats, width: int, height: int) -> dict:
    """Descriptores compactos. `width`/`height`: tamaño del original (no del análisis)."""
    p_mean = sum((i + 0.5) / len(stats.histogram) * h for i, h in enumerate(stats.histogram))
    return {
        "width": width,
        "height": height,
        "orientation": "horizontal"
        if width > height
        else "vertical"
        if height > width
        else "cuadrada",
        # brillo medio en escala perceptual (0 = negro, 1 = blanco), como lo ve una persona
        "mean_luminance": round(p_mean, 3),
        # clave de la escena respecto del gris medio, en EV (−1 = un paso subexpuesta)
        "exposure_ev": round(math.log2(max(stats.log_mean_luminance, 1e-4) / MID_GREY), 2),
        "clipped_shadows": round(stats.clipped_shadows, 3),
        "clipped_highlights": round(stats.clipped_highlights, 3),
        "white_balance_estimate": white_balance_label(stats.gray_world_rgb),
        "median_luminance": round(stats.percentiles["p50"] ** (1 / GAMMA), 3),
    }
