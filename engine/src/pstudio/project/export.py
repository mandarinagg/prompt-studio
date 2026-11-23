"""Exportar fotos del proyecto como copias, con su pila de ajustes.

Nunca sobrescribe: si el nombre está ocupado se agrega `_2`, `_3`… Todas las fotos del proyecto
se pasan como protegidas, así un destino mal elegido no puede pisar ningún original.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pyvips

from pstudio.export import EXTENSIONS, Result, apply_file
from pstudio.render.io import Cancelled
from pstudio.schema import Asset, Export, Project
from pstudio.schema.plan import ExportPreset


def _free_stem(out_dir: Path, stem: str) -> Path:
    """Primer `stem`, `stem_2`… sin archivo con ninguna extensión de salida posible.

    La extensión final la decide el preset después de decodificar, así que se reserva el nombre
    para todas.
    """
    candidate, n = stem, 1
    while any((out_dir / f"{candidate}{ext}").exists() for ext in EXTENSIONS.values()):
        n += 1
        candidate = f"{stem}_{n}"
    return out_dir / candidate


ProgressFn = Callable[[int, int, str, float], None]


def export_assets(
    project: Project,
    asset_ids: list[str],
    out_dir: Path,
    preset: ExportPreset = "original",
    *,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> list[Result]:
    protected = tuple(Path(a.path) for a in project.assets)
    assets = [project.asset(i) for i in asset_ids]
    return export_copies(
        assets, out_dir, preset, protected=protected, on_progress=on_progress, cancel=cancel
    )


def export_copies(
    assets: list[Asset],
    out_dir: Path,
    preset: ExportPreset = "original",
    *,
    protected: tuple[Path, ...] = (),
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> list[Result]:
    """Exporta `assets` (con su pila actual) a `out_dir`; un `Result` por foto, en orden.

    `on_progress(índice, total, asset_id, fracción)`: fracción 0 al empezar cada foto, < 1
    durante la escritura y 1 al terminarla (bien o con error). `cancel` se mira antes de cada
    foto y durante la escritura: al cancelar, la foto en curso no deja archivo, las terminadas
    se conservan y el resto vuelve con `cancelled=True`.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(assets)
    results: list[Result] = []

    def report(i: int, asset_id: str, fraction: float) -> None:
        if on_progress is not None:
            on_progress(i, total, asset_id, fraction)

    for i, asset in enumerate(assets):
        source = Path(asset.path)
        if cancel is not None and cancel.is_set():
            results.extend(Result(Path(a.path), cancelled=True) for a in assets[i:])
            break
        report(i, asset.id, 0.0)
        if not source.is_file():
            results.append(Result(source, error=f"falta el archivo {source.name}"))
            report(i, asset.id, 1.0)
            continue

        def monitor(fraction: float, i: int = i, asset_id: str = asset.id) -> bool:
            report(i, asset_id, min(fraction, 0.99))
            return cancel is None or not cancel.is_set()

        dest = _free_stem(out_dir, f"{source.stem}_{preset}")
        try:
            results.append(
                apply_file(
                    asset.stack,
                    source,
                    dest,
                    cli=Export(preset=preset),
                    protected=protected,
                    monitor=monitor,
                )
            )
        except Cancelled:
            results.extend(Result(Path(a.path), cancelled=True) for a in assets[i:])
            break
        except (OSError, ValueError, pyvips.Error) as e:
            results.append(Result(source, error=f"no se pudo exportar {source.name}: {e}"))
        report(i, asset.id, 1.0)
    return results
