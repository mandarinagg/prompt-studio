"""Previews y miniaturas del proyecto abierto, escritas en `<proyecto>/cache/`.

- **Preview:** el proxy de cada foto se cachea (LRU chico) y la cadena de ajustes reutiliza
  los prefijos de `PreviewCache`. El resultado se escribe como JPEG en `cache/preview/` y la
  app lo muestra con el protocolo de assets de Tauri (ADR-0010). Cada foto conserva solo su
  última preview: la anterior se borra.
- **Miniaturas:** se generan en un hilo aparte (pyvips libera el GIL) para no frenar el bucle
  RPC. Al terminar se avisa con el evento `thumbnail.ready`. Se guardan por hash del original,
  así sobreviven a un "Ubicar…" y a reabrir el proyecto.

Nunca se escribe fuera de `cache/`: los originales solo se leen.
"""

from __future__ import annotations

import os
import queue
import secrets
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

import pyvips
from pydantic import BaseModel, ConfigDict

from pstudio.render.preview import PreviewCache, Proxy, make_proxy, render_preview
from pstudio.rpc.server import Notifier, event
from pstudio.schema import Asset, EditPlan

MAX_PROXIES = 4  # ~33 MB cada uno a 2048 px en float
PREVIEW_QUALITY = 85
THUMB_SIZE = 320
THUMB_QUALITY = 80


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
        self._proxies: OrderedDict[tuple[str, str, int], Proxy] = OrderedDict()
        self._last: dict[str, Path] = {}
        self._counter = 0
        self._queue: queue.Queue[tuple[str, Path, Path] | None] = queue.Queue()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------------ ciclo de vida
    def reset(self, cache_dir: Path) -> None:
        """Al abrir un proyecto: se descartan las previews de la sesión anterior."""
        self._proxies.clear()
        self._last.clear()
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
    def _proxy(self, asset: Asset, long_side: int) -> tuple[Proxy, float]:
        key = (asset.id, asset.sha256, long_side)
        proxy = self._proxies.get(key)
        if proxy is not None:
            self._proxies.move_to_end(key)
            return proxy, 0.0
        start = time.perf_counter()
        proxy, _ = make_proxy(_check_file(asset), long_side)
        self._proxies[key] = proxy
        while len(self._proxies) > MAX_PROXIES:
            self._proxies.popitem(last=False)
        return proxy, (time.perf_counter() - start) * 1000

    def preview(
        self, cache_dir: Path, asset: Asset, stack: EditPlan, long_side: int
    ) -> PreviewImage:
        _check_file(asset)
        proxy, proxy_ms = self._proxy(asset, long_side)
        start = time.perf_counter()
        img = render_preview(self.cache, proxy, stack)
        img = img.copy_memory()
        render_ms = (time.perf_counter() - start) * 1000

        folder = cache_dir / "preview"
        folder.mkdir(parents=True, exist_ok=True)
        self._counter += 1
        dest = folder / f"{asset.id}-{self._counter}.jpg"
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

    # ------------------------------------------------------------------ miniaturas
    @staticmethod
    def thumb_path(cache_dir: Path, asset: Asset) -> Path:
        return cache_dir / "thumbs" / f"{asset.sha256}.jpg"

    def thumbnail(self, cache_dir: Path, asset: Asset) -> Path | None:
        """La ruta si ya existe; si no, se encola y llega después por `thumbnail.ready`."""
        dest = self.thumb_path(cache_dir, asset)
        if dest.is_file():
            return dest
        with self._lock:
            if asset.id in self._pending:
                return None
            self._pending.add(asset.id)
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name="thumbs", daemon=True)
                self._worker.start()
        self._queue.put((asset.id, Path(asset.path), dest))
        return None

    def _run(self) -> None:
        while (item := self._queue.get()) is not None:
            asset_id, source, dest = item
            path, error = None, None
            try:
                if not source.is_file():
                    raise MissingFile(f"falta el archivo {source.name}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                img = pyvips.Image.thumbnail(
                    str(source), THUMB_SIZE, size="down", export_profile="srgb"
                )
                _to_jpeg(img, dest, THUMB_QUALITY)
                path = str(dest)
            except MissingFile as e:
                error = str(e)
            except (OSError, pyvips.Error) as e:
                error = f"no se pudo leer {source.name}"
                print(f"miniatura {source.name}: {e!r}", file=sys.stderr)
            with self._lock:
                self._pending.discard(asset_id)
            if self.notifier is not None:
                self.notifier.emit(
                    "thumbnail.ready", ThumbnailReady(asset=asset_id, path=path, error=error)
                )
