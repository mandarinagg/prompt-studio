"""Esquema del engine: modelos Pydantic como fuente única → JSON Schema → tipos TS."""

from pstudio.schema.plan import (
    OP_NAMES,
    SCHEMA_VERSION,
    EditPlan,
    Export,
    Operation,
    Unsupported,
    json_schema,
)

__all__ = [
    "OP_NAMES",
    "SCHEMA_VERSION",
    "EditPlan",
    "Export",
    "Operation",
    "Unsupported",
    "json_schema",
]
