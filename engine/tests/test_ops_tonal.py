import numpy as np
import pytest
import pyvips
from golden import check_golden, golden_input
from pydantic import TypeAdapter

from pstudio.ops import apply_op, apply_plan, implemented
from pstudio.schema import EditPlan, Operation

TONAL = ["exposure", "contrast", "highlights", "shadows", "whites", "blacks"]
LUMA = np.array([0.2126, 0.7152, 0.0722])


def op(name: str, value: float):
    field = "ev" if name == "exposure" else "amount"
    return TypeAdapter(Operation).validate_python({"op": name, field: value})


def scrgb(arr: np.ndarray) -> pyvips.Image:
    return pyvips.Image.new_from_array(arr.astype(np.float32)).copy(interpretation="scrgb")


def ramp(n: int = 512) -> pyvips.Image:
    """Grises lineales de 0 a 1 (incluye negro y blanco exactos)."""
    g = np.linspace(0, 1, n, dtype=np.float32).reshape(1, n)
    return scrgb(np.dstack([g, g, g]))


def colours(seed: int = 3) -> pyvips.Image:
    """Colores al azar, incluidos algunos fuera de gama (negativos y > 1)."""
    rng = np.random.default_rng(seed)
    arr = rng.uniform(0, 1, (32, 32, 3)) ** 2.2
    arr[0, :8] = [[1.27, -0.04, -0.02]] * 8  # rojo de P3 en scRGB
    arr[1, :8] = [[1.6, 1.4, 1.2]] * 8  # por encima del blanco difuso
    return scrgb(arr)


def luma(img: pyvips.Image) -> np.ndarray:
    return img.numpy()[..., :3] @ LUMA


AMOUNTS = {
    "exposure": [-2, -0.5, 0.5, 2],
    **{n: [-100, -50, 50, 100] for n in TONAL[1:]},
}
CASES = [(n, v) for n in TONAL for v in AMOUNTS[n]]


def test_all_tonal_ops_registered():
    assert set(TONAL) <= set(implemented())


# ------------------------------------------------------------------ neutro = identidad
@pytest.mark.parametrize("name", TONAL)
def test_neutral_is_identity(name):
    img = colours()
    assert np.array_equal(apply_op(img, op(name, 0)).numpy(), img.numpy())


# ------------------------------------------------------------------ monotonía
@pytest.mark.parametrize(("name", "value"), CASES)
def test_monotonic_on_ramp(name, value):
    y = luma(apply_op(ramp(), op(name, value)))[0]
    assert np.all(np.diff(y) >= -1e-6), f"{name} {value} invierte tonos"
    assert np.all(np.isfinite(y))


@pytest.mark.parametrize(("name", "value"), CASES)
def test_preserves_tonal_order_of_any_colour(name, value):
    img = colours()
    before, after = luma(img).ravel(), luma(apply_op(img, op(name, value))).ravel()
    order = np.argsort(before, kind="stable")
    assert np.all(np.diff(after[order]) >= -1e-5)


@pytest.mark.parametrize("name", TONAL)
def test_more_amount_means_brighter_or_more_contrast(name):
    values = AMOUNTS[name]
    imgs = [apply_op(ramp(), op(name, v)) for v in values]
    if name == "contrast":
        # más contraste = más separación tonal (desvío en escala perceptual)
        spread = [np.std(np.clip(luma(i), 0, None) ** (1 / 2.2)) for i in imgs]
        assert spread == sorted(spread)
    else:
        means = [luma(i).mean() for i in imgs]
        assert means == sorted(means), f"{name}: {means}"


# ------------------------------------------------------------------ valores y regiones
def test_exposure_is_exact_power_of_two():
    img = colours()
    out = apply_op(img, op("exposure", 1)).numpy()
    np.testing.assert_allclose(out, img.numpy() * 2, rtol=1e-6)
    out = apply_op(img, op("exposure", -2)).numpy()
    np.testing.assert_allclose(out, img.numpy() / 4, rtol=1e-6)


@pytest.mark.parametrize("value", [-100, 100])
def test_shadows_only_touch_tones_below_mid_grey(value):
    g = np.linspace(0, 1, 512)
    y = luma(apply_op(ramp(), op("shadows", value)))[0]
    above = g >= 0.18
    np.testing.assert_allclose(y[above], g[above], atol=1e-6)
    deep = (g > 0.001) & (g < 0.18 / 64)  # más de 6 EV por debajo del gris medio
    ratio = y[deep] / g[deep]
    np.testing.assert_allclose(ratio, 2.0 ** (3 * value / 100), rtol=1e-3)


@pytest.mark.parametrize(
    ("name", "fixed"),
    [
        ("contrast", [0.0, 1.0]),
        ("shadows", [0.0, 1.0]),
        ("highlights", [0.0, 1.0]),
        ("whites", [0.0]),
        ("blacks", [1.0]),
    ],
)
@pytest.mark.parametrize("value", [-100, 100])
def test_fixed_points(name, fixed, value):
    y = luma(apply_op(ramp(), op(name, value)))[0]
    ends = {0.0: y[0], 1.0: y[-1]}
    for point in fixed:
        assert ends[point] == pytest.approx(point, abs=1e-5)


def test_highlights_act_on_bright_tones_and_shadows_on_dark():
    g = np.linspace(0, 1, 512)
    hi = luma(apply_op(ramp(), op("highlights", -100)))[0] - g
    lo = luma(apply_op(ramp(), op("shadows", 100)))[0] - g
    # en escala perceptual: el mayor cambio de highlights cae en tonos altos (p > 0.6) y la
    # mayor ganancia relativa de shadows, en los más oscuros (p < 0.35)
    assert g[np.argmin(hi)] ** (1 / 2.2) > 0.6
    assert g[np.argmax(lo / np.maximum(g, 1e-9))] ** (1 / 2.2) < 0.35


def test_whites_and_blacks_move_their_endpoint():
    assert luma(apply_op(ramp(), op("whites", 100)))[0, -1] > 1.5
    assert luma(apply_op(ramp(), op("whites", -100)))[0, -1] < 0.6
    blacks_up = luma(apply_op(ramp(), op("blacks", 100)))[0]
    assert blacks_up[0] > 0.04  # el negro se levanta (efecto "desvaído")


# ------------------------------------------------------------------ color y alpha
@pytest.mark.parametrize(("name", "value"), CASES)
def test_hue_and_saturation_are_preserved(name, value):
    rng = np.random.default_rng(5)
    arr = rng.uniform(0.05, 0.6, (16, 16, 3)) ** 2.2  # sin zonas negras ni recortadas
    out = apply_op(scrgb(arr), op(name, value)).numpy()
    y_out = out @ LUMA
    keep = y_out > 1e-4  # donde no quedó negro puro (blacks −100 aplasta sombras)
    ratio_out = out[..., 0][keep] / out[..., 1][keep]
    np.testing.assert_allclose(ratio_out, (arr[..., 0] / arr[..., 1])[keep], rtol=1e-3)


@pytest.mark.parametrize("name", TONAL)
def test_alpha_is_untouched(name):
    rgb = colours().numpy()
    alpha = np.linspace(0, 1, rgb.shape[0] * rgb.shape[1]).reshape(rgb.shape[:2] + (1,))
    img = scrgb(np.concatenate([rgb, alpha], axis=-1))
    value = AMOUNTS[name][-1]
    out = apply_op(img, op(name, value))
    assert out.bands == 4 and out.format == "float" and out.interpretation == "scrgb"
    np.testing.assert_array_equal(out.numpy()[..., 3], img.numpy()[..., 3])


def test_out_of_gamut_values_stay_finite():
    img = colours()
    for name, value in CASES:
        assert np.all(np.isfinite(apply_op(img, op(name, value)).numpy())), name


# ------------------------------------------------------------------ plan
def test_apply_plan_in_order_and_unimplemented_ops_fail_loudly():
    plan = EditPlan.model_validate(
        {"operations": [{"op": "exposure", "ev": 1}, {"op": "contrast", "amount": 20}]}
    )
    img = colours()
    manual = apply_op(apply_op(img, plan.operations[0]), plan.operations[1])
    np.testing.assert_array_equal(apply_plan(img, plan).numpy(), manual.numpy())
    pending = [n for n in ("crop", "denoise", "vignette") if n not in implemented()]
    if pending:
        bad = EditPlan.model_validate(
            {"operations": [{"op": "crop", "aspect_ratio": "1:1"}]}
            if "crop" in pending
            else {"operations": [{"op": pending[0]}]}
        )
        with pytest.raises(NotImplementedError):
            apply_plan(img, bad)


# ------------------------------------------------------------------ golden images
@pytest.mark.parametrize(("name", "value"), [(n, v) for n in TONAL for v in AMOUNTS[n][::3]])
def test_golden(name, value):
    check_golden(f"{name}_{value:+g}", apply_op(golden_input(), op(name, value)))


def test_fused_plan_matches_sequential_ops():
    # apply_plan compone las curvas consecutivas en una LUT: debe dar lo mismo que de a una.
    ops = [
        {"op": "exposure", "ev": 0.3},
        {"op": "contrast", "amount": 30},
        {"op": "highlights", "amount": -60},
        {"op": "shadows", "amount": 70},
        {"op": "whites", "amount": 15},
        {"op": "blacks", "amount": -20},
    ]
    plan = EditPlan.model_validate({"operations": ops})
    img = golden_input()
    sequential = img
    for o in plan.operations:
        sequential = apply_op(sequential, o)
    fused = apply_plan(img, plan).numpy()
    np.testing.assert_allclose(fused, sequential.numpy(), atol=2e-4, rtol=1e-3)
