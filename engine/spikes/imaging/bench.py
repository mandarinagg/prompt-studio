"""Benchmark de un backend sobre una imagen. Imprime una línea JSON.

Uso: uv run --group spike python spikes/imaging/bench.py --backend pyvips --image <ruta>
Se ejecuta un proceso por (backend, imagen) para que el pico de memoria sea comparable.

Mide:
  open_proxy     decodificar + reducir a 2048 px + pasar a lineal (al abrir una foto)
  preview_<n>    aplicar la cadena al proxy en RAM + convertir a sRGB 8 bits (mover un slider,
                 peor caso: se recalcula toda la cadena, sin caché incremental)
  export_<n>     decodificar a resolución completa + cadena + JPEG q92 a disco
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import psutil
from pipelines import BACKENDS, CHAINS


def timed(fn, rounds: int) -> dict:
    samples = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return {
        "median_ms": round(statistics.median(samples), 1),
        "p90_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.9))], 1),
        "min_ms": round(samples[0], 1),
        "rounds": rounds,
    }


def vary(chain, i: int):
    """Cambia levemente el primer valor en cada ronda, como un slider en movimiento."""
    first = chain[0]
    return [replace(first, value=first.value + 0.01 * (i % 7)), *chain[1:]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True, choices=list(BACKENDS))
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--preview-rounds", type=int, default=15)
    parser.add_argument("--export-rounds", type=int, default=3)
    args = parser.parse_args()

    backend = BACKENDS[args.backend]
    if args.backend == "pyvips":
        import pyvips

        pyvips.cache_set_max(0)  # sin caché de operaciones: medir trabajo real

    result: dict = {"backend": args.backend, "image": args.image.stem}
    backend.load_proxy(args.image)  # calentamiento (imports, caché de disco del SO)
    result["open_proxy"] = timed(lambda: backend.load_proxy(args.image), 5)

    proxy = backend.load_proxy(args.image)
    for name, chain in CHAINS.items():
        backend.to_display(backend.apply(proxy, chain))  # calentamiento
        counter = iter(range(10**6))
        result[f"preview_{name}"] = timed(
            lambda chain=chain, counter=counter: backend.to_display(
                backend.apply(proxy, vary(chain, next(counter)))
            ),
            args.preview_rounds,
        )

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.jpg"
        for name in ("4op", "10op"):
            chain = CHAINS[name]
            result[f"export_{name}"] = timed(
                lambda chain=chain: backend.save_jpeg(
                    backend.apply(backend.load_full(args.image), chain), out
                ),
                args.export_rounds,
            )
        result["export_bytes"] = out.stat().st_size

    proc = psutil.Process(os.getpid())
    mem = proc.memory_info()
    result["peak_mem_mb"] = round(getattr(mem, "peak_wset", mem.rss) / 2**20)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
