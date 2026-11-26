"""Previews y miniaturas del proyecto abierto, escritas en `<proyecto>/cache/`.

- **Preview:** el proxy de cada foto se cachea (LRU chico) y la cadena de ajustes reutiliza
  los prefijos de `PreviewCache`. El resultado se escribe como JPEG en `cache/preview/` y la
  app lo muestra con el protocolo de assets de Tauri (ADR-0010). Cada foto conserva solo su
  última preview: la anterior se borra.
- **Miniaturas:** se generan en un hilo aparte (pyvips libera el GIL) para no frenar el bucle
  RPC. Al terminar se avisa con el evento `thumbnail.ready`. Muestran la pila guardada (#61) y
  se guardan como `thumbs/<sha256 del original>-<huella de la pila>.jpg`: sobreviven a un
  "Ubicar…" y a reabrir el proyecto, y una edición nueva da otra ruta. Al generar una se
  borran las demás de esa foto.

Nunca se escribe fuera de `cache/`: los originales solo se leen.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import secrets
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import pyvips
from pydantic import BaseModel, ConfigDict

from pstudio.analysis import analyze
from pstudio.ops import apply_plan
from pstudio.prompting.descriptors import describe
from pstudio.render.preview import PreviewCache, Proxy, make_proxy, render_preview
from pstudio.rpc.server import Notifier, event
from pstudio.schema import Asset, EditPlan

MAX_PROXIES = 4  # ~33 MB cada uno a 2048 px en float
PREVIEW_QUALITY = 85
ANALYSIS_PROXY = 1024  # el mismo que usa la preview mientras se arrastra un slider
THUMB_SIZE = 320
THUMB_QUALITY = 80
# Con pila, el proxy se decodifica al doble del lado de la miniatura: un recorte chico sigue
# llegando a THUMB_SIZE px de lado largo.
THUMB_PROXY = 2 * THUMB_SIZE
EMPTY_STACK_DIGEST = "orig"


def stack_digest(stack: EditPlan) -> str:
    """Huella de la pila para el nombre de la miniatura: 12 hex del sha256 del JSON canónico
    de sus operaciones (lo demás del plan, como la explicación, no cambia los píxeles).
    Sin operaciones: `orig`."""
    if not stack.operations:
        return EMPTY_STACK_DIGEST
    ops = [op.model_dump(mode="json") for op in stack.operations]
    text = json.dumps(ops, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class _ThumbJob:
    """Copia de lo que necesita el hilo de miniaturas (nunca el `Asset` vivo del hilo RPC)."""

    asset: str
    sha256: str
    source: Path
    stack: EditPlan
    dest: Path


@event("thumbnail.ready")
class ThumbnailReady(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    asset: str
    path: str | None
    error: str | None = None


class PreviewImage(BaseModel):
    path: str
    width: int
    height: int
    proxy_ms: float  # 0 si el proxy ya estaba en memoria
    render_ms: float
    encode_ms: float


def _to_jpeg(img: pyvips.Image, dest: Path, quality: int) -> None:
    """scRGB float (o sRGB 8 bits) → JPEG sRGB sin metadatos, con escritura atómica."""
    if img.hasalpha():
        img = img.flatten(background=[1.0, 1.0, 1.0] if img.format == "float" else [255] * 3)
    if img.interpretation != "srgb":
        img = img.colourspace("srgb")
    img = img.cast("uchar")
    tmp = dest.with_name(f".{dest.stem}.{secrets.token_hex(4)}.tmp.jpg")
    try:
        img.jpegsave(str(tmp), Q=quality, keep=pyvips.ForeignKeep.NONE)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


class MissingFile(Exception):
    pass


def _check_file(asset: Asset) -> Path:
    path = Path(asset.path)
    if not path.is_file():
        raise MissingFile(f"falta el archivo {path.name}")
    return path


class Media:
    def __init__(self, notifier: Notifier | None) -> None:
        self.notifier = notifier
        self.cache = PreviewCache()
        # (asset, sha256, lado largo) → (proxy, tamaño del original)
        self._proxies: OrderedDict[tuple[str, str, int], tuple[Proxy, tuple[int, int]]] = (
            OrderedDict()
        )
        self._last: dict[str, Path] = {}
        self._descriptors: dict[tuple[str, str], dict] = {}
        self._counter = 0
        self._queue: queue.Queue[_ThumbJob | None] = queue.Queue()
        self._pending: set[Path] = set()  # destinos en cola o generándose
        # (carpeta, sha256) → última miniatura pedida: las tareas de pilas viejas se descartan
        self._wanted: dict[tuple[Path, str], Path] = {}
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------------ ciclo de vida
    def reset(self, cache_dir: Path) -> None:
        """Al abrir un proyecto: se descartan las previews de la sesión anterior."""
        self._proxies.clear()
        self._last.clear()
        self._descriptors.clear()
        folder = cache_dir / "preview"
        if folder.is_dir():
            for f in folder.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)

    def close(self) -> None:
        if self._worker is not None:
            self._queue.put(None)
            self._worker.join(timeout=10)
            self._worker = None

    # ------------------------------------------------------------------ preview
    def _proxy(self, asset: Asset, long_side: int) -> tuple[Proxy, tuple[int, int], float]:
        """(proxy, tamaño del original, ms que tardó crearlo: 0 si ya estaba en memoria)."""
        key = (asset.id, asset.sha256, long_side)
        entry = self._proxies.get(key)
        if entry is not None:
            self._proxies.move_to_end(key)
            return *entry, 0.0
        start = time.perf_counter()
        proxy, info = make_proxy(_check_file(asset), long_side)
        self._proxies[key] = (proxy, (info.width, info.height))
        while len(self._proxies) > MAX_PROXIES:
            self._proxies.popitem(last=False)
        return proxy, (info.width, info.height), (time.perf_counter() - start) * 1000

    def preview(
        self, cache_dir: Path, asset: Asset, stack: EditPlan, long_side: int
    ) -> PreviewImage:
        _check_file(asset)
        proxy, _, proxy_ms = self._proxy(asset, long_side)
        start = time.perf_counter()
        img = render_preview(self.cache, proxy, stack)
        img = img.copy_memory()
        render_ms = (time.perf_counter() - start) * 1000

        folder = cache_dir / "preview"
        folder.mkdir(parents=True, exist_ok=True)
        self._counter += 1
        dest = folder / f"{asset.id}-{self._counter}.jpg"
        if dest.resolve().parent != folder.resolve():  # el esquema ya lo impide; por las dudas
            raise ValueError(f"id de foto inválido: {asset.id!r}")
        start = time.perf_counter()
        _to_jpeg(img, dest, PREVIEW_QUALITY)
        encode_ms = (time.perf_counter() - start) * 1000
        old = self._last.get(asset.id)
        if old is not None:
            old.unlink(missing_ok=True)
        self._last[asset.id] = dest
        return PreviewImage(
            path=str(dest),
            width=img.width,
            height=img.height,
            proxy_ms=round(proxy_ms, 2),
            render_ms=round(render_ms, 2),
            encode_ms=round(encode_ms, 2),
        )

    def descriptors(self, asset: Asset) -> dict:
        """Descriptores para el planificador, medidos sobre un proxy de preview y cacheados.

        `analyze` reduce a 512 px de todos modos: el proxy da los mismos planes que el original
        (8 fotos reales × 7 pedidos, 56/56 iguales) sin hashear ni decodificar el original en
        cada pedido (150–620 ms con 24–53 MP; presupuesto del borrador: 150 ms). Usa el proxy que
        ya esté en memoria para esa foto; si no hay, crea uno de 1024 px.
        """
        key = (asset.id, asset.sha256)
        if key not in self._descriptors:
            cached = [k for k in self._proxies if k[:2] == key]
            side = cached[-1][2] if cached else ANALYSIS_PROXY
            proxy, (w, h), _ = self._proxy(asset, side)
            self._descriptors[key] = describe(analyze(proxy.image), w, h)
        return self._descriptors[key]

    # ------------------------------------------------------------------ miniaturas
    @staticmethod
    def thumb_path(cache_dir: Path, asset: Asset) -> Path:
        return cache_dir / "thumbs" / f"{asset.sha256}-{stack_digest(asset.stack)}.jpg"

    def thumbnail(self, cache_dir: Path, asset: Asset) -> Path | None:
        """La ruta si ya existe; si no, se encola y llega después por `thumbnail.ready`.

        La app la vuelve a pedir cuando cambia la pila: vale la pedida por última vez. Una tarea
        de una pila anterior que todavía no terminó se descarta sin anunciarse.
        """
        dest = self.thumb_path(cache_dir, asset)
        with self._lock:
            self._wanted[(dest.parent, asset.sha256)] = dest
            if dest.is_file():
                return dest
            if dest in self._pending:
                return None
            self._pending.add(dest)
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name="thumbs", daemon=True)
                self._worker.start()
        stack = asset.stack.model_copy(deep=True)
        self._queue.put(_ThumbJob(asset.id, asset.sha256, Path(asset.path), stack, dest))
        return None

    @staticmethod
    def _render_thumb(source: Path, stack: EditPlan, dest: Path) -> None:
        """Escribe en `dest` la miniatura de `source` con `stack` (corre en el hilo "thumbs")."""
        if not stack.operations:
            # el camino rápido de siempre: shrink-on-load y sin pasar a float
            img = pyvips.Image.thumbnail(
                str(source), THUMB_SIZE, size="down", export_profile="srgb"
            )
        else:
            # El mismo camino que la preview (proxy + `apply_plan` con su escala, que es lo que
            # `render_preview` da bit a bit): recorte, rotación y radios como en el editor.
            # Proxy propio y sin `PreviewCache`: `_proxies` es del hilo RPC y llenar la caché
            # con proxies chicos desalojaría las etapas de la foto que se está editando.
            proxy, _ = make_proxy(source, THUMB_PROXY)
            img = apply_plan(proxy.image, stack, proxy.scale)
            longest = max(img.width, img.height)
            if longest > THUMB_SIZE:
                img = img.resize(THUMB_SIZE / longest)
        _to_jpeg(img, dest, THUMB_QUALITY)

    def _stale(self, job: _ThumbJob) -> bool:
        """Con `_lock` tomado: ¿se pidió después otra miniatura de esa foto?"""
        return self._wanted.get((job.dest.parent, job.sha256)) != job.dest

    def _run(self) -> None:
        while (job := self._queue.get()) is not None:
            path, error = None, None
            with self._lock:
                stale = self._stale(job)
            try:
                if not stale:
                    if not job.source.is_file():
                        raise MissingFile(f"falta el archivo {job.source.name}")
                    job.dest.parent.mkdir(parents=True, exist_ok=True)
                    self._render_thumb(job.source, job.stack, job.dest)
                    path = str(job.dest)
            except MissingFile as e:
                error = str(e)
            except (OSError, ValueError, pyvips.Error) as e:
                error = f"no se pudo leer {job.source.name}"
                print(f"miniatura {job.source.name}: {e!r}", file=sys.stderr)
            with self._lock:
                self._pending.discard(job.dest)
                stale = self._stale(job)
                if stale and path is not None:
                    job.dest.unlink(missing_ok=True)  # la pila cambió mientras se generaba
                elif path is not None:
                    self._drop_other_thumbs(job.dest, job.sha256)
            if self.notifier is not None and not stale:
                self.notifier.emit(
                    "thumbnail.ready", ThumbnailReady(asset=job.asset, path=path, error=error)
                )

    @staticmethod
    def _drop_other_thumbs(keep: Path, sha256: str) -> None:
        """Borra las otras miniaturas de esa foto (otras pilas y la `<sha256>.jpg` de antes de
        #61). Un proyecto no admite dos fotos con el mismo original (`add_assets` las rechaza
        como duplicadas y `relink` exige el mismo hash), así que ningún otro asset las usa.
        Se llama con `_lock` tomado: `thumbnail()` no devuelve un archivo a medio borrar.
        """
        for old in [*keep.parent.glob(f"{sha256}-*.jpg"), keep.parent / f"{sha256}.jpg"]:
            if old != keep:
                old.unlink(missing_ok=True)
