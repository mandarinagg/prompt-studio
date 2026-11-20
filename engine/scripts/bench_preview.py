"""Bench de la preview (#42): costo de mover un slider y de abrir una foto.

Uso (desde engine/):
    uv run python scripts/bench_preview.py                       # backlit-tree, 1024 y 2048
    uv run python scripts/bench_preview.py --photo candle-lowlight --frames 9

Usa las fotos de tests/fixtures/photos (se bajan con tests/fixtures/fetch_fixtures.py).

Imprime tres tablas (mediana de `--frames` cuadros, en ms):
1. Cada op como **última** de una cadena de 10: el prefijo ya está en la caché y solo se
   recalcula esa op. Cada cuadro usa una caché nueva con el prefijo precalculado y un valor
   distinto, para que ni la caché de preview ni la de operaciones de libvips respondan solas.
2. La **primera** op (exposure) cambia en cada cuadro: se recalcula toda la cadena.
3. `make_proxy` en frío para cada foto (decode + reducción + hash del original).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import pyvips

from pstudio.render import PreviewCache, make_proxy, render_preview
from pstudio.schema import EditPlan

PHOTOS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "photos"

# La cadena de 10 de la app: lo que un usuario suele tener activo al editar.
CHAIN: list[dict] = [
    {"op": "exposure", "ev": 0.3},
    {"op": "contrast", "amount": 20},
    {"op": "highlights", "amount": -30},
    {"op": "shadows", "amount": 25},
    {"op": "whites", "amount": 10},
    {"op": "blacks", "amount": -10},
    {"op": "white_balance", "temperature_shift": 15, "tint_shift": -5},
    {"op": "saturation", "amount": 10},
    {"op": "vibrance", "amount": 30},
    {"op": "vignette", "amount": -30},
]
EXTRA: dict[str, dict] = {
    "sharpen": {"op": "sharpen", "amount": 40, "radius": 1.5},
    "denoise": {"op": "denoise", "strength": 0.4},
    "auto_exposure": {"op": "auto_exposure", "strength": 1.0},
    "auto_white_balance": {"op": "auto_white_balance", "method": "gray_world"},
}


def variant(op: dict, i: int) -> dict:
    """La op con un valor distinto para el cuadro i (sin repetir valores)."""
    name = op["op"]
    if name == "exposure":
        return {**op, "ev": 0.1 + 0.05 * i}
    if name == "white_balance":
        return {**op, "temperature_shift": 5 + i}
    if name == "sharpen":
        return {**op, "amount": 30 + i}
    if name == "denoise":
        return {**op, "strength": 0.2 + 0.03 * i}
    if name == "auto_exposure":
        return {**op, "strength": 0.5 + 0.03 * i}
    if name == "auto_white_balance":
        return {**op, "method": ("gray_world", "white_patch")[i % 2]}
    return {**op, "amount": (-1) ** i * (10 + i)}


def plan(ops: list[dict]) -> EditPlan:
    return EditPlan.model_validate({"operations": ops})


def last_op_chain(name: str) -> list[dict]:
    """Las otras 9 ops de CHAIN (o las 10 si es extra, sin la primera) y `name` al final."""
    if name in EXTRA:
        return [*CHAIN[1:], EXTRA[name]]
    return [*(o for o in CHAIN if o["op"] != name), next(o for o in CHAIN if o["op"] == name)]


def time_last(proxy, name: str, frames: int) -> float:
    ops = last_op_chain(name)
    samples = []
    for i in range(frames + 1):
        cache = PreviewCache()
        render_preview(cache, proxy, plan([*ops[:-1], variant(ops[-1], i)]))  # prefijo
        p = plan([*ops[:-1], variant(ops[-1], i + 1)])
        start = time.perf_counter()
        render_preview(cache, proxy, p)
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples[1:])


def time_first(proxy, frames: int) -> float:
    cache = PreviewCache()
    render_preview(cache, proxy, plan(CHAIN))
    samples = []
    for i in range(frames + 1):
        p = plan([variant(CHAIN[0], i + 1), *CHAIN[1:]])
        start = time.perf_counter()
        render_preview(cache, proxy, p)
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples[1:])


def time_proxy(path: Path, side: int, rounds: int) -> float:
    samples = []
    for _ in range(rounds):
        start = time.perf_counter()
        make_proxy(path, side)
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--photo", default="backlit-tree", help="nombre en tests/fixtures/photos")
    ap.add_argument("--sizes", default="1024,2048")
    ap.add_argument("--frames", type=int, default=7)
    ap.add_argument("--skip-proxy", action="store_true", help="no medir make_proxy")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    path = PHOTOS / f"{args.photo}.jpg"
    if not path.is_file():
        print(f"falta {path}: bajar las fotos con tests/fixtures/fetch_fixtures.py")
        return 1
    sizes = [int(s) for s in args.sizes.split(",")]
    print(f"libvips {pyvips.version(0)}.{pyvips.version(1)}.{pyvips.version(2)}, "
          f"hilos {pyvips.vips_lib.vips_concurrency_get()}, foto {args.photo}")  # fmt: skip

    proxies = {s: make_proxy(path, s)[0] for s in sizes}
    dims = ", ".join(f"{p.image.width}×{p.image.height}" for p in proxies.values())
    print(f"\n## Op como última de la cadena de 10 (proxy {dims}), ms\n")
    print("| op | " + " | ".join(f"{s} px" for s in sizes) + " |")
    print("|---|" + "---:|" * len(sizes))
    for name in [o["op"] for o in CHAIN] + list(EXTRA):
        cells = [f"{time_last(proxies[s], name, args.frames):.1f}" for s in sizes]
        print(f"| {name} | " + " | ".join(cells) + " |")
    cells = [f"{time_first(proxies[s], args.frames):.1f}" for s in sizes]
    print("| **cambia la 1.ª op (exposure): toda la cadena** | " + " | ".join(cells) + " |")

    if not args.skip_proxy:
        print("\n## make_proxy en frío (mediana de 3), ms\n")
        print("| foto | MP | " + " | ".join(f"{s} px" for s in sizes) + " |")
        print("|---|---:|" + "---:|" * len(sizes))
        for photo in sorted(PHOTOS.glob("*.jpg")):
            head = pyvips.Image.new_from_file(str(photo))
            mp = head.width * head.height / 1e6
            cells = [f"{time_proxy(photo, s, 3):.0f}" for s in sizes]
            print(f"| {photo.stem} | {mp:.0f} | " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
