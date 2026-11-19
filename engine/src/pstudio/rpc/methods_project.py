"""`project.*` y `asset.*`: proyecto, pila de ajustes e historial (ADR-0009).

Los resúmenes de fotos no llevan rutas absolutas: la UI muestra el nombre del archivo y pide
la preview o la miniatura por id. Las únicas rutas que salen son las del proyecto y su caché.
Todo método que cambia algo guarda al terminar (`Session.commit`).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pstudio.project import history
from pstudio.project.stack import merge
from pstudio.project.store import add_assets, create, relink
from pstudio.rpc.server import ENGINE_ERROR, INVALID_PARAMS, Params, RpcError, method
from pstudio.rpc.session import Session
from pstudio.schema import Asset, EditPlan
from pstudio.schema.plan import Resize


# ------------------------------------------------------------------------------------- modelos
class AssetSummary(BaseModel):
    id: str
    file: str
    edited: bool
    missing: bool


class ProjectInfo(BaseModel):
    path: str
    name: str
    cache_dir: str
    assets: list[AssetSummary]


class ImportResult(BaseModel):
    added: list[AssetSummary]
    duplicates: int
    unsupported: list[str]


class StackState(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    asset: str
    stack: EditPlan
    cursor: int
    label: str  # etiqueta de la entrada actual del historial
    can_undo: bool
    can_redo: bool
    changed: bool  # si esta llamada cambió la pila
    export_hint: Resize | None = None  # el plan pedía resize: va al export, no a la pila


class HistoryItem(BaseModel):
    label: str
    group_id: str | None
    at: datetime


class History(BaseModel):
    cursor: int
    entries: list[HistoryItem]


class UndoGroupResult(BaseModel):
    undone: list[str]
    skipped: list[str]


class CreateParams(Params):
    dir: str = Field(min_length=1)  # vacío sería la carpeta de trabajo del engine
    name: str


class OpenParams(Params):
    path: str


class ImportParams(Params):
    paths: list[str] = Field(min_length=1)
    recursive: bool = False


class AssetParams(Params):
    asset: str


class RelinkParams(AssetParams):
    path: str


class SetStackParams(AssetParams):
    stack: EditPlan
    label: str = Field(min_length=1, max_length=200)
    group_id: str | None = None


class ApplyPlanParams(AssetParams):
    plan: EditPlan
    label: str | None = Field(default=None, min_length=1, max_length=200)
    group_id: str | None = None


class JumpParams(AssetParams):
    index: int


class GroupParams(Params):
    group_id: str


# ------------------------------------------------------------------------------------- helpers
def summary(asset: Asset) -> AssetSummary:
    return AssetSummary(
        id=asset.id,
        file=Path(asset.path).name,
        edited=bool(asset.stack.operations),
        missing=not Path(asset.path).is_file(),
    )


def _info(s: Session) -> ProjectInfo:
    project = s.require()
    return ProjectInfo(
        path=str(s.require_path()),
        name=project.name,
        cache_dir=str(s.cache_dir),
        assets=[summary(a) for a in project.assets],
    )


def _state(asset: Asset, changed: bool, hint: Resize | None = None) -> StackState:
    return StackState(
        asset=asset.id,
        stack=asset.stack,
        cursor=asset.cursor,
        label=asset.history[asset.cursor].label,
        can_undo=asset.cursor > 0,
        can_redo=asset.cursor < len(asset.history) - 1,
        changed=changed,
        export_hint=hint,
    )


def _push(s: Session, asset: Asset, stack: EditPlan, label: str, group: str | None) -> bool:
    changed = history.push(asset, stack, label, group)
    if changed:
        s.commit()
    return changed


# ------------------------------------------------------------------------------------- project
@method("project.create")
def project_create(s: Session, p: CreateParams) -> ProjectInfo:
    folder = Path(p.dir)
    if not folder.is_dir():
        raise RpcError(ENGINE_ERROR, f"no existe la carpeta {folder.name}")
    s.open(create(folder, p.name))
    return _info(s)


@method("project.open")
def project_open(s: Session, p: OpenParams) -> ProjectInfo:
    s.open(Path(p.path))
    return _info(s)


@method("project.info")
def project_info(s: Session) -> ProjectInfo:
    return _info(s)


@method("project.import")
def project_import(s: Session, p: ImportParams) -> ImportResult:
    project = s.require()
    r = add_assets(project, [Path(x) for x in p.paths], recursive=p.recursive)
    if r.added:
        s.commit()
    return ImportResult(
        added=[summary(project.asset(i)) for i in r.added],
        duplicates=len(r.duplicates),
        unsupported=[f.name for f in r.unsupported],
    )


@method("project.relink")
def project_relink(s: Session, p: RelinkParams) -> AssetSummary:
    s.asset(p.asset)  # error claro si no existe
    relink(s.require(), p.asset, Path(p.path))
    s.commit()
    return summary(s.asset(p.asset))


# ------------------------------------------------------------------------------------- asset
@method("asset.state")
def asset_state(s: Session, p: AssetParams) -> StackState:
    return _state(s.asset(p.asset), changed=False)


@method("asset.history")
def asset_history(s: Session, p: AssetParams) -> History:
    asset = s.asset(p.asset)
    return History(
        cursor=asset.cursor,
        entries=[HistoryItem(label=e.label, group_id=e.group_id, at=e.at) for e in asset.history],
    )


@method("asset.set_stack")
def asset_set_stack(s: Session, p: SetStackParams) -> StackState:
    asset = s.asset(p.asset)
    return _state(asset, _push(s, asset, p.stack, p.label, p.group_id))


@method("asset.apply_plan")
def asset_apply_plan(s: Session, p: ApplyPlanParams) -> StackState:
    asset = s.asset(p.asset)
    merged = merge(asset.stack, p.plan)
    label = p.label or (
        f"Pedido: {p.plan.source_prompt}" if p.plan.source_prompt else "Plan aplicado"
    )
    changed = _push(s, asset, merged.stack, label[:200], p.group_id)
    return _state(asset, changed, merged.export_hint)


def _step(s: Session, asset_id: str, fn) -> StackState:
    asset = s.asset(asset_id)
    changed = fn(asset)
    if changed:
        s.commit()
    return _state(asset, changed)


@method("asset.undo")
def asset_undo(s: Session, p: AssetParams) -> StackState:
    return _step(s, p.asset, history.undo)


@method("asset.redo")
def asset_redo(s: Session, p: AssetParams) -> StackState:
    return _step(s, p.asset, history.redo)


@method("asset.jump")
def asset_jump(s: Session, p: JumpParams) -> StackState:
    asset = s.asset(p.asset)
    if not 0 <= p.index < len(asset.history):
        raise RpcError(INVALID_PARAMS, f"index fuera del historial (0..{len(asset.history) - 1})")
    changed = p.index != asset.cursor
    history.jump(asset, p.index)
    if changed:
        s.commit()
    return _state(asset, changed)


@method("asset.reset")
def asset_reset(s: Session, p: AssetParams) -> StackState:
    asset = s.asset(p.asset)
    return _state(asset, _push(s, asset, EditPlan(), "Restablecer", None))


@method("asset.undo_group")
def asset_undo_group(s: Session, p: GroupParams) -> UndoGroupResult:
    r = history.undo_group(s.require(), p.group_id)
    if r.undone:
        s.commit()
    return UndoGroupResult(undone=r.undone, skipped=r.skipped)
