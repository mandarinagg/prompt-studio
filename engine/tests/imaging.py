"""Utilidades de imagen para tests (sin dependencias extra: numpy + pyvips)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvips

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "photos"


def fixture(name: str) -> Path | None:
    """Foto CC0 de tests/fixtures (se bajan con fetch_fixtures.py; no están en CI)."""
    path = FIXTURES / f"{name}.jpg"
    return path if path.is_file() else None


def synthetic_rgb(width: int = 256, height: int = 192, seed: int = 0) -> np.ndarray:
    """Gradientes + ruido + bordes duros: ejercita tonos, color y detalle fino. uint8 HxWx3."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width]
    r = x / (width - 1) * 255
    g = y / (height - 1) * 255
    b = ((x // 16 + y // 16) % 2) * 200 + 25
    img = np.stack([r, g, b], axis=-1) + rng.normal(0, 6, (height, width, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def to_vips(arr: np.ndarray, interpretation: str = "srgb") -> pyvips.Image:
    return pyvips.Image.new_from_array(arr).copy(interpretation=interpretation)


def _box(a: np.ndarray, k: int) -> np.ndarray:
    """Media en ventanas k×k (válidas) con suma acumulada."""
    c = np.cumsum(np.cumsum(np.pad(a, ((1, 0), (1, 0))), axis=0), axis=1)
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def ssim(a: np.ndarray, b: np.ndarray, data_range: float = 255.0, k: int = 7) -> float:
    """SSIM medio sobre la luminancia (Wang et al. 2004, ventana cuadrada k×k)."""

    def luma(x: np.ndarray) -> np.ndarray:
        x = x.astype(np.float64)
        return x if x.ndim == 2 else x[..., :3] @ np.array([0.2126, 0.7152, 0.0722])

    x, y = luma(a), luma(b)
    c1, c2 = (0.01 * data_range) ** 2, (0.03 * data_range) ** 2
    mx, my = _box(x, k), _box(y, k)
    vx = _box(x * x, k) - mx * mx
    vy = _box(y * y, k) - my * my
    cov = _box(x * y, k) - mx * my
    s = ((2 * mx * my + c1) * (2 * cov + c2)) / ((mx**2 + my**2 + c1) * (vx + vy + c2))
    return float(s.mean())


def pixels(path: Path) -> np.ndarray:
    """Pixeles tal como quedaron en el archivo (sin conversión de color), ya orientados."""
    return pyvips.Image.new_from_file(str(path), revalidate=True).autorot().numpy()
