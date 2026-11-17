"""Catálogo cerrado de operaciones: cada op es una función pura (imagen, params) → imagen.

Se despachan por nombre a partir de un `EditPlan` ya validado. No hay forma de registrar ops
desde afuera ni de ejecutar código del plan (regla 1 de CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Callable

import pyvips

from pstudio.analysis import analyze, reduce_for_analysis
from pstudio.ops import color, detail, geometry, tonal
from pstudio.ops._tone import apply_tone_curve, compose
from pstudio.schema import EditPlan, Operation

_REGISTRY: dict[str, Callable[..., pyvips.Image]] = {
    **tonal.OPS,
    **color.OPS,
    **geometry.OPS,
    **detail.OPS,
}
# Ops que dependen de la resolución (radios o tamaños en píxeles de la imagen original).
SPATIAL = frozenset({"resize", "sharpen", "denoise", "crop", "rotate", "straighten", "vignette"})


def implemented() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def apply_op(img: pyvips.Image, op: Operation, scale: float = 1.0) -> pyvips.Image:
    """Aplica una op. `scale` = píxeles de `img` por píxel de la imagen original (< 1 en un
    proxy de preview); solo lo usan las ops espaciales."""
    fn = _REGISTRY.get(op.op)
    if fn is None:
        raise NotImplementedError(f"la op {op.op!r} todavía no está implementada")
    return fn(img, op, scale=scale) if op.op in SPATIAL else fn(img, op)


def apply_plan(img: pyvips.Image, plan: EditPlan, scale: float = 1.0) -> pyvips.Image:
    """Aplica las ops en el orden del plan (las neutras no hacen nada).

    - `scale`: píxeles de `img` por píxel de la imagen original. La preview trabaja sobre un
      proxy (p. ej. 2048 px de una foto de 6000 px → scale ≈ 0.34) y así radios y tamaños en
      píxeles dan el mismo resultado visual que en el export (scale = 1).
    - Las curvas tonales consecutivas se componen en una sola LUT: el resultado es el mismo que
      aplicarlas de a una (salvo error de interpolación < 1e-4), con una sola pasada por píxel.
    - Si hay ops automáticas, se mantiene una copia chica de la imagen (la de analysis.py) que
      pasa por las mismas ops; cada op automática mide esa copia. Así medir no obliga a
      calcular (y decodificar) la imagen entera una vez por op automática.
    """
    ops = [op for op in plan.operations if not op.is_noop()]
    proxy = proxy_scale = None
    if any(o.op in color.AUTO for o in ops):
        proxy = reduce_for_analysis(img).copy_memory()
        proxy_scale = scale * proxy.width / img.width
    pending: list = []

    def run(stage: Callable[[pyvips.Image, float], pyvips.Image]) -> None:
        nonlocal img, proxy
        img = stage(img, scale)
        if proxy is not None:
            proxy = stage(proxy, proxy_scale).copy_memory()

    def flush() -> None:
        if pending:
            curve = compose(list(pending))
            pending.clear()
            run(lambda image, _s: apply_tone_curve(image, curve))

    for op in ops:
        if op.op in tonal.CURVES:
            pending.append(tonal.CURVES[op.op](op))
            continue
        flush()
        if op.op in color.AUTO:
            stats = analyze(proxy)
            run(lambda image, _s, op=op, stats=stats: color.AUTO[op.op](image, op, stats))
        else:
            run(lambda image, s, op=op: apply_op(image, op, s))
    flush()
    return img
