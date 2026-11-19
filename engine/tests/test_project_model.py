from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pstudio.schema import EditPlan
from pstudio.schema.project import Asset, HistoryEntry, Project, project_json_schema

SHA = "a" * 64


def _asset() -> Asset:
    return Asset.new("abc123", "C:/fotos/a.jpg", 1000, SHA)


def test_new_asset_starts_with_original_entry():
    a = _asset()
    assert len(a.history) == 1
    assert a.history[0].label == "Original"
    assert a.stack.operations == []
    assert a.cursor == 0


def test_project_roundtrip_json():
    a = _asset()
    plan = EditPlan.model_validate({"operations": [{"op": "exposure", "ev": 0.3}]})
    a.history.append(HistoryEntry(label="Exposición", stack=plan, at=datetime.now(UTC)))
    a.cursor = 1
    p = Project(name="Verano", created_at=datetime.now(UTC), assets=[a])
    again = Project.model_validate_json(p.model_dump_json())
    assert again == p
    assert again.asset("abc123").stack.operations[0].op == "exposure"


def test_cursor_out_of_range_is_invalid():
    data = _asset().model_dump()
    data["cursor"] = 5
    with pytest.raises(ValidationError):
        Asset.model_validate(data)


def test_unknown_field_rejected():
    data = _asset().model_dump()
    data["extra"] = 1
    with pytest.raises(ValidationError):
        Asset.model_validate(data)


def test_bad_sha_rejected():
    with pytest.raises(ValidationError):
        Asset.new("x", "C:/a.jpg", 1, "nothex")


def test_missing_asset_raises_keyerror_in_spanish():
    p = Project(name="P", created_at=datetime.now(UTC), assets=[])
    with pytest.raises(KeyError, match="no existe la foto zz"):
        p.asset("zz")


def test_project_json_schema_has_assets():
    assert "assets" in project_json_schema()["properties"]
