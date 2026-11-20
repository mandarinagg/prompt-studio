import json

import pytest

from pstudio import recent


def _proj(tmp_path, name):
    p = tmp_path / f"{name}.pstudio"
    p.mkdir()
    (p / "project.json").write_text("{}")
    return p


def test_config_dir_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PSTUDIO_CONFIG_DIR", str(tmp_path / "cfg"))
    assert recent.config_dir() == tmp_path / "cfg"


def test_touch_lists_most_recent_first(tmp_path):
    a, b = _proj(tmp_path, "A"), _proj(tmp_path, "B")
    recent.touch(a, "A")
    recent.touch(b, "B")
    items = recent.list_recent()
    assert [i.name for i in items] == ["B", "A"]
    assert all(i.exists for i in items)
    assert items[0].path == str(b.resolve())


def test_touch_again_moves_to_top_without_duplicate(tmp_path):
    a, b = _proj(tmp_path, "A"), _proj(tmp_path, "B")
    recent.touch(a, "A")
    recent.touch(b, "B")
    recent.touch(tmp_path / "A.pstudio" / ".." / "A.pstudio", "A")
    assert [i.name for i in recent.list_recent()] == ["A", "B"]


def test_keeps_at_most_ten(tmp_path):
    for n in range(12):
        recent.touch(_proj(tmp_path, f"P{n}"), f"P{n}")
    items = recent.list_recent()
    assert len(items) == recent.MAX_RECENT == 10
    assert items[0].name == "P11" and items[-1].name == "P2"


def test_missing_project_is_flagged_not_dropped(tmp_path):
    a = _proj(tmp_path, "A")
    recent.touch(a, "A")
    (a / "project.json").unlink()
    a.rmdir()
    [item] = recent.list_recent()
    assert item.exists is False


def test_forget(tmp_path):
    a, b = _proj(tmp_path, "A"), _proj(tmp_path, "B")
    recent.touch(a, "A")
    recent.touch(b, "B")
    recent.forget(str(a))
    assert [i.name for i in recent.list_recent()] == ["B"]
    recent.forget(str(tmp_path / "nunca"))  # no existe: no hace nada


@pytest.mark.parametrize(
    "content", ["{no es json", '{"version": 1, "items": 3}', "[]", '{"items": [{"x": 1}]}']
)
def test_damaged_file_reads_as_empty(content):
    recent.config_dir().mkdir(parents=True, exist_ok=True)
    (recent.config_dir() / recent.RECENT_FILE).write_text(content, encoding="utf-8")
    assert recent.list_recent() == []


def test_file_is_versioned_json(tmp_path):
    recent.touch(_proj(tmp_path, "A"), "A")
    data = json.loads((recent.config_dir() / recent.RECENT_FILE).read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["items"][0]["name"] == "A"
    assert "opened_at" in data["items"][0]


def test_unreadable_file_is_not_overwritten(tmp_path, monkeypatch):
    # Un bloqueo momentáneo (antivirus) no debe borrar los otros recientes al abrir uno.
    a, b = _proj(tmp_path, "A"), _proj(tmp_path, "B")
    recent.touch(a, "A")
    file = recent.config_dir() / recent.RECENT_FILE
    before = file.read_text(encoding="utf-8")
    real = type(file).read_text

    def locked(self, *args, **kwargs):
        if self == file:
            raise PermissionError(13, "bloqueado")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(type(file), "read_text", locked)
    with pytest.raises(PermissionError):
        recent.touch(b, "B")
    with pytest.raises(PermissionError):
        recent.forget(str(a))
    monkeypatch.undo()
    assert file.read_text(encoding="utf-8") == before


def test_exists_requires_project_file(tmp_path):
    a = _proj(tmp_path, "A")
    b = _proj(tmp_path, "B")
    (b / "project.json").unlink()  # carpeta sin project.json
    recent.touch(a, "A")
    recent.touch(b, "B")
    assert {i.name: i.exists for i in recent.list_recent()} == {"A": True, "B": False}
