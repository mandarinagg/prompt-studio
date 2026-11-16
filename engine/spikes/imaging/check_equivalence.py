"""Verifica que las tres implementaciones producen la misma imagen desde la misma entrada.

Uso: uv run --group spike python spikes/imaging/check_equivalence.py
Compara la salida sRGB 8 bits de cada backend contra Pillow+numpy (referencia) con PSNR.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from pipelines import BACKENDS, CHAINS, PillowNumpy

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "photos"
MIN_PSNR_DB = 40.0


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return float("inf") if mse == 0 else 10 * np.log10(255**2 / mse)


def main() -> int:
    base = PillowNumpy.load_proxy(FIXTURES / "candle-lowlight.jpg")
    print(f"entrada común: proxy {base.shape[1]}x{base.shape[0]} float32 lineal")
    failures = 0
    for chain_name, chain in CHAINS.items():
        ref = PillowNumpy.to_display(PillowNumpy.apply(PillowNumpy.from_array(base), chain))
        for name, backend in BACKENDS.items():
            if name == "pillow":
                continue
            out = backend.to_display(backend.apply(backend.from_array(base), chain))
            value = psnr(ref, out)
            max_diff = int(np.abs(ref.astype(int) - out.astype(int)).max())
            ok = value >= MIN_PSNR_DB
            failures += not ok
            print(
                f"{chain_name:5} {name:7} PSNR={value:6.2f} dB  max|Δ|={max_diff:3}  "
                f"{'ok' if ok else 'DIFIERE'}"
            )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
