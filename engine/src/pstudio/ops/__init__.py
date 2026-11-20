"""Catálogo cerrado de operaciones: cada op es una función pura (imagen, params) → imagen.

Se despachan por nombre a partir de un `EditPlan` ya validado. No hay forma de registrar ops
desde afuera ni de ejecutar código del plan (regla 1 de CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pyvips

from pstudio.analysis import ImageStats, analyze, reduce_for_analysis
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


# ------------------------------------------------------------------ etapas del render
@dataclass(frozen=True)
class Stage:
    """Un paso del render: un grupo de curvas tonales consecutivas (una sola LUT), una op
    automática (mide la copia de análisis) o cualquier otra op sola."""

    ops: tuple[Operation, ...]

    @property
    def is_auto(self) -> bool:
        return self.ops[0].op in color.AUTO


@dataclass(frozen=True)
class RenderState:
    """La imagen entre dos etapas, más la copia chica que miden las ops automáticas."""

    image: pyvips.Image
    scale: float
    analysis: pyvips.Image | None = None  # reduce_for_analysis(entrada) tras las mismas etapas
    analysis_scale: float = 0.0
    # medición de `analysis`, calculada la primera vez que una op automática la pide. El estado
    # cacheado de un prefijo la conserva: al mover el slider de esa op no se vuelve a medir.
    _stats: list[ImageStats] = field(default_factory=list, compare=False, repr=False)

    def stats(self) -> ImageStats:
        if not self._stats:
            self._stats.append(analyze(self.analysis))
        return self._stats[0]


def plan_stages(plan: EditPlan) -> list[Stage]:
    """Etapas del plan en orden: sin las ops neutras y con las curvas consecutivas juntas."""
    stages: list[Stage] = []
    curves: list[Operation] = []
    for op in plan.operations:
        if op.is_noop():
            continue
        if op.op in tonal.CURVES:
            curves.append(op)
            continue
        if curves:
            stages.append(Stage(tuple(curves)))
            curves = []
        stages.append(Stage((op,)))
    if curves:
        stages.append(Stage(tuple(curves)))
    return stages


def auto_ahead(stages: list[Stage]) -> list[bool]:
    """`[i]` = hay alguna op automática en `stages[i:]` (largo n + 1; el último es False)."""
    ahead = [False] * (len(stages) + 1)
    for i in range(len(stages) - 1, -1, -1):
        ahead[i] = ahead[i + 1] or stages[i].is_auto
    return ahead


def start_state(img: pyvips.Image, scale: float, with_analysis: bool) -> RenderState:
    if not with_analysis:
        return RenderState(img, scale)
    small = reduce_for_analysis(img).copy_memory()
    return RenderState(img, scale, small, scale * small.width / img.width)


def run_stage(stage: Stage, state: RenderState, keep_analysis: bool) -> RenderState:
    """Aplica una etapa (perezosa: no materializa `image`). La copia de análisis se sigue
    calculando solo si `keep_analysis` (queda alguna op automática más adelante)."""
    first = stage.ops[0]
    fn: Callable[[pyvips.Image, float], pyvips.Image]
    if first.op in tonal.CURVES:
        curve = compose([tonal.CURVES[o.op](o) for o in stage.ops])
        fn = lambda image, _s: apply_tone_curve(image, curve)  # noqa: E731
    elif first.op in color.AUTO:
        stats = state.stats()
        fn = lambda image, _s: color.AUTO[first.op](image, first, stats)  # noqa: E731
    else:
        fn = lambda image, s: apply_op(image, first, s)  # noqa: E731
    image = fn(state.image, state.scale)
    if not keep_analysis or state.analysis is None:
        return RenderState(image, state.scale)
    analysis = fn(state.analysis, state.analysis_scale).copy_memory()
    return RenderState(image, state.scale, analysis, state.analysis_scale)


def apply_plan(img: pyvips.Image, plan: EditPlan, scale: float = 1.0) -> pyvips.Image:
    """Aplica las ops en el orden del plan (las neutras no hacen nada).

    - `scale`: píxeles de `img` por píxel de la imagen original. La preview trabaja sobre un
      proxy (p. ej. 2048 px de una foto de 6000 px → scale ≈ 0.34) y así radios y tamaños en
      píxeles dan el mismo resultado visual que en el export (scale = 1).
    - Las curvas tonales consecutivas se componen en una sola LUT: el resultado es el mismo que
      aplicarlas de a una (salvo error de interpolación < 1e-4), con una sola pasada por píxel.
    - Si hay ops automáticas, se mantiene una copia chica de la imagen (la de analysis.py) que
      pasa por las mismas ops hasta la última automática; cada op automática mide esa copia.
      Así medir no obliga a calcular (y decodificar) la imagen entera una vez por op automática.

    La preview con caché (render/preview.py) recorre las mismas etapas: da los mismos bytes.
    """
    stages = plan_stages(plan)
    ahead = auto_ahead(stages)
    state = start_state(img, scale, ahead[0])
    for i, stage in enumerate(stages):
        state = run_stage(stage, state, keep_analysis=ahead[i + 1])
    return state.image
