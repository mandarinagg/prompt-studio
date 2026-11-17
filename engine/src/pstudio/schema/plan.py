"""EditPlan v1: catálogo cerrado de operaciones de foto (docs/EDIT_OPERATIONS.md).

Fuente única del esquema (ARCHITECTURE.md): de acá sale el JSON Schema (`pstudio schema`), que
usan la app (tipos TS) y los proveedores de plan. Cada op tiene parámetros acotados y, cuando
corresponde, un valor neutro (no-op) que es su valor por defecto.

Regla no negociable: no hay ops genéricas ni campos que lleven código. `extra="forbid"` en
todos los modelos hace que un campo desconocido sea un error, no algo que se ignora.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

Amount = Annotated[int, Field(ge=-100, le=100, description="-100…100; 0 = sin cambio")]
Unit = Annotated[float, Field(ge=0, le=1)]
AspectRatio = Literal["1:1", "4:5", "5:4", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"]
Anchor = Literal["center", "subject_or_center", "top", "bottom", "left", "right"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Op(_Model):
    def is_noop(self) -> bool:
        """True si la op no cambia la imagen (todos sus parámetros en el valor neutro)."""
        return False


class _AmountOp(_Op):
    amount: Amount = 0

    def is_noop(self) -> bool:
        return self.amount == 0


# --------------------------------------------------------------------------------- tonales
class Exposure(_Op):
    op: Literal["exposure"]
    ev: Annotated[float, Field(ge=-5, le=5, description="Pasos de exposición (EV)")] = 0

    def is_noop(self) -> bool:
        return self.ev == 0


class AutoExposure(_Op):
    op: Literal["auto_exposure"]
    strength: Unit = 1.0

    def is_noop(self) -> bool:
        return self.strength == 0


class Contrast(_AmountOp):
    op: Literal["contrast"]


class Highlights(_AmountOp):
    op: Literal["highlights"]


class Shadows(_AmountOp):
    op: Literal["shadows"]


class Whites(_AmountOp):
    op: Literal["whites"]


class Blacks(_AmountOp):
    op: Literal["blacks"]


# ----------------------------------------------------------------------------------- color
class WhiteBalance(_Op):
    op: Literal["white_balance"]
    temperature_shift: Amount = Field(0, description="Negativo = más frío (azul)")
    tint_shift: Amount = Field(0, description="Negativo = más verde, positivo = más magenta")

    def is_noop(self) -> bool:
        return self.temperature_shift == 0 and self.tint_shift == 0


class AutoWhiteBalance(_Op):
    op: Literal["auto_white_balance"]
    method: Literal["gray_world", "white_patch"] = "gray_world"


class Saturation(_AmountOp):
    op: Literal["saturation"]


class Vibrance(_AmountOp):
    op: Literal["vibrance"]


# ------------------------------------------------------------------------------ geometría
class Rect(_Model):
    """Rectángulo en fracciones de la imagen (0…1), con origen arriba a la izquierda."""

    x: Unit
    y: Unit
    width: Annotated[float, Field(gt=0, le=1)]
    height: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def _inside(self) -> Self:
        if self.x + self.width > 1 + 1e-9 or self.y + self.height > 1 + 1e-9:
            raise ValueError("el rectángulo se sale de la imagen")
        return self


class Crop(_Op):
    op: Literal["crop"]
    aspect_ratio: AspectRatio | None = None
    rect: Rect | None = None
    anchor: Anchor = "center"

    @model_validator(mode="after")
    def _one_mode(self) -> Self:
        if (self.aspect_ratio is None) == (self.rect is None):
            raise ValueError("crop necesita exactamente uno de aspect_ratio o rect")
        return self


class Rotate(_Op):
    op: Literal["rotate"]
    degrees: Annotated[float, Field(ge=-180, le=180, description="Positivo = horario")] = 0

    def is_noop(self) -> bool:
        return self.degrees == 0


class Straighten(_Op):
    op: Literal["straighten"]
    degrees: Annotated[float, Field(ge=-45, le=45)] = 0

    def is_noop(self) -> bool:
        return self.degrees == 0


class Resize(_Op):
    op: Literal["resize"]
    width: Annotated[int, Field(ge=1, le=16384)] | None = None
    height: Annotated[int, Field(ge=1, le=16384)] | None = None
    fit: Literal["contain", "cover", "exact"] = Field(
        "contain",
        description="contain: entra en la caja; cover: la cubre y recorta; exact: deforma",
    )

    @model_validator(mode="after")
    def _some_size(self) -> Self:
        if self.width is None and self.height is None:
            raise ValueError("resize necesita width, height o ambos")
        if self.fit != "contain" and (self.width is None or self.height is None):
            raise ValueError(f"fit={self.fit!r} necesita width y height")
        return self


# --------------------------------------------------------------------------------- detalle
class Sharpen(_Op):
    op: Literal["sharpen"]
    amount: Annotated[int, Field(ge=0, le=100)] = 0
    radius: Annotated[float, Field(ge=0.5, le=5)] = 1.0

    def is_noop(self) -> bool:
        return self.amount == 0


class Denoise(_Op):
    op: Literal["denoise"]
    strength: Unit = 0

    def is_noop(self) -> bool:
        return self.strength == 0


class Vignette(_Op):
    op: Literal["vignette"]
    amount: Amount = Field(0, description="Negativo = oscurece los bordes")
    midpoint: Annotated[int, Field(ge=0, le=100)] = 50

    def is_noop(self) -> bool:
        return self.amount == 0


Operation = Annotated[
    Exposure | AutoExposure | Contrast | Highlights | Shadows | Whites | Blacks | WhiteBalance
    | AutoWhiteBalance | Saturation | Vibrance | Crop | Rotate | Straighten | Resize | Sharpen
    | Denoise | Vignette,
    Field(discriminator="op"),
]  # fmt: skip

OP_TYPES: tuple[type[_Op], ...] = get_args(get_args(Operation)[0])
OP_NAMES: tuple[str, ...] = tuple(get_args(t.model_fields["op"].annotation)[0] for t in OP_TYPES)


# ---------------------------------------------------------------------------------- export
ExportPreset = Literal[
    "original", "high_quality", "web", "catalog_square", "social_vertical", "story_9x16"
]


class Export(_Model):
    """Lo que no se indica sale del preset (docs/EXPORT_PRESETS.md) o de la fuente."""

    preset: ExportPreset | None = None
    format: Literal["jpeg", "png", "webp", "tiff"] | None = None
    quality: Annotated[int, Field(ge=1, le=100)] | None = None
    color_space: Literal["sRGB", "Display P3"] | None = None
    metadata: Literal["keep", "strip", "strip_gps"] | None = None


# ------------------------------------------------------------------------------------ plan
class Unsupported(_Model):
    request: str = Field(max_length=500, description="Parte del pedido que no se puede hacer")
    reason: str = Field(max_length=500)
    alternative: str | None = Field(None, max_length=500)


class EditPlan(_Model):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    asset: str | None = Field(None, max_length=200, description="Id del asset en el proyecto")
    source_prompt: str | None = Field(None, max_length=2000)
    operations: list[Operation] = Field(default_factory=list)
    export: Export | None = None
    explanation: str | None = Field(None, max_length=2000)
    unsupported: list[Unsupported] = Field(default_factory=list)
    clarification: str | None = Field(None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def _empty_clarification(cls, data: object) -> object:
        # Los LLM devuelven "" en lugar de null (spike #5): se normaliza.
        if isinstance(data, dict) and data.get("clarification") == "":
            data = {**data, "clarification": None}
        return data

    @model_validator(mode="after")
    def _unique_ops(self) -> Self:
        # Cada op una sola vez: corta los bucles del LLM (spike #5) y deja un orden sin ambigüedad.
        names = [o.op for o in self.operations]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(f"cada op puede aparecer una sola vez; repetidas: {repeated}")
        return self


def json_schema() -> dict:
    """JSON Schema del EditPlan, en modo validación (lo que se acepta como entrada)."""
    schema = EditPlan.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema
