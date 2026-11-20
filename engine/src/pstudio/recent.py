"""Proyectos recientes: los que la pantalla de inicio ofrece reabrir.

Viven en la configuración del usuario (`recent.json`), no en ningún proyecto. Es una comodidad:
si el archivo se daña o no se puede escribir, la lista queda vacía y nada más falla.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from pstudio.project.store import PROJECT_FILE

MAX_RECENT = 10
RECENT_FILE = "recent.json"
_VERSION = 1


class RecentProject(BaseModel):
    path: str
    name: str
    opened_at: str  # ISO 8601, UTC
    exists: bool


def config_dir() -> Path:
    """Carpeta de configuración: `PSTUDIO_CONFIG_DIR`, si no `%APPDATA%/PROMPT STUDIO`."""
    if env := os.environ.get("PSTUDIO_CONFIG_DIR"):
        return Path(env)
    if appdata := os.environ.get("APPDATA"):
        return Path(appdata) / "PROMPT STUDIO"
    return Path.home() / ".config" / "prompt-studio"


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _load() -> list[dict[str, str]]:
    """La lista guardada. Si no existe o está dañada, vacía; si no se puede leer, OSError."""
    try:
        raw = (config_dir() / RECENT_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        items = json.loads(raw)["items"]
        if not isinstance(items, list):
            return []
        return [
            {"path": str(i["path"]), "name": str(i["name"]), "opened_at": str(i["opened_at"])}
            for i in items
        ]
    except ValueError, TypeError, KeyError:
        return []


def _read() -> list[dict[str, str]]:
    try:
        return _load()
    except OSError:
        return []


def _write(items: list[dict[str, str]]) -> None:
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / RECENT_FILE
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": _VERSION, "items": items}, indent=2), encoding="utf-8")
    os.replace(tmp, file)


def list_recent() -> list[RecentProject]:
    return [RecentProject(**i, exists=(Path(i["path"]) / PROJECT_FILE).is_file()) for i in _read()]


def touch(path: Path, name: str) -> None:
    """Pone el proyecto primero en la lista (lo agrega si no estaba)."""
    resolved = str(Path(path).resolve())
    # Si no se pudo leer (archivo bloqueado), no se escribe: se perderían los demás recientes.
    items = [i for i in _load() if _key(i["path"]) != _key(resolved)]
    now = datetime.now(UTC).isoformat(timespec="seconds")
    items.insert(0, {"path": resolved, "name": name, "opened_at": now})
    _write(items[:MAX_RECENT])


def forget(path: str) -> None:
    items = _load()
    kept = [i for i in items if _key(i["path"]) != _key(path)]
    if len(kept) != len(items):
        _write(kept)
