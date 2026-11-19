"""Proyecto v1: fotos referenciadas, su pila de ajustes y su historial (ADR-0009).

Fuente única del formato de `project.json`. La pila de cada foto es un `EditPlan` normalizado
(ver `pstudio.project.stack`); el historial guarda una copia completa de la pila por entrada.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pstudio.schema.plan import EditPlan

PROJECT_SCHEMA_VERSION = "1.0"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _now() -> datetime:
    return datetime.now(UTC)


class HistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(max_length=200)
    stack: EditPlan
    group_id: str | None = Field(None, max_length=64)
    at: datetime = Field(default_factory=_now)


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=False)

    # Se usa en nombres de archivo de la caché: nunca puede ser una ruta.
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    path: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: Sha256
    imported_at: datetime = Field(default_factory=_now)
    history: list[HistoryEntry] = Field(min_length=1)
    cursor: int = 0

    @model_validator(mode="after")
    def _cursor_in_range(self) -> Self:
        if not 0 <= self.cursor < len(self.history):
            raise ValueError("cursor fuera del historial")
        return self

    @property
    def stack(self) -> EditPlan:
        return self.history[self.cursor].stack

    @classmethod
    def new(cls, id: str, path: str, size: int, sha256: str) -> Asset:
        return cls(
            id=id,
            path=path,
            size=size,
            sha256=sha256,
            history=[HistoryEntry(label="Original", stack=EditPlan())],
        )


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = PROJECT_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=100)
    created_at: datetime = Field(default_factory=_now)
    assets: list[Asset] = Field(default_factory=list)
    export_dir: str | None = None

    def asset(self, asset_id: str) -> Asset:
        for a in self.assets:
            if a.id == asset_id:
                return a
        raise KeyError(f"no existe la foto {asset_id}")


def project_json_schema() -> dict[str, Any]:
    return Project.model_json_schema()
