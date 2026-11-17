"""Ops de detalle (#13): sharpen, denoise, vignette.

sharpen y denoise trabajan sobre la luminancia en escala perceptual `p = Y^(1/2.2)` y aplican
el cambio como razón `RGB · Y'/Y` (igual que las curvas de _tone.py): no generan halos de
color. Sus radios están en píxeles de la imagen **original**; con `scale` < 1 (preview sobre un
proxy) se achican igual, así el proxy muestra lo que va a salir en el export a esa escala.

- sharpen: máscara de enfoque. p' = p + k·(p − blur_σ(p)), σ = radius, k = 2·amount/100.
- denoise: filtro guiado (He et al. 2010) sobre p, guiado por sí mismo: alisa donde la
  varianza local es parecida al ruido y respeta los bordes, donde es mucho mayor. El nivel de
  ruido que se considera "alisable" crece con strength. Antes difumina el ruido de color en
  Lab (canales a/b), que en fotos con poca luz es lo más visible. (Difuminar RGB − Y pasaba
  color del cielo a píxeles casi negros y la razón de luminancia lo amplificaba: aparecía una
  raya roja en los árboles de la foto nocturna de prueba.)
- vignette: multiplica la luz por 2^(VIGNETTE_EV·amount/100·f(r)), con r la distancia
  elíptica al centro (0 centro, 1 esquinas) y f un smoothstep que arranca en
  r = 0.9·midpoint/100. Negativo oscurece los bordes. No depende de la resolución.
"""

from __future__ import annotations

import math

import pyvips

from pstudio.ops._tone import EPS, GAMMA, join_alpha, luminance, split_alpha
from pstudio.schema.plan import Denoise, Sharpen, Vignette

SHARPEN_MAX = 2.0
DENOISE_RADIUS = 3.0  # px (imagen original) del filtro guiado
DENOISE_NOISE = 0.05  # desvío de ruido (en p) que strength = 1 considera alisable
CHROMA_SIGMA = 3.0  # px (imagen original) del difuminado de color con strength = 1
VIGNETTE_EV = 2.0
MIN_SIGMA = 0.3  # por debajo, el desenfoque no cambia nada visible a esa escala


def _perceptual(y: pyvips.Image) -> pyvips.Image:
    return (y > 0).ifthenelse(y, 0.0) ** (1 / GAMMA)


def _with_luminance(rgb: pyvips.Image, y: pyvips.Image, p_new: pyvips.Image) -> pyvips.Image:
    y_new = (p_new > 0).ifthenelse(p_new, 0.0) ** GAMMA
    safe = y > EPS
    ratio = safe.ifthenelse(y_new / safe.ifthenelse(y, 1.0), 1.0)
    offset = safe.ifthenelse(0.0, y_new - y)
    return rgb * ratio + offset


def _blur(img: pyvips.Image, sigma: float) -> pyvips.Image:
    return img.gaussblur(sigma, min_ampl=0.01, precision="float")


# ------------------------------------------------------------------ sharpen
def sharpen(img: pyvips.Image, op: Sharpen, scale: float = 1.0) -> pyvips.Image:
    sigma = op.radius * scale
    if op.is_noop() or sigma < MIN_SIGMA:
        return img
    rgb, alpha = split_alpha(img)
    y = luminance(rgb)
    p = _perceptual(y)
    k = SHARPEN_MAX * op.amount / 100
    p_new = p + (p - _blur(p, sigma)) * k
    return join_alpha(_with_luminance(rgb, y, p_new), alpha)


# ------------------------------------------------------------------ denoise
def _guided(p: pyvips.Image, sigma: float, eps: float) -> pyvips.Image:
    # Los desenfoques se hacen de a dos bandas (p y p², luego a y b): una pasada cada uno.
    moments = _blur(p.bandjoin(p * p), sigma)
    mean, mean_sq = moments[0], moments[1]
    var = mean_sq - mean * mean
    var = (var > 0).ifthenelse(var, 0.0)
    a = var / (var + eps)
    b = mean - a * mean
    coeffs = _blur(a.bandjoin(b), sigma)
    return coeffs[0] * p + coeffs[1]


def denoise(img: pyvips.Image, op: Denoise, scale: float = 1.0) -> pyvips.Image:
    sigma = DENOISE_RADIUS * scale
    if op.is_noop() or sigma < MIN_SIGMA:
        return img
    rgb, alpha = split_alpha(img)
    c_sigma = CHROMA_SIGMA * op.strength * scale
    if c_sigma >= MIN_SIGMA:
        lab = rgb.copy(interpretation="scrgb").colourspace("lab")
        ab = lab.extract_band(1, n=2)
        ab = ab + (_blur(ab, c_sigma) - ab) * op.strength
        rgb = lab.extract_band(0).bandjoin(ab).copy(interpretation="lab").colourspace("scrgb")
    # se materializa una vez: rgb se usa dos veces (para medir y para el resultado) y el
    # filtro guiado anida desenfoques; sin esto libvips recalcula decode + Lab por tile
    rgb = rgb.copy_memory()
    y = luminance(rgb)
    p = _perceptual(y)
    eps = (DENOISE_NOISE * op.strength) ** 2
    return join_alpha(_with_luminance(rgb, y, _guided(p, sigma, eps)), alpha)


# ------------------------------------------------------------------ vignette
def vignette_gain(width: int, height: int, op: Vignette) -> pyvips.Image:
    """Ganancia por píxel (1 banda float)."""
    xyz = pyvips.Image.xyz(width, height).cast("float")
    x = (xyz[0] + 0.5 - width / 2) / (width / 2)
    y = (xyz[1] + 0.5 - height / 2) / (height / 2)
    r = (x * x + y * y) ** 0.5 / math.sqrt(2)
    start = 0.9 * op.midpoint / 100
    t = (r - start) / (1 - start)
    t = (t < 0).ifthenelse(0.0, (t > 1).ifthenelse(1.0, t))
    f = t * t * (3 - t * 2)
    return (f * (VIGNETTE_EV * op.amount / 100 * math.log(2))).exp()


def vignette(img: pyvips.Image, op: Vignette, scale: float = 1.0) -> pyvips.Image:
    if op.is_noop():
        return img
    rgb, alpha = split_alpha(img)
    return join_alpha(rgb * vignette_gain(img.width, img.height, op), alpha)


OPS = {"sharpen": sharpen, "denoise": denoise, "vignette": vignette}
