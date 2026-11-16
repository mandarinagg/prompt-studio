"""EditPlan del spike #5: catálogo Foto v1 (docs/EDIT_OPERATIONS.md) como modelos Pydantic.

Es un borrador para medir si un LLM local respeta el esquema. El modelo definitivo vive en
`pstudio.schema` (M1); este archivo no se importa desde el paquete.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Amount = Annotated[int, Field(ge=-100, le=100)]
Unit = Annotated[float, Field(ge=0, le=1)]


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Exposure(_Op):
    op: Literal["exposure"]
    ev: Annotated[float, Field(ge=-5, le=5)]


class AutoExposure(_Op):
    op: Literal["auto_exposure"]
    strength: Unit


class Contrast(_Op):
    op: Literal["contrast"]
    amount: Amount


class Highlights(_Op):
    op: Literal["highlights"]
    amount: Amount


class Shadows(_Op):
    op: Literal["shadows"]
    amount: Amount


class Whites(_Op):
    op: Literal["whites"]
    amount: Amount


class Blacks(_Op):
    op: Literal["blacks"]
    amount: Amount


class WhiteBalance(_Op):
    op: Literal["white_balance"]
    temperature_shift: Amount
    tint_shift: Amount


class AutoWhiteBalance(_Op):
    op: Literal["auto_white_balance"]
    method: Literal["gray_world", "white_patch"]


class Saturation(_Op):
    op: Literal["saturation"]
    amount: Amount


class Vibrance(_Op):
    op: Literal["vibrance"]
    amount: Amount


class Crop(_Op):
    op: Literal["crop"]
    aspect_ratio: Literal["1:1", "4:5", "5:4", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"]
    anchor: Literal["center", "subject_or_center", "top", "bottom", "left", "right"]


class Rotate(_Op):
    op: Literal["rotate"]
    degrees: Annotated[float, Field(ge=-180, le=180)]


class Straighten(_Op):
    op: Literal["straighten"]
    degrees: Annotated[float, Field(ge=-45, le=45)]


class Resize(_Op):
    op: Literal["resize"]
    width: Annotated[int, Field(ge=1, le=16384)]
    height: Annotated[int, Field(ge=1, le=16384)]
    fit: Literal["contain", "cover", "exact"]


class Sharpen(_Op):
    op: Literal["sharpen"]
    amount: Annotated[int, Field(ge=0, le=100)]
    radius: Annotated[float, Field(ge=0.5, le=5)]


class Denoise(_Op):
    op: Literal["denoise"]
    strength: Unit


class Vignette(_Op):
    op: Literal["vignette"]
    amount: Amount
    midpoint: Annotated[int, Field(ge=0, le=100)]


Operation = Annotated[
    Exposure | AutoExposure | Contrast | Highlights | Shadows | Whites | Blacks | WhiteBalance
    | AutoWhiteBalance | Saturation | Vibrance | Crop | Rotate | Straighten | Resize | Sharpen
    | Denoise | Vignette,
    Field(discriminator="op"),
]  # fmt: skip


class Unsupported(_Op):
    request: str = Field(description="Parte del pedido que no se puede hacer")
    reason: str
    alternative: str | None


class Export(_Op):
    format: Literal["jpeg", "png", "webp", "tiff"]
    quality: Annotated[int, Field(ge=1, le=100)]


class EditPlan(_Op):
    schema_version: Literal["1.0"]
    # Con 16 el modelo entraba en bucle (resize+crop repetidos hasta el tope) a temperatura 0.
    operations: list[Operation] = Field(max_length=8)
    export: Export | None
    explanation: str = Field(description="Una o dos frases en el idioma del usuario")
    unsupported: list[Unsupported]
    clarification: str | None = Field(description="Pregunta concreta si el pedido es ambiguo")

    @model_validator(mode="after")
    def _unique_ops(self) -> EditPlan:
        # La gramática no puede expresar unicidad: se valida acá y el error alimenta el reintento.
        seen = [o.op for o in self.operations]
        repeated = sorted({op for op in seen if seen.count(op) > 1})
        if repeated:
            raise ValueError(f"cada op puede aparecer una sola vez; repetidas: {repeated}")
        return self


def json_schema() -> dict:
    return EditPlan.model_json_schema()
