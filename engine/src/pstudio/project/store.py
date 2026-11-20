"""Proyecto en disco: carpeta `<Nombre>.pstudio/` con `project.json` y `cache/` (ADR-0009).

Es el único módulo que lee y escribe `project.json`. Las fotos se referencian (ruta absoluta +
SHA-256), nunca se copian ni se abren para escribir.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from pstudio.render import sha256_file
from pstudio.schema import PROJECT_SCHEMA_VERSION, Asset, Project

PROJECT_SUFFIX = ".pstudio"
PROJECT_FILE = "project.json"
CACHE_DIR = "cache"
IMPORTABLE = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"})
_FORBIDDEN = set('<>:"/\\|?*')


class ProjectError(Exception):
    """Error del proyecto con un mensaje en español para el usuario."""


@dataclass
class AddResult:
    added: list[str] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)
    unsupported: list[Path] = field(default_factory=list)


def _check_name(name: str) -> None:
    if not name.strip():
        raise ProjectError("el nombre del proyecto está vacío")
    if len(name) > 100:
        raise ProjectError("el nombre del proyecto supera los 100 caracteres")
    if any(c in _FORBIDDEN or ord(c) < 32 for c in name) or name != name.strip(" ."):
        raise ProjectError(f'el nombre "{name}" tiene caracteres no permitidos')


def create(parent: Path, name: str) -> Path:
    _check_name(name)
    path = Path(parent) / f"{name}{PROJECT_SUFFIX}"
    if path.exists():
        raise ProjectError(f"ya existe {path.name}")
    (path / CACHE_DIR).mkdir(parents=True)
    save(path, Project(name=name))
    return path


def _project_file(path: Path) -> Path:
    path = Path(path)
    return path if path.name == PROJECT_FILE else path / PROJECT_FILE


def open_project(path: Path) -> Project:
    file = _project_file(path)
    if not file.is_file():
        raise ProjectError(f"no existe el proyecto {file.parent.name}")
    try:
        raw = file.read_bytes()
    except OSError as e:
        raise ProjectError(f"no se pudo leer {file.parent.name}: {e.strerror}") from e
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ProjectError(f"{file.parent.name}: project.json está dañado") from e
    version = data.get("schema_version") if isinstance(data, dict) else None
    if version != PROJECT_SCHEMA_VERSION:
        raise ProjectError(
            f"{file.parent.name}: versión de proyecto {version!r} no soportada "
            f"(esta versión abre {PROJECT_SCHEMA_VERSION})"
        )
    try:
        return Project.model_validate(data)
    except ValidationError as e:
        raise ProjectError(f"{file.parent.name}: project.json está dañado") from e


def save(path: Path, project: Project) -> None:
    """Escritura atómica: archivo temporal + `os.replace`. Si falla, el anterior queda intacto."""
    file = _project_file(path)
    tmp = file.with_name(file.name + ".tmp")
    tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8", newline="\n")
    try:
        os.replace(tmp, file)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _expand(paths: list[Path], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        p = Path(p).resolve()
        if p.is_dir():
            found = p.rglob("*") if recursive else p.iterdir()
            # La caché de un proyecto guardado entre las fotos no son fotos del usuario.
            found = (
                f
                for f in found
                if f.is_file()
                and not any(d.endswith(PROJECT_SUFFIX) for d in f.relative_to(p).parts[:-1])
            )
            files.extend(sorted(found, key=lambda f: str(f).lower()))
        else:
            files.append(p)
    return files


def add_assets(project: Project, paths: list[Path], *, recursive: bool = False) -> AddResult:
    result = AddResult()
    known = {a.sha256 for a in project.assets}
    for file in _expand(paths, recursive):
        if file.suffix.lower() not in IMPORTABLE or not file.is_file():
            result.unsupported.append(file)
            continue
        digest = sha256_file(file)
        if digest in known:
            result.duplicates.append(file)
            continue
        known.add(digest)
        asset = Asset.new(uuid.uuid4().hex[:12], str(file), file.stat().st_size, digest)
        project.assets.append(asset)
        result.added.append(asset.id)
    return result


def missing(project: Project) -> list[str]:
    return [a.id for a in project.assets if not Path(a.path).is_file()]


def relink(project: Project, asset_id: str, new_path: Path) -> None:
    asset = project.asset(asset_id)
    new_path = Path(new_path).resolve()
    if not new_path.is_file() or sha256_file(new_path) != asset.sha256:
        raise ProjectError("el archivo no es la misma foto")
    asset.path = str(new_path)
    asset.size = new_path.stat().st_size
