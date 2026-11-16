"""Spike #2: mismo pipeline de edición implementado con Pillow+numpy, OpenCV y pyvips.

Todas las variantes trabajan en RGB lineal float32 en [0, 1+] y usan la misma matemática:

    exposure(ev)        x * 2**ev
    white_balance(g)    x * (gr, gg, gb)
    contrast(c)         pivot * (x / pivot) ** c          (pivot = 0.18 gris medio)
    saturation(s)       L + s * (x - L),  L = luma Rec.709
    sharpen(a, sigma)   x + a * (x - gauss(x, sigma))     (sigma escala con la resolución)
    vignette(a)         x * (1 - a * r²),  r² normalizado a 1 en las esquinas

La decodificación sRGB->lineal usa una LUT de 256 entradas; la codificación lineal->sRGB usa una
LUT de 4096 entradas (pyvips usa sus conversiones de espacio de color exactas).
Esto es código de spike: no forma parte del paquete `pstudio`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

PROXY_LONG_EDGE = 2048
JPEG_QUALITY = 92
PIVOT = 0.18
SHARPEN_SIGMA_FULL = 1.2  # sigma a resolución completa (24 MP)
REC709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


@dataclass(frozen=True)
class Op:
    name: str
    value: float | tuple[float, float, float]


CHAIN_1 = [Op("exposure", 0.5)]
CHAIN_4 = [  # el set del issue #2: exposure + contrast + WB + sharpen
    Op("exposure", 0.5),
    Op("white_balance", (1.08, 1.0, 0.92)),
    Op("contrast", 1.15),
    Op("sharpen", 0.6),
]
CHAIN_10 = [  # objetivo de PRODUCT_SPEC §7: export con 10 operaciones
    *CHAIN_4,
    Op("saturation", 1.1),
    Op("vignette", 0.3),
    Op("exposure", -0.1),
    Op("contrast", 1.05),
    Op("saturation", 1.05),
    Op("white_balance", (1.0, 1.0, 1.02)),
]
CHAINS = {"1op": CHAIN_1, "4op": CHAIN_4, "10op": CHAIN_10}


# ---------------------------------------------------------------- transferencia sRGB (compartida)
def _srgb_to_linear(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


DECODE_LUT = _srgb_to_linear(np.arange(256, dtype=np.float64) / 255).astype(np.float32)
ENCODE_LUT = np.round(_linear_to_srgb(np.arange(4096, dtype=np.float64) / 4095) * 255).astype(
    np.uint8
)


def encode_numpy(lin: np.ndarray) -> np.ndarray:
    """Lineal float32 -> sRGB uint8 vía LUT de 12 bits."""
    idx = np.clip(lin, 0.0, 1.0)
    idx *= 4095.0
    idx += 0.5
    return ENCODE_LUT[idx.astype(np.uint16)]


def proxy_size(w: int, h: int) -> tuple[int, int]:
    scale = PROXY_LONG_EDGE / max(w, h)
    return max(1, round(w * scale)), max(1, round(h * scale))


def sharpen_sigma(width: int) -> float:
    """Sigma proporcional a la resolución para que preview y export se vean igual."""
    return SHARPEN_SIGMA_FULL * width / 6000


def gaussian_kernel(sigma: float) -> np.ndarray:
    radius = max(1, int(np.ceil(3 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    k = np.exp(-(x**2) / (2 * sigma**2))
    return (k / k.sum()).astype(np.float32)


# ======================================================================= Pillow + numpy
class PillowNumpy:
    """Pillow para E/S y redimensionado; numpy (un solo hilo) para la matemática."""

    name = "pillow"

    @staticmethod
    def load_proxy(path: Path) -> np.ndarray:
        from PIL import Image

        with Image.open(path) as im:
            target = proxy_size(*im.size)
            im.draft("RGB", target)  # escalado DCT del JPEG: decodifica a 1/2, 1/4 u 1/8
            im = im.convert("RGB").resize(target, Image.Resampling.LANCZOS)
            return DECODE_LUT[np.asarray(im)]

    @staticmethod
    def load_full(path: Path) -> np.ndarray:
        from PIL import Image

        with Image.open(path) as im:
            return DECODE_LUT[np.asarray(im.convert("RGB"))]

    @staticmethod
    def from_array(arr: np.ndarray) -> np.ndarray:
        return arr.copy()

    @staticmethod
    def apply(img: np.ndarray, chain: list[Op]) -> np.ndarray:
        h, w, _ = img.shape
        for op in chain:
            if op.name == "exposure":
                img = img * np.float32(2**op.value)
            elif op.name == "white_balance":
                img = img * np.asarray(op.value, dtype=np.float32)
            elif op.name == "contrast":
                img = np.power(np.maximum(img, 0) / PIVOT, np.float32(op.value)) * np.float32(PIVOT)
            elif op.name == "saturation":
                luma = (img @ REC709)[..., None]
                img = luma + np.float32(op.value) * (img - luma)
            elif op.name == "sharpen":
                k = gaussian_kernel(sharpen_sigma(w))
                r = len(k) // 2
                pad = np.pad(img, ((r, r), (r, r), (0, 0)), mode="edge")
                tmp = np.zeros((h + 2 * r, w, 3), dtype=np.float32)
                for i, kv in enumerate(k):
                    tmp += kv * pad[:, i : i + w]
                blur = np.zeros_like(img)
                for i, kv in enumerate(k):
                    blur += kv * tmp[i : i + h]
                img = img + np.float32(op.value) * (img - blur)
            elif op.name == "vignette":
                ry = ((np.arange(h, dtype=np.float32) - (h - 1) / 2) / ((h - 1) / 2)) ** 2
                rx = ((np.arange(w, dtype=np.float32) - (w - 1) / 2) / ((w - 1) / 2)) ** 2
                mask = 1 - np.float32(op.value) * (ry[:, None] + rx[None, :]) / 2
                img = img * mask[..., None]
            else:
                raise ValueError(op.name)
        return img

    @staticmethod
    def to_display(img: np.ndarray) -> np.ndarray:
        return encode_numpy(img)

    @staticmethod
    def save_jpeg(img: np.ndarray, path: Path) -> None:
        from PIL import Image

        Image.fromarray(encode_numpy(img)).save(path, quality=JPEG_QUALITY)


# ======================================================================= OpenCV
class OpenCV:
    """OpenCV (multihilo). Internamente BGR; entra/sale RGB para comparar con el resto."""

    name = "opencv"

    @staticmethod
    def _read(path: Path, flags: int) -> np.ndarray:
        import cv2

        # imdecode(np.fromfile) en vez de imread: imread no soporta rutas Unicode en Windows.
        return cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)

    @staticmethod
    def load_proxy(path: Path) -> np.ndarray:
        import cv2
        from PIL import Image

        with Image.open(path) as im:  # OpenCV no lee solo la cabecera; Pillow sí (~1 ms)
            w, h = im.size
        factor = 1
        while factor < 8 and max(w, h) / (factor * 2) >= PROXY_LONG_EDGE:
            factor *= 2  # escalado DCT: mayor reducción que mantenga >= 2048 px
        flag = {
            1: cv2.IMREAD_COLOR,
            2: cv2.IMREAD_REDUCED_COLOR_2,
            4: cv2.IMREAD_REDUCED_COLOR_4,
            8: cv2.IMREAD_REDUCED_COLOR_8,
        }[factor]
        img = cv2.resize(OpenCV._read(path, flag), proxy_size(w, h), interpolation=cv2.INTER_AREA)
        return DECODE_LUT[img]

    @staticmethod
    def load_full(path: Path) -> np.ndarray:
        import cv2

        return DECODE_LUT[OpenCV._read(path, cv2.IMREAD_COLOR)]

    @staticmethod
    def from_array(arr: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(arr[..., ::-1])  # RGB -> BGR

    @staticmethod
    def apply(img: np.ndarray, chain: list[Op]) -> np.ndarray:
        import cv2

        h, w, _ = img.shape
        for op in chain:
            if op.name == "exposure":
                img = cv2.multiply(img, (2**op.value,) * 3)
            elif op.name == "white_balance":
                gr, gg, gb = op.value
                img = cv2.multiply(img, (gb, gg, gr))
            elif op.name == "contrast":
                img = cv2.max(img, 0.0)
                img = cv2.pow(cv2.multiply(img, (1 / PIVOT,) * 3), op.value)
                img = cv2.multiply(img, (PIVOT,) * 3)
            elif op.name == "saturation":
                s = op.value
                luma = REC709[::-1]  # BGR
                m = (1 - s) * np.tile(luma, (3, 1)) + s * np.eye(3, dtype=np.float32)
                img = cv2.transform(img, m.astype(np.float32))
            elif op.name == "sharpen":
                blur = cv2.GaussianBlur(
                    img, (0, 0), sharpen_sigma(w), borderType=cv2.BORDER_REPLICATE
                )
                img = cv2.addWeighted(img, 1 + op.value, blur, -op.value, 0)
            elif op.name == "vignette":
                ry = ((np.arange(h, dtype=np.float32) - (h - 1) / 2) / ((h - 1) / 2)) ** 2
                rx = ((np.arange(w, dtype=np.float32) - (w - 1) / 2) / ((w - 1) / 2)) ** 2
                mask = 1 - np.float32(op.value) / 2 * (ry[:, None] + rx[None, :])
                img = cv2.multiply(img, cv2.merge([mask, mask, mask]))
            else:
                raise ValueError(op.name)
        return img

    @staticmethod
    def to_display(img: np.ndarray) -> np.ndarray:
        return encode_numpy(img)[..., ::-1]  # BGR -> RGB

    @staticmethod
    def save_jpeg(img: np.ndarray, path: Path) -> None:
        import cv2

        ok, buf = cv2.imencode(".jpg", encode_numpy(img), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        assert ok
        buf.tofile(path)


# ======================================================================= pyvips
class Vips:
    """libvips: evaluación perezosa por bloques, multihilo, shrink-on-load."""

    name = "pyvips"

    @staticmethod
    def _linear(img):  # sRGB 8 bits -> scRGB float lineal
        return img.colourspace("scrgb")

    @staticmethod
    def load_proxy(path: Path):
        import pyvips

        img = pyvips.Image.thumbnail(str(path), PROXY_LONG_EDGE, height=PROXY_LONG_EDGE)
        return Vips._linear(img).copy_memory()  # materializar: el proxy vive en RAM

    @staticmethod
    def load_full(path: Path):
        import pyvips

        return Vips._linear(pyvips.Image.new_from_file(str(path), access="sequential"))

    @staticmethod
    def from_array(arr: np.ndarray):
        import pyvips

        return pyvips.Image.new_from_array(np.ascontiguousarray(arr)).copy(interpretation="scrgb")

    @staticmethod
    def apply(img, chain: list[Op]):
        w, h = img.width, img.height
        for op in chain:
            if op.name == "exposure":
                img = img.linear(2**op.value, 0)
            elif op.name == "white_balance":
                img = img.linear(list(op.value), [0, 0, 0])
            elif op.name == "contrast":
                scaled = img.linear(1 / PIVOT, 0)
                img = ((scaled > 0).ifthenelse(scaled, 0) ** op.value).linear(PIVOT, 0)
            elif op.name == "saturation":
                s = op.value
                m = (1 - s) * np.tile(REC709, (3, 1)) + s * np.eye(3, dtype=np.float32)
                img = img.recomb(m.tolist())
            elif op.name == "sharpen":
                blur = img.gaussblur(sharpen_sigma(w), precision="float", min_ampl=0.01)
                img = img.linear(1 + op.value, 0) - blur.linear(op.value, 0)
            elif op.name == "vignette":
                import pyvips

                xy = pyvips.Image.xyz(w, h)
                rx = ((xy[0] - (w - 1) / 2) / ((w - 1) / 2)) ** 2
                ry = ((xy[1] - (h - 1) / 2) / ((h - 1) / 2)) ** 2
                img = img * (1 - op.value / 2 * (rx + ry))
            else:
                raise ValueError(op.name)
        return img.copy(interpretation="scrgb")

    @staticmethod
    def _to_srgb(img):
        return img.colourspace("srgb").cast("uchar")

    @staticmethod
    def to_display(img) -> np.ndarray:
        return Vips._to_srgb(img).numpy()

    @staticmethod
    def save_jpeg(img, path: Path) -> None:
        Vips._to_srgb(img).jpegsave(str(path), Q=JPEG_QUALITY)


BACKENDS = {b.name: b for b in (PillowNumpy, OpenCV, Vips)}
