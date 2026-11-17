"""Pedido + foto → plan (#48): lo que hace `pstudio plan` y, en M3, la app.

1. Si hay foto, la analiza localmente y arma los descriptores (solo texto: ningún píxel sale
   del equipo, regla 3).
2. Pide el plan al proveedor elegido con el pipeline de provider.py: validación, un reintento
   y, si el proveedor no está o falla, respaldo a las reglas con aviso.

`auto` usa el LLM local si está registrado (el pipeline cae a reglas si no está configurado o
falla) y, si no, las reglas directamente.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pstudio.analysis import analyze
from pstudio.prompting import PROVIDERS, get_provider
from pstudio.prompting.cloud import payload_text
from pstudio.prompting.descriptors import describe
from pstudio.prompting.provider import PlanRequest, PlanResult, make_plan
from pstudio.prompting.rules import RulesProvider
from pstudio.render.io import decode

AUTO_ORDER = ("local_llm", "rules")


def image_descriptors(path: Path) -> dict:
    img, info = decode(path)
    return describe(analyze(img), info.width, info.height)


def resolve_provider(name: str):
    if name == "auto":
        name = next(n for n in AUTO_ORDER if n in PROVIDERS)
    return get_provider(name)


def plan_for(
    prompt: str,
    image: Path | None = None,
    provider: str = "auto",
    before_send: Callable[[str], None] | None = None,
) -> PlanResult:
    """`before_send(texto)`: se llama antes de enviar algo fuera del equipo (proveedor nube),
    con el texto exacto que se va a enviar, para mostrarlo al usuario."""
    descriptors = image_descriptors(image) if image is not None else {}
    request = PlanRequest(prompt, descriptors, asset=image.name if image is not None else None)
    chosen = resolve_provider(provider)
    if chosen.name == "cloud" and before_send is not None and chosen.ready():
        before_send(payload_text(request))
    fallback = None if chosen.name == "rules" else RulesProvider()
    return make_plan(request, chosen, fallback=fallback)
