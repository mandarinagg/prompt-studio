"""Catálogo cerrado de operaciones: cada op es una función pura (imagen, params) → imagen.

Se despachan por nombre a partir de un `EditPlan` ya validado. No hay forma de registrar ops
desde afuera ni de ejecutar código del plan (regla 1 de CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Callable

import pyvips

from pstudio.analysis import analyze, reduce_for_analysis
from pstudio.ops import color, tonal
from pstudio.ops._tone import apply_tone_curve, compose
from pstudio.schema import EditPlan, Operation

_REGISTRY: dict[str, Callable[[pyvips.Image, object], pyvips.Image]] = {**tonal.OPS, **color.OPS}


def implemented() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def apply_op(img: pyvips.Image, op: Operation) -> pyvips.Image:
    fn = _REGISTRY.get(op.op)
    if fn is None:
        raise NotImplementedError(f"la op {op.op!r} todavía no está implementada")
    return fn(img, op)


def apply_plan(img: pyvips.Image, plan: EditPlan) -> pyvips.Image:
    """Aplica las ops en el orden del plan (las neutras no hacen nada).

    - Las curvas tonales consecutivas se componen en una sola LUT: el resultado es el mismo que
      aplicarlas de a una (salvo error de interpolación < 1e-4), con una sola pasada por píxel.
    - Si hay ops automáticas, se mantiene una copia chica de la imagen (la de analysis.py) que
      pasa por las mismas ops; cada op automática mide esa copia. Así medir no obliga a
      calcular (y decodificar) la imagen entera una vez por op automática.
    """
    ops = [op for op in plan.operations if not op.is_noop()]
    proxy = reduce_for_analysis(img).copy_memory() if any(o.op in color.AUTO for o in ops) else None
    pending: list = []

    def run(stage: Callable[[pyvips.Image], pyvips.Image]) -> None:
        nonlocal img, proxy
        img = stage(img)
        if proxy is not None:
            proxy = stage(proxy).copy_memory()

    def flush() -> None:
        if pending:
            curve = compose(list(pending))
            pending.clear()
            run(lambda image: apply_tone_curve(image, curve))

    for op in ops:
        if op.op in tonal.CURVES:
            pending.append(tonal.CURVES[op.op](op))
            continue
        flush()
        if op.op in color.AUTO:
            stats = analyze(proxy)
            run(lambda image, op=op, stats=stats: color.AUTO[op.op](image, op, stats))
        else:
            run(lambda image, op=op: apply_op(image, op))
    flush()
    return img
