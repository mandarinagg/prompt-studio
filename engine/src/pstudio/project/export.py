"""Exportar fotos del proyecto como copias, con su pila de ajustes.

Nunca sobrescribe: si el nombre está ocupado se agrega `_2`, `_3`… Todas las fotos del proyecto
se pasan como protegidas, así un destino mal elegido no puede pisar ningún original.
"""

from __future__ import annotations

from pathlib import Path

import pyvips

from pstudio.export import EXTENSIONS, Result, apply_file
from pstudio.schema import Export, Project
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


def export_assets(
    project: Project,
    asset_ids: list[str],
    out_dir: Path,
    preset: ExportPreset = "original",
) -> list[Result]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    protected = tuple(Path(a.path) for a in project.assets)
    results: list[Result] = []
    for asset_id in asset_ids:
        asset = project.asset(asset_id)
        source = Path(asset.path)
        if not source.is_file():
            results.append(Result(source, error=f"falta el archivo {source.name}"))
            continue
        dest = _free_stem(out_dir, f"{source.stem}_{preset}")
        try:
            results.append(
                apply_file(
                    asset.stack, source, dest, cli=Export(preset=preset), protected=protected
                )
            )
        except (OSError, ValueError, pyvips.Error) as e:
            results.append(Result(source, error=f"no se pudo exportar {source.name}: {e}"))
    return results
