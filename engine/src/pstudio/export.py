"""Exportación (#14): presets, aplicar un plan a un archivo y modo lote.

Siempre se escribe una **copia**. Las entradas se pasan como protegidas a `encode`, que se
niega a escribir encima de un original (también si es el mismo archivo por otro camino o un
hardlink) y verifica después que el hash del original no cambió.

Precedencia de cada ajuste de salida (formato, calidad, color, metadatos):
    opciones de la CLI  >  `export` del plan  >  preset  >  la fuente.
El preset sale de la CLI, si no del plan, y si no es `original`. Ver docs/EXPORT_PRESETS.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import pyvips

from pstudio.ops import apply_plan
from pstudio.ops.geometry import output_size, resize
from pstudio.render.io import (
    SUFFIXES,
    OriginalProtectedError,
    SourceInfo,
    decode,
    encode,
)
from pstudio.schema import EditPlan, Export
from pstudio.schema.plan import Resize

Format = Literal["jpeg", "png", "webp", "tiff"]
EXTENSIONS: dict[str, str] = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "tiff": ".tif"}


@dataclass(frozen=True)
class Box:
    """Tamaño de salida de un preset. `long_side`: solo achica. `width`×`height`: cover."""

    long_side: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class Preset:
    format: Format | None  # None = el de la fuente
    quality: int
    color_space: Literal["sRGB", "Display P3"] | None  # None = según la fuente (P3 si es P3)
    metadata: Literal["keep", "strip", "strip_gps"]
    box: Box | None = None


PRESETS: dict[str, Preset] = {
    "original": Preset(format=None, quality=100, color_space=None, metadata="keep"),
    # TIFF 16 bits si la fuente es de 16 bits; si no, JPEG 95 (ver resolve()).
    "high_quality": Preset(format=None, quality=95, color_space=None, metadata="keep"),
    "web": Preset("webp", 85, "sRGB", "strip_gps", Box(long_side=2048)),
    "catalog_square": Preset("jpeg", 90, "sRGB", "strip", Box(width=1080, height=1080)),
    "social_vertical": Preset("jpeg", 90, "sRGB", "strip", Box(width=1080, height=1350)),
    "story_9x16": Preset("jpeg", 90, "sRGB", "strip", Box(width=1080, height=1920)),
}


@dataclass(frozen=True)
class Settings:
    preset: str
    format: Format
    quality: int
    color_space: Literal["sRGB", "Display P3"]
    metadata: Literal["keep", "strip", "strip_gps"]
    depth: Literal[8, 16]
    box: Box | None


def _is_wide_gamut(info: SourceInfo) -> bool:
    return "P3" in info.profile


def resolve(info: SourceInfo, plan_export: Export | None, cli: Export | None) -> Settings:
    """Combina CLI > plan > preset > fuente en los ajustes finales de un archivo."""
    layers = [x for x in (cli, plan_export) if x is not None]

    def pick(name: str):
        for layer in layers:
            value = getattr(layer, name)
            if value is not None:
                return value
        return None

    preset_name = pick("preset") or "original"
    preset = PRESETS[preset_name]
    fmt = pick("format") or preset.format
    if fmt is None:
        if preset_name == "high_quality":
            fmt = "tiff" if info.bit_depth == 16 else "jpeg"
        else:
            fmt = info.format
    quality = pick("quality") or preset.quality
    color = pick("color_space") or preset.color_space
    if color is None:
        color = "Display P3" if _is_wide_gamut(info) else "sRGB"
    metadata = pick("metadata") or preset.metadata
    depth = 16 if fmt in ("png", "tiff") and info.bit_depth == 16 else 8
    return Settings(preset_name, fmt, quality, color, metadata, depth, preset.box)


def fit_box(img: pyvips.Image, box: Box | None) -> pyvips.Image:
    if box is None:
        return img
    if box.long_side is not None:
        if max(img.width, img.height) <= box.long_side:
            return img
        side = box.long_side
        return resize(img, Resize(op="resize", width=side, height=side, fit="contain"))
    return resize(img, Resize(op="resize", width=box.width, height=box.height, fit="cover"))


# Margen al achicar antes del plan: se procesa a 1.25× el tamaño final y el último paso es un
# Lanczos al tamaño exacto, para no perder nitidez por remuestrear dos veces al límite.
PRESHRINK_MARGIN = 1.25
PRESHRINK_MAX = 0.8  # si habría que achicar menos que esto, no vale la pena: se procesa entero


def preshrink_scale(width: int, height: int, plan: EditPlan, box: Box | None) -> float:
    """Factor (≤ 1) al que se puede reducir la fuente antes de aplicar el plan cuando el
    preset achica la salida. El plan se aplica con `scale` = ese factor (radios y tamaños se
    ajustan igual que en la preview), así que el resultado equivale a procesar entero y
    reducir al final, pero sin calcular millones de píxeles que se van a descartar."""
    if box is None:
        return 1.0
    fw, fh = output_size(width, height, plan.operations)
    if box.long_side is not None:
        need = min(box.long_side, max(fw, fh)) / max(fw, fh)
    else:
        need = max(box.width / fw, box.height / fh)
    k = need * PRESHRINK_MARGIN
    return k if k < PRESHRINK_MAX else 1.0


# ------------------------------------------------------------------ un archivo
@dataclass
class Result:
    source: Path
    dest: Path | None = None
    seconds: float = 0.0
    error: str | None = None
    settings: Settings | None = None


def apply_file(
    plan: EditPlan,
    source: Path,
    dest: Path,
    *,
    cli: Export | None = None,
    protected: tuple[Path, ...] = (),
    overwrite: bool = False,
) -> Result:
    """Decodifica `source`, aplica el plan, ajusta al preset y guarda la copia en `dest`.

    La extensión de `dest` se reemplaza por la del formato resuelto.
    """
    start = time.perf_counter()
    img, info = decode(source)
    settings = resolve(info, plan.export, cli)
    scale = preshrink_scale(img.width, img.height, plan, settings.box)
    if scale < 1.0:
        img = img.resize(scale, kernel="lanczos3")
    out = fit_box(apply_plan(img, plan, scale=scale), settings.box)
    final = encode(
        out,
        dest.with_suffix(EXTENSIONS[settings.format]),
        source=info,
        protected=protected,
        quality=settings.quality,
        color_space=settings.color_space,
        depth=settings.depth,
        metadata=settings.metadata,
        overwrite=overwrite,
    )
    return Result(source, final, time.perf_counter() - start, settings=settings)


# ------------------------------------------------------------------ lote
@dataclass
class Job:
    source: Path
    dest: Path  # sin la extensión final (la decide el formato)


@dataclass
class Batch:
    jobs: list[Job] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)  # archivos que no son imágenes soportadas


def collect(inputs: list[Path], out_dir: Path, *, recursive: bool = False) -> Batch:
    """Arma la lista de trabajos. Las carpetas aportan sus imágenes (en orden alfabético) y
    mantienen la estructura de subcarpetas en la salida si `recursive`."""
    batch = Batch()
    for item in inputs:
        if item.is_dir():
            pattern = "**/*" if recursive else "*"
            for f in sorted(item.glob(pattern)):
                if not f.is_file() or f.name.startswith("."):
                    continue
                if f.suffix.lower() not in SUFFIXES:
                    batch.skipped.append(f)
                    continue
                rel = f.relative_to(item).with_suffix("")
                batch.jobs.append(Job(f, out_dir / rel))
        else:
            batch.jobs.append(Job(item, out_dir / item.stem))

    # Dos entradas con el mismo nombre (foto.jpg y foto.png) irían al mismo destino: se
    # distinguen agregando la extensión original (foto_png.jpg).
    seen: dict[Path, int] = {}
    for job in batch.jobs:
        key = job.dest.resolve()
        seen[key] = seen.get(key, 0) + 1
    for i, job in enumerate(batch.jobs):
        if seen[job.dest.resolve()] > 1:
            ext = job.source.suffix.lstrip(".").lower()
            batch.jobs[i] = replace(job, dest=job.dest.with_name(f"{job.dest.name}_{ext}"))
    return batch


def run_batch(
    plan: EditPlan,
    batch: Batch,
    *,
    cli: Export | None = None,
    overwrite: bool = False,
    on_result=None,
) -> list[Result]:
    """Procesa todos los trabajos; un error en un archivo no frena el resto.

    La excepción es OriginalModifiedError (un original cambió durante el export): corta todo,
    porque algo externo está tocando los originales.
    """
    protected = tuple(job.source for job in batch.jobs)
    results = []
    for job in batch.jobs:
        start = time.perf_counter()
        try:
            r = apply_file(
                plan, job.source, job.dest, cli=cli, protected=protected, overwrite=overwrite
            )
        except (OSError, ValueError, pyvips.Error, OriginalProtectedError) as e:
            r = Result(job.source, seconds=time.perf_counter() - start, error=str(e))
        results.append(r)
        if on_result is not None:
            on_result(r)
    return results
