"""Cola de trabajos largos del engine (#60): por ahora, exportar fotos.

- **Un solo hilo** worker (daemon), que arranca con el primer `submit_*` y atiende los jobs en
  orden (FIFO). libvips ya paraleliza adentro de cada export; un hilo frena menos la preview
  que un proceso aparte (mediciones en docs/superpowers/plans/2026-11-23-m3-60-jobs.md).
- Cada job trabaja sobre una **copia** de las fotos y sus pilas tomada al crearlo: el usuario
  puede seguir editando y el worker nunca lee ni escribe el proyecto abierto.
- **Cancelación cooperativa:** entre fotos con una bandera y, a mitad de una foto, desde el
  monitor de `encode` (`set_kill` de libvips). De la foto en curso no queda nada (ni el
  temporal); las ya terminadas se conservan y se informan; el resto queda como cancelado.
- **Eventos** (`on_event(nombre, JobInfo)`): `job.progress`* y después exactamente uno de
  `job.done` (`status` `done` o `cancelled`) o `job.failed` (error inesperado, p. ej. no se pudo
  crear la carpeta destino). El progreso nunca baja y se limita a ~10 por segundo, salvo el
  cambio de foto, que siempre se emite. Cada evento lleva una copia: el worker no la toca.

Nunca se escribe sobre originales: todas las fotos del proyecto viajan como `protected`.
"""

from __future__ import annotations

import queue
import secrets
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pstudio.project.export import export_copies
from pstudio.render.io import Cancelled
from pstudio.schema import Asset
from pstudio.schema.plan import ExportPreset

__all__ = ["Cancelled", "JobInfo", "JobItem", "JobQueue"]

PROGRESS_INTERVAL = 0.1  # segundos entre eventos de progreso de una misma foto
MAX_KEPT = 50  # jobs terminados que se recuerdan para `list()`

Status = Literal["queued", "running", "done", "failed", "cancelled"]
EventFn = Callable[[str, BaseModel], None]


class JobItem(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    asset: str
    path: str | None = None  # None: no se exportó (error o cancelado)
    error: str | None = None


class JobInfo(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    kind: Literal["export"] = "export"
    status: Status = "queued"
    total: int
    done: int = 0  # fotos terminadas (bien o con error)
    current: str | None = None  # nombre de archivo de la foto en curso
    fraction: float = 0.0  # 0–1 del job completo
    out_dir: str
    results: list[JobItem] = []
    error: str | None = None
    ms: float | None = None


@dataclass
class _Job:
    info: JobInfo
    assets: list[Asset]
    protected: tuple[Path, ...]
    out_dir: Path
    preset: ExportPreset
    cancel: threading.Event = field(default_factory=threading.Event)
    index: int = -1  # foto en curso
    last_emit: float = 0.0


class JobQueue:
    def __init__(self, on_event: EventFn | None = None) -> None:
        self._on_event = on_event
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._closed = False

    # ------------------------------------------------------------------ API
    def submit_export(
        self,
        assets: list[Asset],
        protected: list[Path],
        out_dir: Path,
        preset: ExportPreset,
    ) -> JobInfo:
        """Encola un export. Las fotos se copian ahora: editar después no cambia el job."""
        job = _Job(
            info=JobInfo(id=secrets.token_hex(6), total=len(assets), out_dir=str(out_dir)),
            assets=[a.model_copy(deep=True) for a in assets],
            protected=tuple(Path(p) for p in protected),
            out_dir=Path(out_dir),
            preset=preset,
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("la cola de trabajos está cerrada")
            self._jobs[job.info.id] = job
            self._trim()
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name="jobs", daemon=True)
                self._worker.start()
            snapshot = job.info.model_copy(deep=True)
        self._queue.put(job.info.id)
        return snapshot

    def cancel(self, job_id: str) -> JobInfo:
        """En cola: queda cancelado sin correr. Corriendo: se pide que pare (el estado cambia
        cuando el worker termina la foto en curso). Terminado: sin cambios."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"no existe el trabajo {job_id}")
            queued = job.info.status == "queued"
            if queued or job.info.status == "running":
                job.cancel.set()
            if queued:
                job.info.status = "cancelled"
            snapshot = job.info.model_copy(deep=True)
        if queued:
            self._emit("job.done", snapshot)
        return snapshot

    def list(self) -> list[JobInfo]:
        """Los últimos `MAX_KEPT` jobs, del más viejo al más nuevo."""
        with self._lock:
            return [j.info.model_copy(deep=True) for j in list(self._jobs.values())[-MAX_KEPT:]]

    def close(self, timeout: float = 10) -> None:
        """Cancela todo (lo encolado y lo que corre) y espera al worker hasta `timeout`."""
        with self._lock:
            self._closed = True
            pending = [j.info.id for j in self._jobs.values() if j.info.status == "queued"]
            for job in self._jobs.values():
                if job.info.status == "running":
                    job.cancel.set()
        for job_id in pending:
            self.cancel(job_id)
        if self._worker is not None:
            self._queue.put(None)
            self._worker.join(timeout=timeout)

    # ------------------------------------------------------------------ worker
    def _trim(self) -> None:
        """Olvida los jobs terminados más viejos (nunca los que esperan o corren)."""
        finished = [k for k, j in self._jobs.items() if j.info.status not in ("queued", "running")]
        for k in finished[: max(0, len(self._jobs) - MAX_KEPT)]:
            del self._jobs[k]

    def _emit(self, name: str, info: JobInfo) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(name, info)
        except Exception as e:  # un oyente roto no puede matar al worker
            print(f"evento {name}: {e!r}", file=sys.stderr)

    def _run(self) -> None:
        while (job_id := self._queue.get()) is not None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.info.status != "queued":
                    continue
                job.info.status = "running"
            self._execute(job)

    def _execute(self, job: _Job) -> None:
        start = time.perf_counter()

        def on_progress(i: int, total: int, asset_id: str, fraction: float) -> None:
            now = time.monotonic()
            with self._lock:
                info = job.info
                changed = i != job.index
                job.index = i
                info.current = Path(job.assets[i].path).name
                info.done = i + (1 if fraction >= 1 else 0)
                info.fraction = max(info.fraction, (i + fraction) / total)
                if not changed and now - job.last_emit < PROGRESS_INTERVAL:
                    return
                job.last_emit = now
                snapshot = info.model_copy(deep=True)
            self._emit("job.progress", snapshot)

        try:
            results = export_copies(
                job.assets,
                job.out_dir,
                job.preset,
                protected=job.protected,
                on_progress=on_progress,
                cancel=job.cancel,
            )
        except Exception as e:
            with self._lock:
                job.info.status = "failed"
                job.info.error = str(e) or type(e).__name__
                job.info.ms = round((time.perf_counter() - start) * 1000, 2)
                snapshot = job.info.model_copy(deep=True)
            self._emit("job.failed", snapshot)
            return

        with self._lock:
            info = job.info
            info.results = [
                JobItem(asset=a.id, path=str(r.dest) if r.dest else None, error=r.error)
                for a, r in zip(job.assets, results, strict=True)
            ]
            if any(r.cancelled for r in results):
                info.status = "cancelled"
            else:
                info.status = "done"
                info.done = info.total
                info.fraction = 1.0
            info.ms = round((time.perf_counter() - start) * 1000, 2)
            snapshot = info.model_copy(deep=True)
        self._emit("job.done", snapshot)
