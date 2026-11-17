"""Golden images: el resultado de cada op sobre una entrada fija se compara con una referencia.

No prueban que la op sea "correcta" (eso lo hacen los tests de propiedades: neutro, monotonía,
dirección). Detectan **cambios involuntarios** en una op ya revisada.

Las referencias son PNG de 16 bits (sRGB) en tests/fixtures/tiny/golden/: chicas, generadas,
sin licencias de terceros. Para regenerarlas después de un cambio intencional:
    PSTUDIO_UPDATE_GOLDEN=1 uv run pytest tests/test_ops_*.py
y revisar las diferencias antes de commitear.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pyvips
from imaging import ssim, synthetic_rgb, to_vips

GOLDEN = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "tiny" / "golden"
UPDATE = os.environ.get("PSTUDIO_UPDATE_GOLDEN") == "1"
MAX_DIFF = 0.002  # en fracción de la escala (≈ 0.5/255): margen para diferencias de CPU/libvips


def golden_input() -> pyvips.Image:
    """Entrada fija (scRGB float) para todas las golden: gradientes, ruido y bordes."""
    path = GOLDEN / "input.png"
    if UPDATE and not path.exists():
        GOLDEN.mkdir(parents=True, exist_ok=True)
        to_vips(synthetic_rgb(96, 64, seed=11)).write_to_file(str(path))
    return pyvips.Image.new_from_file(str(path), revalidate=True).colourspace("scrgb")


def _to_16bit(img: pyvips.Image) -> np.ndarray:
    return img.colourspace("rgb16").cast("ushort").numpy()


def check_golden(name: str, result: pyvips.Image) -> None:
    path = GOLDEN / f"{name}.png"
    got = _to_16bit(result)
    if UPDATE:
        pyvips.Image.new_from_array(got).copy(interpretation="rgb16").write_to_file(str(path))
        return
    assert path.exists(), f"falta {path.name}: generar con PSTUDIO_UPDATE_GOLDEN=1"
    want = pyvips.Image.new_from_file(str(path), revalidate=True).numpy()
    diff = np.abs(got.astype(np.int32) - want.astype(np.int32)).max() / 65535
    assert diff <= MAX_DIFF, f"{name}: diferencia máx {diff:.4f} > {MAX_DIFF}"
    assert ssim(got, want, data_range=65535) >= 0.995
