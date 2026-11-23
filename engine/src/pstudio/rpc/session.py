"""Estado del engine mientras la app está abierta: el proyecto abierto y sus cachés.

Un solo proceso escribe el proyecto (ADR-0009), pero nada impide usar `pstudio project …` desde
la terminal con la app abierta. Para no pisar esos cambios en silencio, antes de guardar se
compara `project.json` con lo que se cargó (mtime + tamaño). Si cambió, se recarga y la acción
falla con un mensaje claro; el usuario la repite sobre el proyecto actualizado.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from pstudio import recent
from pstudio.jobs import JobQueue
from pstudio.project.store import CACHE_DIR, PROJECT_FILE, open_project, save
from pstudio.rpc.media import Media
from pstudio.rpc.server import ENGINE_ERROR, NO_PROJECT, PROJECT_CHANGED, Notifier, RpcError
from pstudio.schema import Asset, Project


def _stamp(file: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(file)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


class Session:
    def __init__(self, notifier: Notifier | None = None) -> None:
        self.notifier = notifier
        self.project: Project | None = None
        self.path: Path | None = None  # carpeta <Nombre>.pstudio
        self._stamp: tuple[int, int] | None = None
        self.media = Media(notifier)
        # Los jobs trabajan sobre copias de las fotos: siguen aunque se cierre el proyecto.
        self.jobs = JobQueue(notifier.emit if notifier is not None else None)

    # ------------------------------------------------------------------ proyecto
    def open(self, path: Path) -> Project:
        path = Path(path).resolve()
        if path.name == PROJECT_FILE:
            path = path.parent
        project = open_project(path)
        self.project, self.path = project, path
        self._stamp = _stamp(path / PROJECT_FILE)
        (path / CACHE_DIR).mkdir(exist_ok=True)
        self.on_open()
        with contextlib.suppress(OSError):  # los recientes son una comodidad: nunca impiden abrir
            recent.touch(path, project.name)
        return project

    def close_project(self) -> None:
        if self.path is not None:
            self.media.reset(self.cache_dir)
        self.project, self.path, self._stamp = None, None, None

    def on_open(self) -> None:
        self.media.reset(self.cache_dir)

    @property
    def cache_dir(self) -> Path:
        return self.require_path() / CACHE_DIR

    def require(self) -> Project:
        if self.project is None:
            raise RpcError(NO_PROJECT, "no hay un proyecto abierto")
        return self.project

    def require_path(self) -> Path:
        self.require()
        assert self.path is not None
        return self.path

    def asset(self, asset_id: str) -> Asset:
        try:
            return self.require().asset(asset_id)
        except KeyError as e:
            raise RpcError(ENGINE_ERROR, e.args[0]) from e

    def commit(self) -> None:
        """Guarda el proyecto, salvo que otro programa lo haya cambiado desde que se cargó."""
        path = self.require_path()
        file = path / PROJECT_FILE
        if _stamp(file) != self._stamp:
            self.project = open_project(path)
            self._stamp = _stamp(file)
            raise RpcError(
                PROJECT_CHANGED,
                "el proyecto cambió fuera de la app: se recargó, repetí la acción",
            )
        try:
            save(path, self.require())
        except BaseException:
            # Lo que quedó en memoria sin guardarse no debe colarse en el próximo guardado.
            self.project = open_project(path)
            self._stamp = _stamp(file)
            raise
        self._stamp = _stamp(file)

    def close(self) -> None:
        self.jobs.close()
        self.media.close()
