from datetime import UTC, datetime

import pytest

from pstudio.project.history import MAX_ENTRIES, jump, push, redo, undo, undo_group
from pstudio.schema import Asset, EditPlan, Project


def ev(value: float) -> EditPlan:
    return EditPlan.model_validate({"operations": [{"op": "exposure", "ev": value}]})


def new_asset(i: str = "a") -> Asset:
    return Asset.new(i, f"C:/fotos/{i}.jpg", 1, "0" * 64)


def current_ev(a: Asset) -> float | None:
    ops = a.stack.operations
    return ops[0].ev if ops else None


def test_push_undo_redo_cycle():
    a = new_asset()
    assert push(a, ev(0.1), "A")
    assert push(a, ev(0.2), "B")
    assert undo(a) and current_ev(a) == 0.1
    assert undo(a) and current_ev(a) is None
    assert not undo(a)
    assert redo(a) and current_ev(a) == 0.1
    assert redo(a) and current_ev(a) == 0.2
    assert not redo(a)


def test_push_after_undo_discards_redo_branch():
    a = new_asset()
    push(a, ev(0.1), "A")
    push(a, ev(0.2), "B")
    undo(a)
    push(a, ev(0.5), "C")
    assert [e.label for e in a.history] == ["Original", "A", "C"]
    assert not redo(a)


def test_push_identical_stack_is_noop():
    a = new_asset()
    push(a, ev(0.1), "A")
    assert not push(a, ev(0.1), "otra vez")
    assert not push(new_asset("b"), EditPlan(), "vacío")
    assert len(a.history) == 2


def test_push_normalizes_stack():
    a = new_asset()
    push(
        a,
        EditPlan.model_validate(
            {"operations": [{"op": "vibrance", "amount": 5}, {"op": "exposure", "ev": 0.2}]}
        ),
        "x",
    )
    assert [o.op for o in a.stack.operations] == ["exposure", "vibrance"]


def test_history_is_capped_keeping_original():
    a = new_asset()
    for i in range(250):
        push(a, ev(round(0.01 * (i + 1), 2)), f"e{i}")
    assert len(a.history) == MAX_ENTRIES == 200
    assert a.history[0].label == "Original"
    assert a.cursor == len(a.history) - 1
    assert a.history[-1].label == "e249"


def test_jump_moves_cursor_without_truncating():
    a = new_asset()
    push(a, ev(0.1), "A")
    push(a, ev(0.2), "B")
    jump(a, 0)
    assert current_ev(a) is None and len(a.history) == 3
    jump(a, 2)
    assert current_ev(a) == 0.2
    with pytest.raises(IndexError):
        jump(a, 3)


def _project(*ids: str) -> Project:
    return Project(name="P", created_at=datetime.now(UTC), assets=[new_asset(i) for i in ids])


def test_undo_group_reverts_all_assets():
    p = _project("a", "b", "c")
    for a in p.assets:
        push(a, ev(0.1), "previo")
        push(a, ev(0.5), "Lote", group_id="g1")
    result = undo_group(p, "g1")
    assert result.undone == ["a", "b", "c"] and result.skipped == []
    assert all(current_ev(a) == 0.1 for a in p.assets)


def test_undo_group_skips_assets_changed_later():
    p = _project("a", "b", "c")
    for a in p.assets:
        push(a, ev(0.5), "Lote", group_id="g1")
    push(p.asset("b"), ev(0.9), "después")
    result = undo_group(p, "g1")
    assert result.undone == ["a", "c"] and result.skipped == ["b"]
    assert current_ev(p.asset("b")) == 0.9
    assert current_ev(p.asset("a")) is None


def test_undo_group_ignores_assets_without_the_group():
    p = _project("a", "b")
    push(p.asset("a"), ev(0.5), "Lote", group_id="g1")
    result = undo_group(p, "g1")
    assert result.undone == ["a"] and result.skipped == []
