"""Contrato RPC en JSON Schema: de acá salen los tipos TS de la app (nada se tipa dos veces).

Forma: `{methods: {<nombre>: {params, result}}, events: {<nombre>: payload}}` con todos los
modelos en `$defs`. `app/scripts/gen-types.mjs` lo convierte en `app/src/engine/contract.gen.ts`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

import pstudio.rpc  # noqa: F401  registra los métodos
from pstudio.rpc.server import EVENTS, METHODS

RPC_SCHEMA_FILE = Path(__file__).resolve().parents[3] / "schema" / "rpc-1.schema.json"


def _group(title: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": title,
        "type": "object",
        "properties": props,
        "required": sorted(props),
        "additionalProperties": False,
    }


def rpc_json_schema() -> dict[str, Any]:
    inputs: list[tuple[Any, Any, TypeAdapter]] = []
    for name in sorted(METHODS):
        m = METHODS[name]
        inputs.append(((name, "params"), "validation", TypeAdapter(m.params)))
        inputs.append(((name, "result"), "serialization", m.adapter))
    for name in sorted(EVENTS):
        inputs.append(((name, "event"), "serialization", TypeAdapter(EVENTS[name])))
    schemas, top = TypeAdapter.json_schemas(inputs, ref_template="#/$defs/{model}")

    methods = {}
    for name in sorted(METHODS):
        methods[name] = {
            "type": "object",
            "properties": {
                "params": schemas[((name, "params"), "validation")],
                "result": schemas[((name, "result"), "serialization")],
            },
            "required": ["params", "result"],
            "additionalProperties": False,
        }
    events = {name: schemas[((name, "event"), "serialization")] for name in sorted(EVENTS)}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Rpc",
        "description": "Contrato JSON-RPC 1 entre la app y el engine de PROMPT STUDIO.",
        "type": "object",
        "properties": {"methods": _group("Methods", methods), "events": _group("Events", events)},
        "required": ["events", "methods"],
        "additionalProperties": False,
        "$defs": top.get("$defs", {}),
    }
