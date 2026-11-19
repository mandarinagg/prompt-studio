"""Historial por foto: entradas con la pila completa, cursor, undo/redo y lotes (ADR-0009).

Las funciones mutan el `Asset`/`Project` recibido; guardar en disco es tarea de `store`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pstudio.project.stack import normalize
from pstudio.schema import Asset, EditPlan, HistoryEntry, Project

MAX_ENTRIES = 200


@dataclass
class UndoGroupResult:
    undone: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def push(asset: Asset, stack: EditPlan, label: str, group_id: str | None = None) -> bool:
    """Agrega una entrada con `stack` normalizada. False si no cambia nada."""
    stack = normalize(stack)
    if stack == asset.stack:
        return False
    del asset.history[asset.cursor + 1 :]
    asset.history.append(HistoryEntry(label=label[:200], stack=stack, group_id=group_id))
    if len(asset.history) > MAX_ENTRIES:
        del asset.history[1]  # la entrada 0 ("Original") nunca se poda
    asset.cursor = len(asset.history) - 1
    return True


def undo(asset: Asset) -> bool:
    if asset.cursor == 0:
        return False
    asset.cursor -= 1
    return True


def redo(asset: Asset) -> bool:
    if asset.cursor >= len(asset.history) - 1:
        return False
    asset.cursor += 1
    return True


def jump(asset: Asset, index: int) -> None:
    if not 0 <= index < len(asset.history):
        raise IndexError(f"no existe la entrada {index} del historial")
    asset.cursor = index


def undo_group(project: Project, group_id: str) -> UndoGroupResult:
    """Deshace el lote `group_id` en las fotos donde sigue siendo la entrada actual."""
    result = UndoGroupResult()
    for asset in project.assets:
        if asset.history[asset.cursor].group_id == group_id:
            undo(asset)
            result.undone.append(asset.id)
        elif any(e.group_id == group_id for e in asset.history[: asset.cursor]):
            result.skipped.append(asset.id)
    return result
