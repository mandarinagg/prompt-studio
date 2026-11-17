"""Preview con caché incremental por etapa (#31): misma salida que apply_plan, bit a bit."""

import numpy as np
import pytest
import pyvips
from imaging import fixture, synthetic_rgb, to_vips

from pstudio.ops import apply_plan, plan_stages
from pstudio.render import PreviewCache, Proxy, make_proxy, render_preview, sha256_file
from pstudio.render.preview import image_bytes, prefix_keys
from pstudio.schema import EditPlan

SHA = "ab" * 32

CHAIN = [  # 10 ops → 8 etapas (contrast + highlights + shadows van en una sola LUT)
    {"op": "exposure", "ev": 0.4},
    {"op": "white_balance", "temperature_shift": 15, "tint_shift": -5},
    {"op": "contrast", "amount": 20},
    {"op": "highlights", "amount": -30},
    {"op": "shadows", "amount": 25},
    {"op": "saturation", "amount": 10},
    {"op": "vibrance", "amount": 30},
    {"op": "denoise", "strength": 0.4},
    {"op": "sharpen", "amount": 40, "radius": 1.5},
    {"op": "vignette", "amount": -30},
]
AUTO_CHAIN = [
    {"op": "contrast", "amount": 15},
    {"op": "auto_exposure"},
    {"op": "shadows", "amount": 20},
    {"op": "auto_white_balance", "method": "white_patch"},
    {"op": "vibrance", "amount": 25},
    {"op": "crop", "aspect_ratio": "4:3", "anchor": "subject_or_center"},
    {"op": "denoise", "strength": 0.3},
    {"op": "sharpen", "amount": 30},
    {"op": "rotate", "degrees": 3},
    {"op": "vignette", "amount": -20},
]


def plan(ops: list[dict]) -> EditPlan:
    return EditPlan.model_validate({"operations": ops})


def changed(ops: list[dict], name: str, **params) -> list[dict]:
    return [{**o, **params} if o["op"] == name else o for o in ops]


def make(w: int = 320, h: int = 240, seed: int = 3, scale: float = 0.5, sha: str = SHA) -> Proxy:
    img = to_vips(synthetic_rgb(w, h, seed=seed)).colourspace("scrgb").cast("float")
    return Proxy((img * 0.6).copy(interpretation="scrgb").copy_memory(), sha, scale)


def same_bytes(a: pyvips.Image, b: pyvips.Image) -> bool:
    return (a.width, a.height, a.bands, a.format) == (b.width, b.height, b.bands, b.format) and (
        a.write_to_memory() == b.write_to_memory()
    )


def reference(proxy: Proxy, p: EditPlan) -> pyvips.Image:
    return apply_plan(proxy.image, p, proxy.scale)


@pytest.fixture
def proxy() -> Proxy:
    return make()


# ------------------------------------------------------------------ misma salida
@pytest.mark.parametrize(
    ("ops", "size"),
    [(CHAIN, (320, 240)), (AUTO_CHAIN, (320, 240)), (AUTO_CHAIN, (1100, 700))],
    ids=["chain", "auto", "auto-reduced"],  # 1100 px: la copia de análisis se reduce (512 px)
)
def test_cached_output_is_bit_exact(ops, size):
    proxy = make(*size)
    cache = PreviewCache()
    p = plan(ops)
    cold = render_preview(cache, proxy, p)
    warm = render_preview(cache, proxy, p)
    assert same_bytes(cold, reference(proxy, p))
    assert same_bytes(warm, cold)
    assert cache.stages_computed == len(plan_stages(p)) == cache.stages_reused


def test_empty_or_neutral_plan_returns_the_proxy(proxy):
    cache = PreviewCache()
    assert render_preview(cache, proxy, plan([])) is proxy.image
    assert render_preview(cache, proxy, plan([{"op": "contrast", "amount": 0}])) is proxy.image
    assert len(cache) == 0


# ------------------------------------------------------------------ invalidación
def test_changing_the_last_op_recomputes_only_the_last_stage(proxy):
    cache = PreviewCache()
    render_preview(cache, proxy, plan(CHAIN))
    for amount in (-60, -10, 40):
        before = cache.stages_computed
        p = plan(changed(CHAIN, "vignette", amount=amount))
        out = render_preview(cache, proxy, p)
        assert cache.stages_computed - before == 1
        assert same_bytes(out, reference(proxy, p))


def test_changing_an_intermediate_op_recomputes_from_there(proxy):
    cache = PreviewCache()
    render_preview(cache, proxy, plan(CHAIN))
    reused, computed = cache.stages_reused, cache.stages_computed
    p = plan(changed(CHAIN, "saturation", amount=-40))  # etapa 4 de 8
    out = render_preview(cache, proxy, p)
    assert (cache.stages_reused - reused, cache.stages_computed - computed) == (3, 5)
    assert same_bytes(out, reference(proxy, p))
    assert not same_bytes(out, render_preview(cache, proxy, plan(CHAIN)))
    # volver al plan anterior no recalcula nada: sigue en la caché
    assert cache.stages_computed - computed == 5


def test_changing_a_fused_curve_recomputes_its_whole_group(proxy):
    cache = PreviewCache()
    render_preview(cache, proxy, plan(CHAIN))
    before = cache.stages_computed
    p = plan(changed(CHAIN, "highlights", amount=-80))
    out = render_preview(cache, proxy, p)
    assert cache.stages_computed - before == 6  # la LUT de contrast+highlights+shadows y el resto
    assert same_bytes(out, reference(proxy, p))


def test_auto_ops_remeasure_when_something_upstream_changes(proxy):
    cache = PreviewCache()
    render_preview(cache, proxy, plan(AUTO_CHAIN))
    p = plan(changed(AUTO_CHAIN, "contrast", amount=-50))
    assert same_bytes(render_preview(cache, proxy, p), reference(proxy, p))
    before = cache.stages_computed
    p = plan(changed(AUTO_CHAIN, "vignette", amount=-70))  # después de la última automática
    assert same_bytes(render_preview(cache, proxy, p), reference(proxy, p))
    assert cache.stages_computed - before == 1


def test_entries_without_the_analysis_copy_are_not_reused_by_auto_ops(proxy):
    cache = PreviewCache()
    render_preview(cache, proxy, plan(CHAIN))  # sin ops automáticas: no se guarda la copia
    p = plan([*CHAIN, {"op": "auto_exposure"}])
    before = cache.stages_computed
    out = render_preview(cache, proxy, p)
    assert cache.stages_computed - before == len(plan_stages(p))
    assert same_bytes(out, reference(proxy, p))


def test_neutral_ops_do_not_change_the_key(proxy):
    cache = PreviewCache()
    render_preview(cache, proxy, plan(CHAIN))
    before = cache.stages_computed
    p = plan([*CHAIN[:5], {"op": "rotate", "degrees": 0}, *CHAIN[5:]])
    render_preview(cache, proxy, p)
    assert cache.stages_computed == before


def test_key_covers_source_size_scale_and_ops(proxy):
    stages = plan_stages(plan(CHAIN))
    keys = prefix_keys(proxy, stages)
    assert len(set(keys)) == len(keys) == len(stages)
    others = [
        make(sha="cd" * 32),
        make(w=322),
        make(scale=0.25),
    ]
    for other in others:
        assert not set(prefix_keys(other, stages)) & set(keys)
    edited = plan_stages(plan(changed(CHAIN, "denoise", strength=0.5)))
    new = prefix_keys(proxy, edited)
    assert new[:5] == keys[:5] and not set(new[5:]) & set(keys)


def test_different_sources_do_not_share_entries():
    cache = PreviewCache()
    a, b = make(seed=1, sha="01" * 32), make(seed=2, sha="02" * 32)
    render_preview(cache, a, plan(CHAIN))
    out = render_preview(cache, b, plan(CHAIN))
    assert same_bytes(out, reference(b, plan(CHAIN)))


# ------------------------------------------------------------------ memoria
def test_lru_eviction_keeps_memory_under_the_limit(proxy):
    entry = image_bytes(proxy.image)
    cache = PreviewCache(max_bytes=int(3.5 * entry))
    p = plan(CHAIN)
    out = render_preview(cache, proxy, p)
    assert len(cache) == 3 and cache.nbytes <= cache.max_bytes and cache.evictions == 5
    keys = prefix_keys(proxy, plan_stages(p))
    assert [k in cache for k in keys] == [False] * 5 + [True] * 3  # quedan las más recientes
    assert same_bytes(out, reference(proxy, p))
    # cambiar una op temprana: lo que falta se recalcula y la salida sigue exacta
    q = plan(changed(CHAIN, "exposure", ev=-0.3))
    assert same_bytes(render_preview(cache, proxy, q), reference(proxy, q))
    assert cache.nbytes <= cache.max_bytes


def test_reused_prefix_is_refreshed_in_lru_order(proxy):
    entry = image_bytes(proxy.image)
    cache = PreviewCache(max_bytes=9 * entry)
    render_preview(cache, proxy, plan(CHAIN))  # 8 entradas
    keys = prefix_keys(proxy, plan_stages(plan(CHAIN)))
    other = make(seed=9, sha="99" * 32)
    render_preview(cache, other, plan(CHAIN[:1]))  # 1 entrada de otro asset
    render_preview(cache, proxy, plan(changed(CHAIN, "vignette", amount=-50)))  # toca 0…6
    render_preview(cache, proxy, plan(changed(CHAIN, "vignette", amount=-55)))  # desaloja 2
    assert all(k in cache for k in keys[:7])
    assert keys[7] not in cache and prefix_keys(other, plan_stages(plan(CHAIN[:1])))[0] not in cache


def test_entries_larger_than_the_limit_are_not_stored(proxy):
    cache = PreviewCache(max_bytes=image_bytes(proxy.image) - 1)
    p = plan(CHAIN)
    out = render_preview(cache, proxy, p)
    assert len(cache) == 0 and cache.nbytes == 0
    assert same_bytes(out, reference(proxy, p))


def test_lowering_the_limit_evicts():
    proxy = make()
    cache = PreviewCache()
    render_preview(cache, proxy, plan(CHAIN))
    cache.max_bytes = 2 * image_bytes(proxy.image)
    assert len(cache) == 2 and cache.nbytes <= cache.max_bytes
    with pytest.raises(ValueError):
        PreviewCache(max_bytes=-1)
    cache.clear()
    assert len(cache) == 0 and cache.nbytes == 0


# ------------------------------------------------------------------ proxy
def test_make_proxy_reduces_and_keeps_the_verified_hash(tmp_path):
    src = tmp_path / "orig.png"
    to_vips(synthetic_rgb(600, 400, seed=5)).write_to_file(str(src))
    digest = sha256_file(src)
    proxy, info = make_proxy(src, long_side=256)
    assert (proxy.image.width, proxy.image.height) == (256, 171)
    assert proxy.image.format == "float" and proxy.image.interpretation == "scrgb"
    assert proxy.source_sha256 == info.sha256 == digest
    assert proxy.scale == pytest.approx(256 / 600)
    assert sha256_file(src) == digest  # el original no se toca
    small, _ = make_proxy(src, long_side=2048)  # más chica que el proxy: no se agranda
    assert (small.image.width, small.image.height, small.scale) == (600, 400, 1.0)


def test_real_photo_proxy_is_bit_exact():
    path = fixture("candle-lowlight")
    if path is None:
        pytest.skip("fotos de tests/fixtures no disponibles")
    proxy, _ = make_proxy(path)
    assert max(proxy.image.width, proxy.image.height) == 2048
    cache = PreviewCache()
    for ops in (CHAIN, changed(CHAIN, "sharpen", amount=80), AUTO_CHAIN):
        p = plan(ops)
        out = render_preview(cache, proxy, p)
        assert np.array_equal(out.numpy(), reference(proxy, p).numpy())
