"""Contrato de los proveedores de planes y el pipeline que los valida (docs/PROMPT_ENGINE.md).

Un proveedor recibe el pedido del usuario y los descriptores de la imagen (texto/JSON generado
localmente) y propone un plan en JSON. **Nunca** devuelve código: lo que propone se valida con
el esquema Pydantic del EditPlan (solo ops del catálogo, con sus rangos) y lo que no valida se
descarta.

Pipeline (`make_plan`): proveedor → parseo → validación → si falla, un reintento con el error
como feedback → si vuelve a fallar, se usa el proveedor de respaldo (reglas) y se avisa.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from pstudio.ops import implemented
from pstudio.schema import EditPlan


@dataclass(frozen=True)
class PlanRequest:
    prompt: str
    descriptors: dict[str, Any] = field(default_factory=dict)
    asset: str | None = None


@runtime_checkable
class PlanProvider(Protocol):
    name: str

    def propose(self, request: PlanRequest, feedback: str | None = None) -> str | dict:
        """Devuelve el plan como texto JSON o dict. `feedback` = error del intento anterior."""
        ...


class ProviderUnavailable(RuntimeError):
    """El proveedor no se puede usar en este equipo (falta el modelo, sin opt-in, etc.)."""


@dataclass
class PlanResult:
    plan: EditPlan | None
    provider: str  # el que produjo el plan final (o el que falló, si plan es None)
    seconds: float
    attempts: int  # intentos del proveedor principal
    errors: list[str] = field(default_factory=list)  # un error por intento fallido
    fallback_from: str | None = None  # si se cayó a reglas: el proveedor que falló
    warnings: list[str] = field(default_factory=list)

    @property
    def valid_first_try(self) -> bool:
        return self.plan is not None and self.fallback_from is None and self.attempts == 1


def validate(raw: str | dict, request: PlanRequest) -> EditPlan:
    """Parsea y valida lo que propuso un proveedor. Lanza ValueError con un mensaje corto."""
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"no es JSON válido: {e.msg} (línea {e.lineno})") from None
    else:
        data = raw
    if not isinstance(data, dict):
        raise ValueError("el plan debe ser un objeto JSON")
    data = {**data, "source_prompt": request.prompt}
    if request.asset is not None:
        data["asset"] = request.asset
    try:
        plan = EditPlan.model_validate(data)
    except ValidationError as e:
        parts = []
        for err in e.errors()[:5]:
            loc = ".".join(str(x) for x in err["loc"]) or "(plan)"
            parts.append(f"{loc}: {err['msg']}")
        raise ValueError("plan inválido: " + "; ".join(parts)) from None
    missing = sorted({o.op for o in plan.operations} - set(implemented()))
    if missing:
        raise ValueError(f"ops no disponibles en este equipo: {', '.join(missing)}")
    return plan


def make_plan(
    request: PlanRequest,
    provider: PlanProvider,
    *,
    fallback: PlanProvider | None = None,
    retries: int = 1,
) -> PlanResult:
    """Corre el pipeline completo. Sin `fallback`, un fallo devuelve `plan=None`."""
    start = time.perf_counter()
    errors: list[str] = []
    feedback = None
    attempts = 0
    for _ in range(1 + retries):
        attempts += 1
        try:
            plan = validate(provider.propose(request, feedback), request)
            return PlanResult(plan, provider.name, time.perf_counter() - start, attempts, errors)
        except ProviderUnavailable as e:
            errors.append(str(e))
            break
        except ValueError as e:
            errors.append(str(e))
            feedback = str(e)
    if fallback is None:
        return PlanResult(None, provider.name, time.perf_counter() - start, attempts, errors)
    plan = validate(fallback.propose(request), request)
    warning = (
        f"{provider.name} no produjo un plan válido ({errors[-1]}); se usaron las reglas offline"
    )
    return PlanResult(
        plan,
        fallback.name,
        time.perf_counter() - start,
        attempts,
        errors,
        fallback_from=provider.name,
        warnings=[warning],
    )
