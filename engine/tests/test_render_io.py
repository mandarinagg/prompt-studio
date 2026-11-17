import os

import numpy as np
import pytest
import pyvips
from imaging import fixture, pixels, synthetic_rgb, to_vips

from pstudio.render import (
    OriginalProtectedError,
    decode,
    encode,
    sha256_file,
)
from pstudio.render.io import icc_description

PHOTOS = [
    "backlit-tree", "candle-lowlight", "daylight-landscape", "product-white",
    "stage-portrait", "starry-night-noise", "warm-living-room", "warm-restaurant",
]  # fmt: skip


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "orig.png"
    to_vips(synthetic_rgb()).write_to_file(str(path))
    return path


# ------------------------------------------------------------------------ decode
def test_decode_gives_linear_float_scrgb(png):
    img, info = decode(png)
    assert img.format == "float" and img.interpretation == "scrgb" and img.bands == 3
    assert (info.width, info.height, info.format, info.bit_depth) == (256, 192, "png", 8)
    assert info.profile == "none" and not info.has_alpha
    assert info.sha256 == sha256_file(png)
    # sRGB 255 → lineal 1.0; sRGB 128 → lineal ~0.2158 (no es una escala lineal)
    lin = to_vips(np.full((1, 1, 3), [255, 128, 0], np.uint8))
    lin.write_to_file(str(png.with_name("p.png")))
    v = decode(png.with_name("p.png"))[0].getpoint(0, 0)
    assert v == pytest.approx([1.0, 0.2158, 0.0], abs=1e-3)


def test_decode_applies_exif_orientation(tmp_path):
    path = tmp_path / "rotada.jpg"
    img = to_vips(synthetic_rgb(64, 32)).copy()
    img.set_type(pyvips.GValue.gint_type, "orientation", 6)  # 90° horario al mostrar
    img.write_to_file(str(path), Q=95)
    lin, info = decode(path)
    assert (info.width, info.height, info.orientation) == (32, 64, 6)


def test_decode_sees_file_replaced_on_disk(tmp_path):
    path = tmp_path / "cambia.png"
    to_vips(np.zeros((4, 4, 3), np.uint8)).write_to_file(str(path))
    decode(path)
    to_vips(np.full((4, 4, 3), 255, np.uint8)).write_to_file(str(path))
    img, info = decode(path)
    assert img.avg() == pytest.approx(1.0) and info.sha256 == sha256_file(path)


def test_decode_keeps_alpha(tmp_path):
    arr = np.dstack([synthetic_rgb(32, 32), np.full((32, 32), 128, np.uint8)])
    to_vips(arr).write_to_file(str(tmp_path / "a.png"))
    img, info = decode(tmp_path / "a.png")
    assert info.has_alpha and img.bands == 4
    assert img.getpoint(0, 0)[3] == pytest.approx(128 / 255, abs=1e-4)


def test_decode_16bit_tiff(tmp_path):
    arr = (synthetic_rgb().astype(np.uint16) * 257) + 3  # usa los bits bajos
    to_vips(arr, "rgb16").write_to_file(str(tmp_path / "x.tif"))
    img, info = decode(tmp_path / "x.tif")
    assert info.bit_depth == 16 and info.format == "tiff"
    out = encode(img, tmp_path / "y.tif", source=info, depth=16)
    assert np.array_equal(pixels(out), arr)  # 16 bits: ida y vuelta exacta


def test_decode_display_p3_keeps_wide_gamut(tmp_path):
    arr = np.zeros((2, 2, 3), np.uint16)
    arr[..., 0] = 65535  # rojo puro de P3: fuera de la gama sRGB
    src = to_vips(arr, "rgb16")
    lab = src.icc_import(input_profile="p3", intent="relative")
    lab.icc_export(output_profile="p3", depth=16).write_to_file(str(tmp_path / "p3.tif"))
    img, info = decode(tmp_path / "p3.tif")
    assert info.profile not in ("none", "sRGB")
    r, g, b = img.getpoint(0, 0)
    assert r > 1.2 and g < 0 and b < 0  # se conserva fuera de 0…1
    out = encode(img, tmp_path / "out.tif", source=info, color_space="Display P3", depth=16)
    assert np.abs(pixels(out).astype(int) - arr.astype(int)).max() <= 2


@pytest.mark.parametrize("name", ["x.bmp", "x.gif", "x"])
def test_decode_rejects_unsupported_extension(tmp_path, name):
    (tmp_path / name).write_bytes(b"\0" * 16)
    with pytest.raises(ValueError, match="no soportado"):
        decode(tmp_path / name)


def test_decode_rejects_mismatched_content(tmp_path):
    to_vips(synthetic_rgb(8, 8)).write_to_file(str(tmp_path / "x.gif"))
    os.replace(tmp_path / "x.gif", tmp_path / "x.png")
    with pytest.raises((ValueError, pyvips.Error)):
        decode(tmp_path / "x.png")


def test_icc_description_of_garbage_is_empty():
    assert icc_description(b"not a profile") == ""


# ------------------------------------------------------------------------ identidad
# decode → encode sin ops ≈ identidad (#10). La forma precisa de medirlo:
# - formatos sin pérdida: igualdad bit a bit, también en las 8 fotos reales;
# - formatos con pérdida: la salida es idéntica a recodificar el original directo con libvips
#   con las mismas opciones. El viaje por float32 lineal no agrega pérdida: toda la pérdida es
#   del códec. (SSIM medido de JPEG Q100 contra el original: 0.9978–0.9999 según la foto; ver
#   docs/MEDIA_PIPELINE.md. Por eso no se usa un umbral de SSIM para formatos con pérdida.)
def lossy_options(suffix: str, quality: int) -> dict:
    if suffix == ".jpg":
        return {"optimize_coding": True, "subsample_mode": "off" if quality >= 90 else "auto"}
    return {}


@pytest.mark.parametrize(
    ("suffix", "kwargs"),
    [(".png", {}), (".tif", {}), (".webp", {"quality": 100}), (".png", {"depth": 16})],
)
def test_identity_lossless_is_exact(png, tmp_path, suffix, kwargs):
    img, info = decode(png)
    out = encode(img, tmp_path / f"out{suffix}", source=info, **kwargs)
    expected = pixels(png).astype(np.uint16) * (257 if kwargs.get("depth") == 16 else 1)
    assert np.array_equal(pixels(out), expected)


@pytest.mark.parametrize(("suffix", "quality"), [(".jpg", 95), (".jpg", 80), (".webp", 90)])
def test_identity_lossy_adds_no_loss_beyond_codec(png, tmp_path, suffix, quality):
    img, info = decode(png)
    out = encode(img, tmp_path / f"out{suffix}", source=info, quality=quality)
    direct = tmp_path / f"direct{suffix}"
    opts = lossy_options(suffix, quality)
    pyvips.Image.new_from_file(str(png)).write_to_file(str(direct), Q=quality, **opts)
    assert np.array_equal(pixels(out), pixels(direct))


@pytest.mark.parametrize("name", PHOTOS)
def test_identity_real_photos(name, tmp_path):
    src = fixture(name)
    if src is None:
        pytest.skip("fixtures no descargadas (tests/fixtures/fetch_fixtures.py)")
    img, info = decode(src)
    a = pixels(src)
    # sin pérdida, sobre un recorte central (PNG de 45 MP tarda demasiado): exacto
    h, w = a.shape[:2]
    y, x = h // 2 - 512, w // 2 - 512
    crop = encode(img.crop(x, y, 1024, 1024), tmp_path / "crop.png", source=info)
    assert np.array_equal(pixels(crop), a[y : y + 1024, x : x + 1024])
    # con pérdida, la foto entera: idéntica a re-guardar el original directo
    out = encode(img, tmp_path / "out.jpg", source=info, quality=95)
    direct = tmp_path / "direct.jpg"
    original = pyvips.Image.new_from_file(str(src)).autorot()
    original.write_to_file(str(direct), Q=95, **lossy_options(".jpg", 95))
    assert np.array_equal(pixels(out), pixels(direct))
    assert sha256_file(src) == info.sha256


# ------------------------------------------------------------------------ originales
def test_never_writes_over_original(png):
    img, info = decode(png)
    before = sha256_file(png)
    with pytest.raises(OriginalProtectedError):
        encode(img, png, source=info, overwrite=True)
    with pytest.raises(OriginalProtectedError):  # misma ruta escrita de otra forma
        encode(img, png.parent / "." / png.name.upper(), source=info, overwrite=True)
    assert sha256_file(png) == before


def test_never_writes_over_hardlink_of_original(png, tmp_path):
    img, info = decode(png)
    link = tmp_path / "link.png"
    os.link(png, link)
    with pytest.raises(OriginalProtectedError):
        encode(img, link, source=info, overwrite=True)


def test_protected_paths(png, tmp_path):
    img, _ = decode(png)
    other = tmp_path / "otro_original.png"
    other.write_bytes(png.read_bytes())
    with pytest.raises(OriginalProtectedError):
        encode(img, other, protected=(other,), overwrite=True)


def test_existing_destination_needs_overwrite(png, tmp_path):
    img, info = decode(png)
    dest = encode(img, tmp_path / "out.png", source=info)
    with pytest.raises(FileExistsError):
        encode(img, dest, source=info)
    encode(img, dest, source=info, overwrite=True)


def test_no_temp_files_left_and_original_untouched(png, tmp_path):
    img, info = decode(png)
    out_dir = tmp_path / "export"
    encode(img, out_dir / "a.jpg", source=info)
    with pytest.raises(ValueError):
        encode(img, out_dir / "b.jpg", source=info, depth=16)
    assert sorted(p.name for p in out_dir.iterdir()) == ["a.jpg"]
    assert sha256_file(png) == info.sha256


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"quality": 0}, "quality"),
        ({"depth": 16}, "16 bits"),
    ],
)
def test_encode_rejects_bad_options(png, tmp_path, kwargs, message):
    img, info = decode(png)
    with pytest.raises(ValueError, match=message):
        encode(img, tmp_path / "x.jpg", source=info, **kwargs)


def test_encode_rejects_unknown_extension(png, tmp_path):
    img, info = decode(png)
    with pytest.raises(ValueError, match="extensión"):
        encode(img, tmp_path / "x.bmp", source=info)


# ------------------------------------------------------------------------ color y metadatos
def test_output_embeds_profile(png, tmp_path):
    img, info = decode(png)
    srgb = pyvips.Image.new_from_file(str(encode(img, tmp_path / "s.jpg", source=info)))
    p3 = pyvips.Image.new_from_file(
        str(encode(img, tmp_path / "p.jpg", source=info, color_space="Display P3"))
    )
    assert icc_description(srgb.get("icc-profile-data")) == "sRGB"
    assert "P3" in icc_description(p3.get("icc-profile-data"))


def test_jpeg_flattens_alpha_on_white_in_linear_light(tmp_path):
    arr = np.zeros((4, 4, 4), np.uint8)
    arr[..., 3] = 0  # negro totalmente transparente → blanco
    to_vips(arr).write_to_file(str(tmp_path / "t.png"))
    img, info = decode(tmp_path / "t.png")
    out = pixels(encode(img, tmp_path / "t.jpg", source=info, quality=95))
    assert out.shape[2] == 3 and out.min() >= 253


def test_metadata_keep_and_strip(tmp_path):
    src = fixture("warm-restaurant")
    if src is None:
        pytest.skip("fixtures no descargadas")
    img, info = decode(src)
    small = img.resize(0.1)  # metadatos intactos, export rápido
    kept = pyvips.Image.new_from_file(str(encode(small, tmp_path / "k.jpg", source=info)))
    stripped = pyvips.Image.new_from_file(
        str(encode(small, tmp_path / "s.jpg", source=info, metadata="strip"))
    )
    assert kept.get("exif-ifd0-Make") and kept.get_typeof("exif-ifd0-ImageDescription")
    assert not stripped.get_typeof("exif-data") and stripped.get_typeof("icc-profile-data")
