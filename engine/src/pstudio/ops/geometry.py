"""Ops geométricas (#13): crop, rotate, straighten, resize.

Todas trabajan en scRGB float lineal, así que remuestrear (rotar, cambiar tamaño) promedia luz
real y no oscurece bordes finos como pasa en sRGB. El alpha se premultiplica antes de
remuestrear para que los bordes transparentes no "sangren" color.

- crop: `rect` en fracciones de la imagen, o el rectángulo más grande con `aspect_ratio`
  ubicado según `anchor`. `subject_or_center` centra el recorte en el punto de atención de
  libvips (bordes, color de piel y saturación), medido sobre la imagen reducida de
  analysis.py: es determinista y da el mismo encuadre en preview y en export.
- rotate: horario. Los múltiplos de 90° son exactos (sin remuestrear). Otros ángulos agrandan
  el lienzo para que entre toda la foto; las esquinas nuevas quedan transparentes (al exportar
  a JPEG se aplanan sobre blanco).
- straighten: rota y recorta al rectángulo más grande con las proporciones originales que
  queda dentro de la foto rotada (como la herramienta "enderezar" de cualquier editor).
- resize: Lanczos3. `width`/`height` están en píxeles de la imagen original: con `scale` < 1
  (preview sobre un proxy) se escalan igual, para que el resultado sea el mismo encuadre.
"""

from __future__ import annotations

import math

import pyvips

from pstudio.analysis import reduce_for_analysis
from pstudio.schema.plan import Crop, Resize, Rotate, Straighten

INTERPOLATE = "bicubic"
ASPECTS = {
    "1:1": 1.0,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
}


def _finish(img: pyvips.Image) -> pyvips.Image:
    return img.copy(interpretation="scrgb").cast("float")


def _premultiplied(img: pyvips.Image, fn) -> pyvips.Image:
    """Aplica `fn` (remuestreo) con alpha premultiplicado si hay alpha."""
    if img.bands != 4:
        return _finish(fn(img))
    return _finish(fn(img.premultiply(max_alpha=1.0)).unpremultiply(max_alpha=1.0))


# ------------------------------------------------------------------ crop
def crop_box(
    width: int, height: int, op: Crop, focus: tuple[float, float] | None = None
) -> tuple[int, int, int, int]:
    """Rectángulo (left, top, w, h) en píxeles. `focus` = punto de atención en fracciones."""
    if op.rect is not None:
        r = op.rect
        left, top = round(r.x * width), round(r.y * height)
        w = max(1, min(width - left, round(r.width * width)))
        h = max(1, min(height - top, round(r.height * height)))
        return left, top, w, h

    ratio = ASPECTS[op.aspect_ratio]
    if width / height > ratio:
        w, h = max(1, round(height * ratio)), height
    else:
        w, h = width, max(1, round(width / ratio))
    cx, cy = 0.5, 0.5
    if op.anchor == "subject_or_center" and focus is not None:
        cx, cy = focus
    left = round(cx * width - w / 2)
    top = round(cy * height - h / 2)
    if op.anchor == "left":
        left = 0
    elif op.anchor == "right":
        left = width - w
    elif op.anchor == "top":
        top = 0
    elif op.anchor == "bottom":
        top = height - h
    left = min(max(left, 0), width - w)
    top = min(max(top, 0), height - h)
    return left, top, w, h


def attention_point(img: pyvips.Image) -> tuple[float, float]:
    """Punto de interés (fracciones 0…1) según libvips, sobre la imagen reducida en sRGB."""
    small = reduce_for_analysis(img)
    rgb = small.extract_band(0, n=3) if small.bands == 4 else small
    srgb = rgb.copy(interpretation="scrgb").colourspace("srgb").cast("uchar")
    side = max(1, min(srgb.width, srgb.height) // 2)
    _, pos = srgb.smartcrop(side, side, interesting="attention", attention_x=True, attention_y=True)
    return pos["attention_x"] / srgb.width, pos["attention_y"] / srgb.height


def crop(img: pyvips.Image, op: Crop, scale: float = 1.0) -> pyvips.Image:
    focus = attention_point(img) if op.anchor == "subject_or_center" and op.rect is None else None
    left, top, w, h = crop_box(img.width, img.height, op, focus)
    if (left, top, w, h) == (0, 0, img.width, img.height):
        return img
    return img.crop(left, top, w, h)


# ------------------------------------------------------------------ rotate / straighten
def _ensure_alpha(img: pyvips.Image) -> pyvips.Image:
    return img if img.bands == 4 else img.bandjoin_const([1.0])


def rotate(img: pyvips.Image, op: Rotate, scale: float = 1.0) -> pyvips.Image:
    if op.is_noop():
        return img
    quarter = op.degrees / 90
    if quarter == round(quarter):
        turn = {1: "d90", 2: "d180", -2: "d180", -1: "d270"}[round(quarter)]
        return img.rot(turn)
    interp = pyvips.Interpolate.new(INTERPOLATE)
    return _premultiplied(
        _ensure_alpha(img),
        lambda im: im.rotate(op.degrees, interpolate=interp, background=[0.0] * im.bands),
    )


def straighten_scale(width: int, height: int, degrees: float) -> float:
    """Factor s: el rectángulo s·w × s·h centrado entra en la foto rotada `degrees`."""
    t = math.radians(abs(degrees))
    c, s = math.cos(t), math.sin(t)
    return min(width / (width * c + height * s), height / (width * s + height * c))


def straighten(img: pyvips.Image, op: Straighten, scale: float = 1.0) -> pyvips.Image:
    if op.is_noop():
        return img
    w, h = img.width, img.height
    interp = pyvips.Interpolate.new(INTERPOLATE)
    rotated = _premultiplied(img, lambda im: im.rotate(op.degrees, interpolate=interp))
    k = straighten_scale(w, h, op.degrees)
    # 2 px de margen por lado (el alcance del kernel bicúbico): si no, el borde mezcla el
    # fondo vacío de la rotación y queda un filo (lo detectó el test con 3°)
    cw, ch = max(1, math.floor(k * w) - 4), max(1, math.floor(k * h) - 4)
    left = (rotated.width - cw) // 2
    top = (rotated.height - ch) // 2
    return rotated.crop(left, top, cw, ch)


# ------------------------------------------------------------------ resize
def resize_size(width: int, height: int, op: Resize, scale: float = 1.0) -> tuple[int, int]:
    tw = None if op.width is None else op.width * scale
    th = None if op.height is None else op.height * scale
    if op.fit == "exact":
        return max(1, round(tw)), max(1, round(th))
    sx = None if tw is None else tw / width
    sy = None if th is None else th / height
    if sx is None or sy is None:
        k = sx if sy is None else sy
    else:
        k = max(sx, sy) if op.fit == "cover" else min(sx, sy)
    return max(1, round(width * k)), max(1, round(height * k))


def resize(img: pyvips.Image, op: Resize, scale: float = 1.0) -> pyvips.Image:
    w, h = resize_size(img.width, img.height, op, scale)
    if (w, h) != (img.width, img.height):
        hs, vs = w / img.width, h / img.height
        img = _premultiplied(img, lambda im: im.resize(hs, vscale=vs, kernel="lanczos3"))
        # resize puede redondear un píxel distinto: se fuerza el tamaño pedido
        img = img.crop(0, 0, min(w, img.width), min(h, img.height))
    if op.fit == "cover":
        tw = round(op.width * scale)
        th = round(op.height * scale)
        tw, th = max(1, min(tw, img.width)), max(1, min(th, img.height))
        img = img.crop((img.width - tw) // 2, (img.height - th) // 2, tw, th)
    return img


OPS = {"crop": crop, "rotate": rotate, "straighten": straighten, "resize": resize}


def output_size(width: int, height: int, operations) -> tuple[int, int]:
    """Tamaño final (aprox. ±2 px) que deja la parte geométrica de un plan, sin procesar
    píxeles. Lo usa el export para decidir cuánto puede achicar antes de aplicar el plan."""
    w, h = width, height
    for op in operations:
        if op.is_noop():
            continue
        if op.op == "crop":
            focus = (0.5, 0.5)  # el ancla de sujeto no cambia el tamaño, solo la posición
            _, _, w, h = crop_box(w, h, op, focus)
        elif op.op == "rotate":
            if (op.degrees / 90) == round(op.degrees / 90):
                if round(op.degrees / 90) % 2:
                    w, h = h, w
            else:
                t = math.radians(abs(op.degrees))
                c, s = abs(math.cos(t)), abs(math.sin(t))
                w, h = round(w * c + h * s), round(w * s + h * c)
        elif op.op == "straighten":
            k = straighten_scale(w, h, op.degrees)
            w, h = max(1, math.floor(k * w) - 4), max(1, math.floor(k * h) - 4)
        elif op.op == "resize":
            w, h = resize_size(w, h, op)
    return w, h
