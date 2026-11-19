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
from pstudio.schema.project import (
    PROJECT_SCHEMA_VERSION,
    Asset,
    HistoryEntry,
    Project,
    project_json_schema,
)

__all__ = [
    "PROJECT_SCHEMA_VERSION",
    "Asset",
    "HistoryEntry",
    "Project",
    "project_json_schema",
    "OP_NAMES",
    "SCHEMA_VERSION",
    "EditPlan",
    "Export",
    "Operation",
    "Unsupported",
    "json_schema",
]
