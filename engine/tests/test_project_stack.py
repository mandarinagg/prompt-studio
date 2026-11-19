import pytest

from pstudio.project.stack import CANONICAL_ORDER, merge, normalize
from pstudio.schema import OP_NAMES, EditPlan


def plan(*ops: dict) -> EditPlan:
    return EditPlan.model_validate({"operations": list(ops)})


def names(p: EditPlan) -> list[str]:
    return [o.op for o in p.operations]


def get(p: EditPlan, name: str):
    return next(o for o in p.operations if o.op == name)


def test_canonical_order_covers_catalog_except_resize():
    assert set(CANONICAL_ORDER) == set(OP_NAMES) - {"resize"}
    assert len(CANONICAL_ORDER) == len(set(CANONICAL_ORDER))


def test_normalize_orders_canonically():
    # EditPlan ya rechaza ops repetidas, así que normalize solo tiene que ordenar.
    p = plan(
        {"op": "vibrance", "amount": 20},
        {"op": "exposure", "ev": 0.5},
        {"op": "crop", "aspect_ratio": "1:1"},
    )
    out = normalize(p)
    assert names(out) == ["crop", "exposure", "vibrance"]
    assert get(out, "exposure").ev == 0.5


def test_normalize_drops_noops_and_resize():
    p = plan(
        {"op": "exposure", "ev": 0},
        {"op": "resize", "width": 800},
        {"op": "contrast", "amount": 10},
    )
    assert names(normalize(p)) == ["contrast"]


def test_normalize_keeps_only_operations():
    p = EditPlan.model_validate(
        {"operations": [{"op": "contrast", "amount": 10}], "source_prompt": "x", "explanation": "y"}
    )
    out = normalize(p)
    assert out.source_prompt is None and out.explanation is None


NON_NEUTRAL = {
    "straighten": {"degrees": 2},
    "rotate": {"degrees": 90},
    "crop": {"aspect_ratio": "1:1"},
    "denoise": {"strength": 0.5},
    "auto_white_balance": {},
    "white_balance": {"temperature_shift": 10},
    "auto_exposure": {"strength": 1.0},
    "exposure": {"ev": 0.5},
    "contrast": {"amount": 10},
    "highlights": {"amount": -10},
    "shadows": {"amount": 10},
    "whites": {"amount": 10},
    "blacks": {"amount": -10},
    "saturation": {"amount": 10},
    "vibrance": {"amount": 10},
    "sharpen": {"amount": 30},
    "vignette": {"amount": -20},
}


@pytest.mark.parametrize("name", CANONICAL_ORDER)
def test_normalize_keeps_every_canonical_op(name):
    p = plan({"op": name, **NON_NEUTRAL[name]})
    assert names(normalize(p)) == [name]


def test_merge_adds_relative_values():
    out = merge(plan({"op": "exposure", "ev": 0.3}), plan({"op": "exposure", "ev": 0.4}))
    assert get(out.stack, "exposure").ev == pytest.approx(0.7)
    assert out.export_hint is None


def test_merge_clamps_to_schema_bounds():
    out = merge(plan({"op": "exposure", "ev": 4.8}), plan({"op": "exposure", "ev": 0.4}))
    assert get(out.stack, "exposure").ev == 5.0
    out = merge(plan({"op": "saturation", "amount": 90}), plan({"op": "saturation", "amount": 30}))
    assert get(out.stack, "saturation").amount == 100
    out = merge(plan({"op": "denoise", "strength": 0.9}), plan({"op": "denoise", "strength": 0.3}))
    assert get(out.stack, "denoise").strength == 1.0
    out = merge(plan({"op": "vignette", "amount": -20}), plan({"op": "vignette", "amount": 20}))
    assert names(out.stack) == []


def test_merge_white_balance_adds_both_shifts():
    out = merge(
        plan({"op": "white_balance", "temperature_shift": 10, "tint_shift": -5}),
        plan({"op": "white_balance", "temperature_shift": 15, "tint_shift": 10}),
    )
    wb = get(out.stack, "white_balance")
    assert (wb.temperature_shift, wb.tint_shift) == (25, 5)


def test_merge_replaces_geometry_and_auto():
    out = merge(
        plan({"op": "crop", "aspect_ratio": "1:1"}), plan({"op": "crop", "aspect_ratio": "4:5"})
    )
    assert get(out.stack, "crop").aspect_ratio == "4:5"
    out = merge(
        plan({"op": "auto_exposure", "strength": 0.5}),
        plan({"op": "auto_exposure", "strength": 1.0}),
    )
    assert get(out.stack, "auto_exposure").strength == 1.0


def test_merge_moves_resize_to_export_hint():
    out = merge(EditPlan(), plan({"op": "resize", "width": 1080}, {"op": "contrast", "amount": 5}))
    assert names(out.stack) == ["contrast"]
    assert out.export_hint is not None and out.export_hint.width == 1080


def test_merge_keeps_auto_and_manual_together():
    out = merge(plan({"op": "auto_exposure", "strength": 1.0}), plan({"op": "exposure", "ev": 0.2}))
    assert names(out.stack) == ["auto_exposure", "exposure"]


def test_merge_does_not_mutate_inputs():
    a = plan({"op": "exposure", "ev": 0.3})
    merge(a, plan({"op": "exposure", "ev": 0.4}))
    assert get(a, "exposure").ev == 0.3
