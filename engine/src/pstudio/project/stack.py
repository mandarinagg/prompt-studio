"""Pila de ajustes de una foto: un `EditPlan` con una op por tipo, en orden canónico.

El orden no depende del historial: cada slider corresponde a un único valor y el resultado es
el mismo sin importar en qué orden se tocaron los ajustes (ADR-0009, EDIT_OPERATIONS.md).
Un plan del prompt se *fusiona* sobre la pila: los valores relativos se suman y se recortan al
rango del esquema; la geometría y las ops automáticas reemplazan.
"""

from __future__ import annotations

from dataclasses import dataclass

import annotated_types

from pstudio.schema import EditPlan, Operation
from pstudio.schema.plan import Resize

CANONICAL_ORDER: tuple[str, ...] = (
    "straighten",
    "rotate",
    "crop",
    "denoise",
    "auto_white_balance",
    "white_balance",
    "auto_exposure",
    "exposure",
    "contrast",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "saturation",
    "vibrance",
    "sharpen",
    "vignette",
)
_RANK = {name: i for i, name in enumerate(CANONICAL_ORDER)}

_AMOUNT = frozenset({"amount"})
ADDITIVE: dict[str, frozenset[str]] = {
    "exposure": frozenset({"ev"}),
    "contrast": _AMOUNT,
    "highlights": _AMOUNT,
    "shadows": _AMOUNT,
    "whites": _AMOUNT,
    "blacks": _AMOUNT,
    "saturation": _AMOUNT,
    "vibrance": _AMOUNT,
    "white_balance": frozenset({"temperature_shift", "tint_shift"}),
    "vignette": _AMOUNT,
    "sharpen": _AMOUNT,
    "denoise": frozenset({"strength"}),
}


@dataclass(frozen=True)
class MergeResult:
    stack: EditPlan
    export_hint: Resize | None = None


def normalize(stack: EditPlan) -> EditPlan:
    """En orden canónico, sin no-ops ni `resize` (EditPlan ya garantiza una op por tipo)."""
    by_name = {op.op: op for op in stack.operations if op.op in _RANK}
    ops = [by_name[n] for n in CANONICAL_ORDER if n in by_name and not by_name[n].is_noop()]
    return EditPlan(operations=ops)


def _bounds(op: Operation, field: str) -> tuple[float | None, float | None]:
    lo = hi = None
    for meta in type(op).model_fields[field].metadata:
        if isinstance(meta, annotated_types.Ge):
            lo = meta.ge
        elif isinstance(meta, annotated_types.Le):
            hi = meta.le
    return lo, hi


def _add(current: Operation, delta: Operation) -> Operation:
    """Suma los campos relativos; el resto se conserva salvo que el plan lo indique."""
    values = current.model_dump()
    values.update(delta.model_dump(include=delta.model_fields_set))
    for field in ADDITIVE[current.op]:
        total = getattr(current, field) + getattr(delta, field)
        if isinstance(total, float):
            total = round(total, 4)  # 0.1 + 0.2 - 0.3 tiene que dar 0 (no-op), no 5e-17
        lo, hi = _bounds(current, field)
        if lo is not None:
            total = max(lo, total)
        if hi is not None:
            total = min(hi, total)
        values[field] = total
    return type(current).model_validate(values)


def merge(stack: EditPlan, plan: EditPlan) -> MergeResult:
    """Fusiona `plan` sobre `stack`. `resize` no entra a la pila: vuelve como `export_hint`."""
    by_name: dict[str, Operation] = {op.op: op for op in normalize(stack).operations}
    hint: Resize | None = None
    for op in plan.operations:
        if isinstance(op, Resize):
            hint = op
            continue
        current = by_name.get(op.op)
        by_name[op.op] = _add(current, op) if current and op.op in ADDITIVE else op
    return MergeResult(normalize(EditPlan(operations=list(by_name.values()))), hint)
