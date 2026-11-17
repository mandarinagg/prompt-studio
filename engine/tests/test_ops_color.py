import math

import numpy as np
import pytest
import pyvips
from golden import check_golden, golden_input
from imaging import fixture
from pydantic import TypeAdapter

from pstudio.analysis import ANALYSIS_SIZE, HIST_BINS, analyze
from pstudio.ops import apply_op, implemented
from pstudio.ops import color as C
from pstudio.schema import Operation

COLOR = ["white_balance", "auto_white_balance", "saturation", "vibrance", "auto_exposure"]
LUMA = np.array([0.2126, 0.7152, 0.0722])
A = TypeAdapter(Operation)


def op(name: str, **kw):
    return A.validate_python({"op": name, **kw})


def scrgb(arr: np.ndarray) -> pyvips.Image:
    return pyvips.Image.new_from_array(arr.astype(np.float32)).copy(interpretation="scrgb")


def colours(seed: int = 3, n: int = 32) -> np.ndarray:
    rng = np.random.default_rng(seed)
    arr = rng.uniform(0, 1, (n, n, 3)) ** 2.2
    arr[0, :8] = [[1.27, -0.04, -0.02]] * 8  # rojo de P3 en scRGB
    arr[1, :8] = [[1.6, 1.4, 1.2]] * 8  # por encima del blanco difuso
    return arr


def grey_texture(level: float = 0.18, seed: int = 1, n: int = 64) -> np.ndarray:
    """Escena neutra (grises con textura) de clave ≈ `level`."""
    rng = np.random.default_rng(seed)
    g = level * 2.0 ** rng.normal(0, 0.8, (n, n))
    return np.repeat(g[..., None], 3, axis=-1)


def chroma(arr: np.ndarray) -> np.ndarray:
    y = arr[..., :3] @ LUMA
    return np.linalg.norm(arr[..., :3] - y[..., None], axis=-1)


def run(arr: np.ndarray, o) -> np.ndarray:
    return apply_op(scrgb(arr), o).numpy()


EXAMPLES = {
    "white_balance": [op("white_balance", temperature_shift=60, tint_shift=-30)],
    "auto_white_balance": [
        op("auto_white_balance"),
        op("auto_white_balance", method="white_patch"),
    ],
    "saturation": [op("saturation", amount=-60), op("saturation", amount=60)],
    "vibrance": [op("vibrance", amount=-60), op("vibrance", amount=60)],
    "auto_exposure": [op("auto_exposure")],
}
ALL = [o for ops in EXAMPLES.values() for o in ops]


def test_all_color_ops_registered():
    assert set(COLOR) <= set(implemented())


# ------------------------------------------------------------------ neutro = identidad
@pytest.mark.parametrize(
    "o",
    [
        op("white_balance"),
        op("saturation", amount=0),
        op("vibrance", amount=0),
        op("auto_exposure", strength=0),
    ],
    ids=str,
)
def test_neutral_is_identity(o):
    arr = colours()
    np.testing.assert_array_equal(run(arr, o), arr.astype(np.float32))


def test_auto_ops_leave_a_neutral_well_exposed_scene_alone():
    arr = grey_texture(0.2)
    for o in [
        op("auto_exposure"),
        op("auto_white_balance"),
        op("auto_white_balance", method="white_patch"),
    ]:
        np.testing.assert_allclose(run(arr, o), arr, rtol=1e-4, atol=1e-6, err_msg=str(o))


# ------------------------------------------------------------------ saturation / vibrance
@pytest.mark.parametrize("name", ["saturation", "vibrance"])
@pytest.mark.parametrize("amount", [-100, -40, 40, 100])
def test_saturation_and_vibrance_keep_luminance_and_greys(name, amount):
    arr = colours()
    out = run(arr, op(name, amount=amount))
    np.testing.assert_allclose(out @ LUMA, arr @ LUMA, atol=1e-5)
    grey = grey_texture()
    np.testing.assert_allclose(run(grey, op(name, amount=amount)), grey, atol=1e-6)


def test_saturation_minus_100_is_black_and_white():
    out = run(colours(), op("saturation", amount=-100))
    np.testing.assert_allclose(out[..., 0], out[..., 1], atol=1e-6)
    np.testing.assert_allclose(out[..., 1], out[..., 2], atol=1e-6)


@pytest.mark.parametrize("name", ["saturation", "vibrance"])
def test_more_amount_means_more_colour(name):
    arr = np.clip(colours(), 0, 1)
    c = [chroma(run(arr, op(name, amount=a))).mean() for a in (-100, -50, 0, 50, 100)]
    assert c == sorted(c), c


def test_saturation_scales_chroma_exactly():
    arr = colours()
    out = run(arr, op("saturation", amount=50))
    np.testing.assert_allclose(chroma(out), 1.5 * chroma(arr), rtol=1e-4, atol=1e-6)


def test_vibrance_favours_muted_colours():
    muted = np.array([[[0.30, 0.22, 0.18]]])  # marrón apagado
    vivid = np.array([[[0.80, 0.05, 0.02]]])  # rojo saturado
    gain = {}
    for label, px in [("muted", muted), ("vivid", vivid)]:
        gain[label] = chroma(run(px, op("vibrance", amount=100))) / chroma(px)
    assert gain["muted"] > 1.4
    assert gain["vivid"] < 1.25 and gain["muted"] > gain["vivid"] + 0.4
    # saturation, en cambio, sube a los dos por igual
    sat = [chroma(run(px, op("saturation", amount=100))) / chroma(px) for px in (muted, vivid)]
    np.testing.assert_allclose(sat, 2.0, rtol=1e-4)


# ------------------------------------------------------------------ white_balance
@pytest.mark.parametrize("t", [-100, -30, 30, 100])
@pytest.mark.parametrize("g", [-100, 0, 100])
def test_white_balance_keeps_grey_luminance(t, g):
    grey = grey_texture()
    out = run(grey, op("white_balance", temperature_shift=t, tint_shift=g))
    np.testing.assert_allclose(out @ LUMA, grey @ LUMA, rtol=1e-5)


def test_white_balance_direction():
    grey = grey_texture()[:1, :1]

    def rgb(**kw):
        return run(grey, op("white_balance", **kw))[0, 0]

    warm, cool = rgb(temperature_shift=50), rgb(temperature_shift=-50)
    assert warm[0] / warm[2] > 1.2 and cool[0] / cool[2] < 1 / 1.2
    magenta, green = rgb(tint_shift=50), rgb(tint_shift=-50)
    assert magenta[1] < min(magenta[0], magenta[2])
    assert green[1] > max(green[0], green[2])
    # más valor, más corrimiento
    ratios = [
        rgb(temperature_shift=t)[0] / rgb(temperature_shift=t)[2] for t in (-100, -50, 50, 100)
    ]
    assert ratios == sorted(ratios)


def test_white_balance_full_range_magnitude():
    grey = grey_texture()[:1, :1]
    warm = run(grey, op("white_balance", temperature_shift=100))[0, 0]
    # ±100 corre ≈ 1 EV la relación rojo/azul (TEMP_EV está en conos)
    assert math.log2(warm[0] / warm[2]) == pytest.approx(1.0, abs=0.1)


# ------------------------------------------------------------------ auto_white_balance
CAST = np.array([1.25, 1.0, 0.7])  # luz cálida (tungsteno suave)


@pytest.mark.parametrize("method", ["gray_world", "white_patch"])
def test_auto_white_balance_removes_a_cast(method):
    scene = grey_texture(0.15) * CAST
    out = run(scene, op("auto_white_balance", method=method))
    mean = out.reshape(-1, 3).mean(axis=0)
    assert np.ptp(mean / mean.mean()) < 0.02, mean
    # la luminancia media se conserva
    assert (out @ LUMA).mean() == pytest.approx((scene @ LUMA).mean(), rel=0.03)


def test_gray_world_ignores_a_dominant_saturated_colour():
    """Media foto de una pared roja + media de grises: los grises deben seguir neutros."""
    scene = grey_texture(0.15)
    scene[:, :40] = [0.55, 0.04, 0.03]  # 62% de la imagen, rojo saturado
    out = run(scene, op("auto_white_balance"))
    grey_part = out[:, 40:].reshape(-1, 3).mean(axis=0)
    assert np.ptp(grey_part / grey_part.mean()) < 0.02, grey_part


def test_auto_white_balance_correction_is_limited():
    scene = grey_texture(0.15) * np.array([1.0, 1.0, 0.05])  # amarillo extremo
    m = C.auto_white_balance_matrix(scrgb(scene), op("auto_white_balance"))
    blue_gain = (C._RGB2LMS @ m @ C._LMS2RGB)[2, 2]
    assert blue_gain <= 2.0**C.MAX_AUTO_WB_EV * 1.05


# ------------------------------------------------------------------ auto_exposure
def key(arr: np.ndarray) -> float:
    return float(np.exp(np.log(np.maximum(arr @ LUMA, 1e-4)).mean()))


def test_auto_exposure_brightens_an_underexposed_scene_to_the_band():
    dark = grey_texture(0.03)  # 1.7 EV por debajo de KEY_LOW (el tope es MAX_AUTO_EV)
    out = run(dark, op("auto_exposure"))
    assert key(out) == pytest.approx(C.KEY_LOW, rel=0.05)


def test_auto_exposure_strength_scales_the_ev():
    img = scrgb(grey_texture(0.02))
    full = C.auto_exposure_ev(img, op("auto_exposure"))
    half = C.auto_exposure_ev(img, op("auto_exposure", strength=0.5))
    assert full > 1 and half == pytest.approx(full / 2)


def test_auto_exposure_does_not_push_bright_parts_into_clipping():
    scene = grey_texture(0.02)
    scene[:4] = 0.8  # 6% de la imagen ya bastante clara
    ev = C.auto_exposure_ev(scrgb(scene), op("auto_exposure"))
    assert 0 <= ev <= math.log2(1 / 0.8) + 1e-6


def test_auto_exposure_keeps_high_key_photos_with_deep_tones():
    product = np.full((64, 64, 3), 0.85)  # fondo blanco
    product[20:40, 20:40] = [0.3, 0.02, 0.01]  # objeto oscuro y saturado
    assert C.auto_exposure_ev(scrgb(product), op("auto_exposure")) == 0


def test_auto_exposure_darkens_a_washed_out_photo():
    washed = grey_texture(0.6) * 0.5 + 0.35
    out = run(washed, op("auto_exposure"))
    assert key(out) == pytest.approx(C.KEY_HIGH, rel=0.05)


# ------------------------------------------------------------------ comunes
@pytest.mark.parametrize("o", ALL, ids=str)
def test_alpha_is_untouched_and_format_kept(o):
    rgb = colours()
    alpha = np.linspace(0, 1, rgb.shape[0] * rgb.shape[1]).reshape(rgb.shape[:2] + (1,))
    img = scrgb(np.concatenate([rgb, alpha], axis=-1))
    out = apply_op(img, o)
    assert out.bands == 4 and out.format == "float" and out.interpretation == "scrgb"
    np.testing.assert_array_equal(out.numpy()[..., 3], img.numpy()[..., 3])


@pytest.mark.parametrize("o", ALL, ids=str)
def test_out_of_gamut_values_stay_finite(o):
    assert np.all(np.isfinite(run(colours(), o)))


@pytest.mark.parametrize("o", ALL, ids=str)
def test_golden(o):
    params = "_".join(f"{v}" for k, v in o.model_dump().items() if k != "op")
    check_golden(f"{o.op}_{params}", apply_op(golden_input(), o))


# ------------------------------------------------------------------ analizadores
def test_analysis_basic_numbers():
    arr = np.zeros((40, 50, 3))
    arr[:10] = 1.0  # 25% blanco recortado
    arr[10:20] = 0.18
    s = analyze(scrgb(arr))
    assert s.pixels == 2000
    assert s.clipped_highlights == pytest.approx(0.25)
    assert s.clipped_shadows == pytest.approx(0.5)
    assert sum(s.histogram) == pytest.approx(1.0) and len(s.histogram) == HIST_BINS
    assert s.percentiles["p1"] == 0 and s.percentiles["p99"] == pytest.approx(1.0)
    assert s.gray_world_rgb == pytest.approx((0.18, 0.18, 0.18))
    assert s.p99_unclipped == pytest.approx(0.18)


def test_analysis_ignores_transparent_pixels():
    rgb = np.full((20, 20, 3), 0.18)
    rgb[:, :10] = [0.9, 0.0, 0.0]
    alpha = np.ones((20, 20, 1))
    alpha[:, :10] = 0
    s = analyze(scrgb(np.concatenate([rgb, alpha], axis=-1)))
    assert s.pixels == 200
    assert s.gray_world_rgb == pytest.approx((0.18, 0.18, 0.18))


def test_analysis_is_deterministic_and_resolution_independent():
    # contenido suave, como una foto (con ruido por píxel, promediar bloques cambia la media
    # geométrica; en las fotos de tests/fixtures preview y export difieren ≤ 3% en la clave)
    y, x = np.mgrid[0:120, 0:160]
    base = np.stack([x / 160, y / 120, (x + y) / 280], axis=-1) ** 2.2 * CAST + 0.01
    big = scrgb(base).resize(8, kernel="nearest")  # 1280×960: se reduce a ≤ ANALYSIS_SIZE
    small = scrgb(base).resize(3, kernel="nearest")
    a, b = analyze(big), analyze(big)
    assert a == b
    assert max(a.width, a.height) <= ANALYSIS_SIZE
    c = analyze(small)
    assert c.log_mean_luminance == pytest.approx(a.log_mean_luminance, rel=0.02)
    assert c.gray_world_rgb == pytest.approx(a.gray_world_rgb, rel=0.02)


# ------------------------------------------------------------------ fotos reales
def test_auto_exposure_on_real_photos():
    from pstudio.render import decode

    cases = {"product-white": 0.0, "daylight-landscape": 0.0}
    paths = {n: fixture(n) for n in [*cases, "warm-living-room"]}
    if None in paths.values():
        pytest.skip("fotos de tests/fixtures no descargadas")
    for name, want in cases.items():
        img, _ = decode(paths[name])
        assert C.auto_exposure_ev(img, op("auto_exposure")) == want, name
    img, _ = decode(paths["warm-living-room"])
    assert C.auto_exposure_ev(img, op("auto_exposure")) > 0.3


# ------------------------------------------------------------------ CLI
def test_cli_analyze(tmp_path, capsys):
    import json

    from imaging import synthetic_rgb, to_vips

    from pstudio import main
    from pstudio.render import sha256_file

    path = tmp_path / "foto ñ.png"
    to_vips(synthetic_rgb(64, 48)).write_to_file(str(path))
    before = sha256_file(path)
    with pytest.raises(SystemExit) as exc:
        main(["analyze", str(path)])
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 0
    assert out["source"] == {"width": 64, "height": 48} and len(out["histogram"]) == HIST_BINS
    assert sha256_file(path) == before

    (tmp_path / "roto.jpg").write_bytes(b"no es una imagen")
    with pytest.raises(SystemExit) as exc:
        main(["analyze", str(tmp_path / "roto.jpg")])
    assert exc.value.code == 2


# ------------------------------------------------------------------ plan
def test_plan_with_auto_ops_matches_op_by_op():
    """apply_plan mide las ops automáticas sobre una copia chica: debe dar casi lo mismo."""
    from imaging import synthetic_rgb, to_vips

    from pstudio.ops import apply_plan
    from pstudio.schema import EditPlan

    img = to_vips(synthetic_rgb(1200, 800, seed=4)).colourspace("scrgb")  # se reduce a 600×400
    img = scrgb(img.numpy() * 0.15 * CAST)  # oscura y con dominante: las auto actúan
    plan = EditPlan.model_validate(
        {
            "operations": [
                {"op": "contrast", "amount": 20},
                {"op": "auto_exposure"},
                {"op": "auto_white_balance"},
                {"op": "vibrance", "amount": 40},
            ]
        }
    )
    sequential = img
    for o in plan.operations:
        sequential = apply_op(sequential, o)
    fused = apply_plan(img, plan).numpy()
    diff = np.abs(fused - sequential.numpy())
    assert diff.max() < 5e-3 and diff.mean() < 5e-4, (diff.max(), diff.mean())
