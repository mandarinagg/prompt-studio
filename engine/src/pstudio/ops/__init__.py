"""Catálogo cerrado de operaciones: cada op es una función pura (imagen, params) → imagen.

Se despachan por nombre a partir de un `EditPlan` ya validado. No hay forma de registrar ops
desde afuera ni de ejecutar código del plan (regla 1 de CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Callable

import pyvips

from pstudio.ops import tonal
from pstudio.ops._tone import apply_tone_curve, compose
from pstudio.schema import EditPlan, Operation

_REGISTRY: dict[str, Callable[[pyvips.Image, object], pyvips.Image]] = {**tonal.OPS}


def implemented() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def apply_op(img: pyvips.Image, op: Operation) -> pyvips.Image:
    fn = _REGISTRY.get(op.op)
    if fn is None:
        raise NotImplementedError(f"la op {op.op!r} todavía no está implementada")
    return fn(img, op)


def apply_plan(img: pyvips.Image, plan: EditPlan) -> pyvips.Image:
    """Aplica las ops en el orden del plan (las neutras no hacen nada).

    Las curvas tonales consecutivas se componen en una sola LUT: el resultado es el mismo que
    aplicarlas de a una (salvo error de interpolación < 1e-4), con una sola pasada por píxel.
    """
    pending: list = []

    def flush(image: pyvips.Image) -> pyvips.Image:
        if pending:
            image = apply_tone_curve(image, compose(pending))
            pending.clear()
        return image

    for op in plan.operations:
        if op.is_noop():
            continue
        if op.op in tonal.CURVES:
            pending.append(tonal.CURVES[op.op](op))
            continue
        img = apply_op(flush(img), op)
    return flush(img)
