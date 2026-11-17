"""Preview sobre un proxy con caché incremental por etapa (#31, docs/MEDIA_PIPELINE.md).

El plan se recorre en las mismas etapas que `apply_plan` (ops/__init__.py: curvas tonales
consecutivas fundidas en una LUT, ops automáticas, ops sueltas). Después de cada etapa la
imagen se materializa y se guarda en la caché con la clave del prefijo que la produjo:

    sha256(JSON canónico de {motor, sha256 del original, tamaño del proxy, scale,
                             ops no neutras hasta el final de esa etapa})

Al mover el slider de una op se reutiliza la etapa anterior más larga que esté en caché y se
recalcula desde ahí. El resultado es idéntico bit a bit al de `apply_plan` sobre el proxy
(mismas etapas, mismas operaciones de libvips; materializar no cambia los valores).

La copia chica que miden las ops automáticas también se guarda en la entrada mientras quede
alguna op automática más adelante; una entrada sin esa copia no sirve para retomar un plan que
todavía la necesita y se trata como ausente.

La caché es en RAM, con límite en bytes y desalojo LRU. El export a resolución completa no la
usa: siempre recalcula desde el original con `apply_plan`.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path

import pyvips

from pstudio import __version__
from pstudio.ops import RenderState, Stage, auto_ahead, plan_stages, run_stage, start_state
from pstudio.render.io import SourceInfo, decode
from pstudio.schema import EditPlan

PROXY_SIZE = 2048  # lado largo del proxy de preview (px)
DEFAULT_MAX_BYTES = 512 * 1024 * 1024  # HARDWARE_COMPATIBILITY: caché en RAM ≲ 2 GB

_FORMAT_BYTES = {
    "uchar": 1, "char": 1, "ushort": 2, "short": 2, "uint": 4, "int": 4,
    "float": 4, "complex": 8, "double": 8, "dpcomplex": 16,
}  # fmt: skip


@dataclass(frozen=True)
class Proxy:
    """Imagen reducida (scRGB float32, en memoria) sobre la que se calcula la preview."""

    image: pyvips.Image
    source_sha256: str  # hash del original, calculado al decodificarlo (render/io.py)
    scale: float  # píxeles del proxy por píxel del original


def make_proxy(path: str | Path, long_side: int = PROXY_SIZE) -> tuple[Proxy, SourceInfo]:
    """Decodifica el original (solo lectura) y lo reduce a `long_side` px de lado largo."""
    img, info = decode(path)
    longest = max(img.width, img.height)
    factor = min(1.0, long_side / longest)
    if factor < 1:
        if img.hasalpha():
            img = img.premultiply(max_alpha=1.0).resize(factor).unpremultiply(max_alpha=1.0)
        else:
            img = img.resize(factor)
        img = img.copy(interpretation="scrgb").cast("float")
    img = img.copy_memory()
    return Proxy(img, info.sha256, max(img.width, img.height) / longest), info


def image_bytes(img: pyvips.Image | None) -> int:
    if img is None:
        return 0
    return img.width * img.height * img.bands * _FORMAT_BYTES.get(img.format, 8)


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def prefix_keys(proxy: Proxy, stages: list[Stage]) -> list[str]:
    """Clave de caché al final de cada etapa (una por etapa, en orden)."""
    head = {
        "engine": __version__,
        "source": proxy.source_sha256,
        "size": [proxy.image.width, proxy.image.height, proxy.image.bands],
        "scale": proxy.scale,
    }
    ops: list[dict] = []
    keys = []
    for stage in stages:
        ops.extend(op.model_dump(mode="json") for op in stage.ops)
        text = _canonical({**head, "ops": ops})
        keys.append(hashlib.sha256(text.encode()).hexdigest())
    return keys


class PreviewCache:
    """Resultados de prefijos del plan, en RAM, con límite en bytes y desalojo LRU."""

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        if max_bytes < 0:
            raise ValueError("max_bytes no puede ser negativo")
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, tuple[RenderState, int]] = OrderedDict()
        self._nbytes = 0
        self._lock = threading.Lock()
        self.stages_reused = 0  # etapas que no se recalcularon gracias a la caché
        self.stages_computed = 0
        self.evictions = 0

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @max_bytes.setter
    def max_bytes(self, value: int) -> None:
        if value < 0:
            raise ValueError("max_bytes no puede ser negativo")
        with self._lock:
            self._max_bytes = value
            self._evict()

    @property
    def nbytes(self) -> int:
        return self._nbytes

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def get(self, key: str) -> RenderState | None:
        """La entrada (sin marcarla como usada: eso lo hace `touch`)."""
        with self._lock:
            entry = self._entries.get(key)
            return None if entry is None else entry[0]

    def touch(self, keys: list[str]) -> None:
        """Marca como recién usadas las claves presentes, en ese orden (la última, la más)."""
        with self._lock:
            for key in keys:
                if key in self._entries:
                    self._entries.move_to_end(key)

    def put(self, key: str, state: RenderState) -> None:
        size = image_bytes(state.image) + image_bytes(state.analysis)
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._nbytes -= old[1]
            if size > self._max_bytes:
                return  # no entra ni sola: no se guarda
            self._entries[key] = (state, size)
            self._nbytes += size
            self._evict()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._nbytes = 0

    def _evict(self) -> None:
        while self._nbytes > self._max_bytes and self._entries:
            _, (_, size) = self._entries.popitem(last=False)
            self._nbytes -= size
            self.evictions += 1


def render_preview(cache: PreviewCache, proxy: Proxy, plan: EditPlan) -> pyvips.Image:
    """Aplica `plan` al proxy reutilizando el prefijo más largo que esté en la caché.

    Devuelve scRGB float32 en memoria, idéntico bit a bit a
    `apply_plan(proxy.image, plan, proxy.scale)`.
    """
    stages = plan_stages(plan)
    if not stages:
        return proxy.image
    ahead = auto_ahead(stages)
    keys = prefix_keys(proxy, stages)

    done, state = -1, None
    for i in range(len(stages) - 1, -1, -1):
        entry = cache.get(keys[i])
        if entry is not None and (entry.analysis is not None or not ahead[i + 1]):
            done, state = i, entry
            break
    if state is None:
        state = start_state(proxy.image, proxy.scale, ahead[0])
    cache.touch(keys[: done + 1])  # el prefijo reutilizado queda como lo más reciente
    cache.stages_reused += done + 1

    for i in range(done + 1, len(stages)):
        state = run_stage(stages[i], state, keep_analysis=ahead[i + 1])
        state = replace(state, image=state.image.copy_memory())
        cache.put(keys[i], state)
        cache.stages_computed += 1
    return state.image
