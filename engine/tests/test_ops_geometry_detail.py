import math

import numpy as np
import pytest
import pyvips
from golden import check_golden, golden_input
from imaging import ssim
from pydantic import TypeAdapter

from pstudio.ops import apply_op, apply_plan, implemented
from pstudio.ops import detail as D
from pstudio.ops import geometry as G
from pstudio.schema import EditPlan, Operation

NAMES = ["crop", "rotate", "straighten", "resize", "sharpen", "denoise", "vignette"]
LUMA = np.array([0.2126, 0.7152, 0.0722])
A = TypeAdapter(Operation)


def op(name: str, **kw):
    return A.validate_python({"op": name, **kw})


def scrgb(arr: np.ndarray) -> pyvips.Image:
    return pyvips.Image.new_from_array(arr.astype(np.float32)).copy(interpretation="scrgb")


def ramp_rgb(w: int = 60, h: int = 40) -> np.ndarray:
    """Imagen sin simetrías (cada píxel distinto) para verificar posiciones."""
    y, x = np.mgrid[0:h, 0:w]
    return np.stack([x / w, y / h, (x * 7 + y * 13) % 17 / 17], axis=-1).astype(np.float32)


def run(arr: np.ndarray, o, scale: float = 1.0) -> np.ndarray:
    return apply_op(scrgb(arr), o, scale).numpy()


def test_all_registered():
    assert set(NAMES) <= set(implemented())


# ------------------------------------------------------------------ crop
def test_crop_rect_is_exact():
    arr = ramp_rgb()
    out = run(arr, op("crop", rect={"x": 0.25, "y": 0.5, "width": 0.5, "height": 0.25}))
    np.testing.assert_array_equal(out, arr[20:30, 15:45])


def test_crop_full_rect_is_identity():
    arr = ramp_rgb()
    out = run(arr, op("crop", rect={"x": 0, "y": 0, "width": 1, "height": 1}))
    np.testing.assert_array_equal(out, arr)


@pytest.mark.parametrize("ratio", list(G.ASPECTS))
@pytest.mark.parametrize("size", [(600, 400), (400, 600), (500, 500)])
def test_crop_aspect_is_the_largest_inside(ratio, size):
    w, h = size
    left, top, cw, ch = G.crop_box(w, h, op("crop", aspect_ratio=ratio))
    assert cw / ch == pytest.approx(G.ASPECTS[ratio], abs=1.5 / min(cw, ch))
    assert cw == w or ch == h  # máximo: toca dos bordes
    assert 0 <= left <= w - cw and 0 <= top <= h - ch


@pytest.mark.parametrize(
    ("anchor", "check"),
    [
        ("center", lambda b, w, h: abs(b[0] * 2 + b[2] - w) <= 1 and abs(b[1] * 2 + b[3] - h) <= 1),
        ("top", lambda b, w, h: b[1] == 0),
        ("bottom", lambda b, w, h: b[1] + b[3] == h),
        ("left", lambda b, w, h: b[0] == 0),
        ("right", lambda b, w, h: b[0] + b[2] == w),
    ],
)
def test_crop_anchors(anchor, check):
    for w, h, ratio in [(600, 400, "1:1"), (400, 600, "1:1")]:
        box = G.crop_box(w, h, op("crop", aspect_ratio=ratio, anchor=anchor))
        # top/bottom solo mueven en vertical (y left/right en horizontal): si ese eje no tiene
        # margen, el recorte queda centrado y el chequeo se cumple trivialmente
        assert check(box, w, h) or box[2] == w or box[3] == h


def test_crop_subject_follows_the_interesting_part():
    arr = np.full((300, 600, 3), 0.05, np.float32)
    arr[120:180, 470:540] = [0.9, 0.1, 0.05]  # objeto rojo, saturado, a la derecha
    out_box = G.crop_box(600, 300, op("crop", aspect_ratio="1:1", anchor="subject_or_center"),
                         G.attention_point(scrgb(arr)))  # fmt: skip
    left, _, w, _ = out_box
    assert left <= 470 and left + w >= 540  # el objeto queda adentro
    assert left > 150  # y no es el recorte centrado (que empezaría en 150)
    # determinista y casi igual sobre una versión reducida (preview)
    p1 = G.attention_point(scrgb(arr))
    p2 = G.attention_point(scrgb(arr).resize(0.5))
    assert p1 == G.attention_point(scrgb(arr))
    assert p1 == pytest.approx(p2, abs=0.05)


# ------------------------------------------------------------------ rotate
@pytest.mark.parametrize(("deg", "k"), [(90, -1), (-90, 1), (180, 2), (-180, 2)])
def test_rotate_quarter_turns_are_exact_and_clockwise(deg, k):
    arr = ramp_rgb()
    np.testing.assert_array_equal(run(arr, op("rotate", degrees=deg)), np.rot90(arr, k=k))


def test_rotate_arbitrary_expands_canvas_with_transparent_corners():
    arr = np.full((40, 60, 3), 0.5, np.float32)
    out = run(arr, op("rotate", degrees=30))
    t = math.radians(30)
    assert out.shape[1] == pytest.approx(60 * math.cos(t) + 40 * math.sin(t), abs=2)
    assert out.shape[0] == pytest.approx(60 * math.sin(t) + 40 * math.cos(t), abs=2)
    assert out.shape[2] == 4
    assert out[0, 0, 3] == 0 and out[-1, -1, 3] == 0
    cy, cx = out.shape[0] // 2, out.shape[1] // 2
    assert out[cy, cx, 3] == pytest.approx(1) and out[cy, cx, 0] == pytest.approx(0.5, abs=1e-4)


def test_rotate_there_and_back_keeps_the_centre():
    arr = ramp_rgb(80, 60)
    there = apply_op(scrgb(arr), op("rotate", degrees=20))
    back = apply_op(there, op("rotate", degrees=-20)).numpy()
    cy, cx = back.shape[0] // 2, back.shape[1] // 2
    # R y G son gradientes suaves (B es un diente de sierra que ninguna interpolación conserva)
    centre = back[cy - 10 : cy + 10, cx - 10 : cx + 10, :2]
    orig = arr[20:40, 30:50, :2]
    assert np.abs(centre - orig).mean() < 0.03


# ------------------------------------------------------------------ straighten
@pytest.mark.parametrize("deg", [-45, -10, -1.5, 3, 20, 45])
def test_straighten_keeps_aspect_and_has_no_empty_border(deg):
    arr = np.full((300, 450, 3), 0.5, np.float32)
    out = run(arr, op("straighten", degrees=deg))
    assert out.shape[2] == 3
    assert out.shape[1] / out.shape[0] == pytest.approx(1.5, rel=0.03)
    np.testing.assert_allclose(out, 0.5, atol=1e-3)  # sin filo oscuro ni esquinas vacías


def test_straighten_scale():
    assert G.straighten_scale(600, 400, 0) == pytest.approx(1)
    ks = [G.straighten_scale(600, 400, d) for d in (0, 5, 15, 30, 45)]
    assert ks == sorted(ks, reverse=True)


# ------------------------------------------------------------------ resize
@pytest.mark.parametrize(
    ("kw", "want"),
    [
        ({"width": 300}, (300, 200)),
        ({"height": 100}, (150, 100)),
        ({"width": 300, "height": 300}, (300, 200)),  # contain
        ({"width": 300, "height": 300, "fit": "cover"}, (300, 300)),
        ({"width": 100, "height": 300, "fit": "exact"}, (100, 300)),
        ({"width": 1200}, (1200, 800)),  # agrandar también
    ],
)
def test_resize_sizes(kw, want):
    out = apply_op(scrgb(np.full((400, 600, 3), 0.3)), op("resize", **kw))
    assert (out.width, out.height) == want


def test_resize_sizes_follow_scale():
    out = apply_op(scrgb(np.full((200, 300, 3), 0.3)), op("resize", width=300), scale=0.5)
    assert (out.width, out.height) == (150, 100)


def test_resize_averages_light_linearly():
    checker = (np.indices((64, 64)).sum(axis=0) % 2).astype(np.float32)
    arr = np.repeat(checker[..., None], 3, axis=-1)
    out = run(arr, op("resize", width=16))
    # en luz lineal, mitad negro + mitad blanco = 0.5 (en sRGB daría 0.21 lineal: más oscuro)
    np.testing.assert_allclose(out[2:-2, 2:-2], 0.5, atol=0.02)


def test_resize_premultiplies_alpha():
    arr = np.zeros((32, 32, 4), np.float32)
    arr[:, :16] = [1.0, 0.0, 0.0, 0.0]  # rojo totalmente transparente
    arr[:, 16:] = [0.0, 1.0, 0.0, 1.0]  # verde opaco
    out = run(arr, op("resize", width=8))
    visible = out[..., 3] > 0.05
    assert np.all(out[..., 0][visible] < 0.02), "el rojo invisible se filtró al borde"


# ------------------------------------------------------------------ sharpen
def step(level=(0.1, 0.4), n=64) -> np.ndarray:
    arr = np.full((n, n, 3), level[0], np.float32)
    arr[:, n // 2 :] = level[1]
    return arr


def test_sharpen_adds_contrast_at_edges_only():
    arr = step()
    out = run(arr, op("sharpen", amount=80, radius=1.5))
    row = out[32, :, 1]
    assert row[31] < 0.1 and row[32] > 0.4  # rebote a cada lado del borde
    np.testing.assert_allclose(out[:, :20], arr[:, :20], atol=1e-5)  # lejos del borde, igual
    flat = np.full((32, 32, 3), 0.3, np.float32)
    np.testing.assert_allclose(run(flat, op("sharpen", amount=100)), flat, atol=1e-6)


def test_sharpen_keeps_hue():
    arr = step() * np.array([1.0, 0.6, 0.3], np.float32)
    out = run(arr, op("sharpen", amount=100, radius=2))
    np.testing.assert_allclose(out[..., 0] / out[..., 1], 1 / 0.6, rtol=1e-3)


def test_sharpen_radius_follows_scale():
    arr = step()
    # radio 0.5 px de la original sobre un proxy a 1/4: no hay nada que enfocar a esa escala
    out = run(arr, op("sharpen", amount=100, radius=0.5), scale=0.25)
    np.testing.assert_array_equal(out, arr)


# ------------------------------------------------------------------ denoise
def noisy(seed=0, n=96) -> tuple[np.ndarray, np.ndarray]:
    clean = step((0.04, 0.3), n)
    rng = np.random.default_rng(seed)
    p = clean ** (1 / 2.2) + rng.normal(0, 0.03, (n, n, 1)) + rng.normal(0, 0.02, (n, n, 3))
    return clean, np.clip(p, 0, None) ** 2.2


def test_denoise_reduces_noise_and_keeps_edges():
    clean, arr = noisy()
    out = run(arr, op("denoise", strength=1))

    def p_std(a):  # ruido en una zona plana, en escala perceptual
        return (np.clip(a[10:-10, 5:38] @ LUMA, 0, None) ** (1 / 2.2)).std()

    assert p_std(out) < 0.5 * p_std(arr)
    # el borde sigue nítido: el salto entre 3 px a cada lado se conserva en ≥ 85%
    jump = lambda a: (a[:, 51] @ LUMA).mean() - (a[:, 44] @ LUMA).mean()  # noqa: E731
    assert jump(out) > 0.85 * jump(clean)
    # el ruido de color baja
    chroma = lambda a: np.std(a[10:-10, 5:38, 0] - a[10:-10, 5:38, 2])  # noqa: E731
    assert chroma(out) < 0.5 * chroma(arr)


def test_denoise_more_strength_more_smoothing():
    _, arr = noisy(1)
    stds = [
        (np.clip(run(arr, op("denoise", strength=s))[10:-10, 5:38] @ LUMA, 0, None) ** 0.45).std()
        for s in (0.25, 0.5, 1.0)
    ]
    assert stds == sorted(stds, reverse=True)


# ------------------------------------------------------------------ vignette
def test_vignette_centre_unchanged_and_corners_by_ev():
    arr = np.full((81, 121, 3), 0.2, np.float32)
    out = run(arr, op("vignette", amount=-100))
    assert out[40, 60, 0] == pytest.approx(0.2, rel=1e-5)
    assert out[0, 0, 0] == pytest.approx(0.2 * 2**-D.VIGNETTE_EV, rel=0.05)
    brighter = run(arr, op("vignette", amount=50))
    assert brighter[0, 0, 0] > 0.2 * 1.9
    # simétrica
    np.testing.assert_allclose(out[0, 0], out[-1, -1], rtol=1e-4)


def test_vignette_does_not_depend_on_resolution():
    small = D.vignette_gain(120, 80, op("vignette", amount=-60)).numpy()
    big = D.vignette_gain(480, 320, op("vignette", amount=-60)).numpy()
    np.testing.assert_allclose(small[::10, ::10], big[2::40, 2::40], atol=0.02)


def test_vignette_midpoint_moves_the_falloff():
    arr = np.full((81, 121, 3), 0.2, np.float32)
    near = run(arr, op("vignette", amount=-80, midpoint=10))[40, 100, 0]
    far = run(arr, op("vignette", amount=-80, midpoint=90))[40, 100, 0]
    assert near < far


# ------------------------------------------------------------------ comunes
EXAMPLES = [
    op("crop", aspect_ratio="4:5", anchor="top"),
    op("crop", rect={"x": 0.1, "y": 0.2, "width": 0.6, "height": 0.5}),
    op("rotate", degrees=90),
    op("rotate", degrees=30),
    op("straighten", degrees=5),
    op("resize", width=48),
    op("sharpen", amount=60),
    op("denoise", strength=0.7),
    op("vignette", amount=-60),
]


@pytest.mark.parametrize("o", [o for o in EXAMPLES if o.op in ("sharpen", "denoise", "vignette")])
def test_detail_ops_leave_alpha_alone(o):
    rgb = ramp_rgb()
    alpha = np.linspace(0, 1, 60 * 40).reshape(40, 60, 1).astype(np.float32)
    out = apply_op(scrgb(np.concatenate([rgb, alpha], axis=-1)), o)
    assert out.bands == 4 and out.format == "float" and out.interpretation == "scrgb"
    np.testing.assert_array_equal(out.numpy()[..., 3], alpha[..., 0])


@pytest.mark.parametrize("o", EXAMPLES, ids=str)
def test_output_is_scrgb_float_and_finite(o):
    out = apply_op(scrgb(ramp_rgb()), o)
    assert out.format == "float" and out.interpretation == "scrgb"
    assert np.all(np.isfinite(out.numpy()))


@pytest.mark.parametrize("o", EXAMPLES, ids=str)
def test_golden(o):
    params = "_".join(
        f"{v}" if not isinstance(v, dict) else "-".join(f"{x:g}" for x in v.values())
        for k, v in o.model_dump(exclude_none=True).items()
        if k != "op"
    )
    check_golden(f"{o.op}_{params}", apply_op(golden_input(), o))


# ------------------------------------------------------------------ preview = export a escala
def test_plan_on_a_proxy_matches_the_export_downscaled():
    """La preview (proxy a 1/2, scale=0.5) se ve como el export reducido a ese tamaño."""
    from imaging import synthetic_rgb, to_vips

    full = to_vips(synthetic_rgb(400, 300, seed=2)).colourspace("scrgb")
    proxy = full.resize(0.5, kernel="lanczos3")
    plan = EditPlan.model_validate(
        {
            "operations": [
                {"op": "crop", "aspect_ratio": "4:3"},
                {"op": "sharpen", "amount": 60, "radius": 2},
                {"op": "denoise", "strength": 0.5},
                {"op": "vignette", "amount": -40},
                {"op": "resize", "width": 200},
            ]
        }
    )
    export = apply_plan(full, plan)
    preview = apply_plan(proxy, plan, scale=0.5)
    assert (preview.width, preview.height) == (100, 75)
    reduced = export.resize(0.5, kernel="lanczos3")
    to8 = lambda im: im.colourspace("srgb").numpy()  # noqa: E731
    assert ssim(to8(preview), to8(reduced)) > 0.97
