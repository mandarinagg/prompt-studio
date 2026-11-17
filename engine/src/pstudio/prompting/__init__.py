"""Motor de prompts: pedido en lenguaje natural → EditPlan validado (docs/PROMPT_ENGINE.md).

Los proveedores solo proponen JSON; el plan final siempre pasa por la validación del esquema
(solo ops del catálogo). Ningún proveedor produce código (regla 1 de CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import Callable

from pstudio.prompting.provider import (
    PlanProvider,
    PlanRequest,
    PlanResult,
    ProviderUnavailable,
    make_plan,
    validate,
)

# nombre → fábrica. Los proveedores se registran a medida que existen (#15, #17, #18).
PROVIDERS: dict[str, Callable[[], PlanProvider]] = {}


def get_provider(name: str) -> PlanProvider:
    factory = PROVIDERS.get(name)
    if factory is None:
        available = ", ".join(sorted(PROVIDERS)) or "ninguno todavía"
        raise ProviderUnavailable(f"proveedor {name!r} no disponible (hay: {available})")
    return factory()


__all__ = [
    "PROVIDERS",
    "PlanProvider",
    "PlanRequest",
    "PlanResult",
    "ProviderUnavailable",
    "get_provider",
    "make_plan",
    "validate",
]
