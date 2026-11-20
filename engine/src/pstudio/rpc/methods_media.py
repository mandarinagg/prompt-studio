"""`plan.create`, `preview.render` y `thumbnail.get`."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pyvips
from pydantic import BaseModel, Field

from pstudio.project.stack import merge
from pstudio.rpc.media import MissingFile, PreviewImage
from pstudio.rpc.server import ENGINE_ERROR, Params, RpcError, method
from pstudio.rpc.session import Session
from pstudio.schema import EditPlan
from pstudio.schema.plan import Resize


class PlanParams(Params):
    prompt: str = Field(min_length=1, max_length=2000)
    asset: str | None = None
    # `cloud` no se ofrece por RPC hasta que la app pida el consentimiento (#64).
    provider: Literal["auto", "rules", "local_llm"] = "auto"


class PlanCreated(BaseModel):
    plan: EditPlan | None
    provider: str
    ms: float
    warnings: list[str]
    errors: list[str]
    draft: EditPlan | None  # pila actual ⊕ plan: lo que se ve antes de "Aplicar"
    export_hint: Resize | None


class PreviewParams(Params):
    asset: str
    stack: EditPlan | None = None  # sin `stack`: la pila guardada de la foto
    long_side: int = Field(default=2048, ge=256, le=2048)


class ThumbParams(Params):
    asset: str


class Thumbnail(BaseModel):
    asset: str
    path: str | None  # None: se está generando; llega por `thumbnail.ready`


def _missing(e: MissingFile) -> RpcError:
    return RpcError(ENGINE_ERROR, str(e))


@method("plan.create")
def plan_create(s: Session, p: PlanParams) -> PlanCreated:
    from pstudio.prompting import ProviderUnavailable
    from pstudio.prompting.planner import plan_for

    asset = s.asset(p.asset) if p.asset is not None else None
    image, descriptors = None, None
    try:
        if asset is not None:
            image = Path(asset.path)
            descriptors = s.media.descriptors(asset)
        r = plan_for(p.prompt, image, p.provider, descriptors=descriptors)
    except MissingFile as e:
        raise _missing(e) from e
    except ProviderUnavailable as e:
        raise RpcError(ENGINE_ERROR, str(e)) from e
    except (ValueError, pyvips.Error) as e:
        raise RpcError(
            ENGINE_ERROR, f"no se pudo analizar {image.name if image else 'la foto'}"
        ) from e
    draft, hint = None, None
    if r.plan is not None:
        if asset is not None:
            merged = merge(asset.stack, r.plan)
            draft, hint = merged.stack, merged.export_hint
        else:
            hint = next((op for op in r.plan.operations if isinstance(op, Resize)), None)
    return PlanCreated(
        plan=r.plan,
        provider=r.provider,
        ms=round(r.seconds * 1000, 2),
        warnings=r.warnings,
        errors=r.errors,
        draft=draft,
        export_hint=hint,
    )


class DraftParams(Params):
    asset: str
    plan: EditPlan
    stack: EditPlan | None = None  # sin `stack`: la pila guardada (con: la que se arrastra)


class PlanDraft(BaseModel):
    draft: EditPlan  # pila ⊕ plan
    export_hint: Resize | None


@method("plan.draft")
def plan_draft(s: Session, p: DraftParams) -> PlanDraft:
    """Recalcula el borrador cuando cambian las casillas, los valores o la pila. No guarda nada."""
    asset = s.asset(p.asset)
    merged = merge(p.stack if p.stack is not None else asset.stack, p.plan)
    return PlanDraft(draft=merged.stack, export_hint=merged.export_hint)


@method("preview.render")
def preview_render(s: Session, p: PreviewParams) -> PreviewImage:
    asset = s.asset(p.asset)
    stack = p.stack if p.stack is not None else asset.stack
    try:
        return s.media.preview(s.cache_dir, asset, stack, p.long_side)
    except MissingFile as e:
        raise _missing(e) from e


@method("thumbnail.get")
def thumbnail_get(s: Session, p: ThumbParams) -> Thumbnail:
    asset = s.asset(p.asset)
    path = s.media.thumbnail(s.cache_dir, asset)
    return Thumbnail(asset=asset.id, path=str(path) if path else None)
