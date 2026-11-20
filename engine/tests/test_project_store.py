import json
import shutil
from pathlib import Path

import pytest
from imaging import synthetic_rgb, to_vips

from pstudio.project import store
from pstudio.project.store import (
    ProjectError,
    add_assets,
    create,
    missing,
    open_project,
    relink,
    save,
)
from pstudio.render import sha256_file


def photo(path: Path, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_vips(synthetic_rgb(64, 48, seed=seed)).write_to_file(str(path))
    return path


@pytest.mark.parametrize("name", ["", "a/b", "a\\b", "x:y", "q?", "n" * 101, "tab\there"])
def test_create_rejects_bad_names(tmp_path, name):
    with pytest.raises(ProjectError):
        create(tmp_path, name)


def test_create_makes_folder_and_refuses_existing(tmp_path):
    path = create(tmp_path, "Verano 2026")
    assert path == tmp_path / "Verano 2026.pstudio"
    assert (path / "project.json").is_file() and (path / "cache").is_dir()
    assert open_project(path).name == "Verano 2026"
    with pytest.raises(ProjectError):
        create(tmp_path, "Verano 2026")


def test_save_open_roundtrip(tmp_path):
    path = create(tmp_path, "P")
    p = open_project(path / "project.json")
    add_assets(p, [photo(tmp_path / "in" / "a.jpg")])
    save(path, p)
    assert open_project(path) == p


def test_save_is_atomic(tmp_path, monkeypatch):
    path = create(tmp_path, "P")
    before = (path / "project.json").read_bytes()
    p = open_project(path)
    p.name = "Cambiado"

    def boom(*_args, **_kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        save(path, p)
    assert (path / "project.json").read_bytes() == before


def test_open_rejects_corrupt_and_future_versions(tmp_path):
    path = create(tmp_path, "P")
    file = path / "project.json"
    good = file.read_text(encoding="utf-8")

    file.write_text(good[: len(good) // 2], encoding="utf-8")
    before = sha256_file(file)
    with pytest.raises(ProjectError, match="dañado"):
        open_project(path)
    assert sha256_file(file) == before

    data = json.loads(good)
    data["schema_version"] = "9.0"
    file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectError, match="versión"):
        open_project(path)

    with pytest.raises(ProjectError, match="no existe"):
        open_project(tmp_path / "nada.pstudio")


def test_add_skips_duplicates_by_hash(tmp_path):
    p = open_project(create(tmp_path, "P"))
    a = photo(tmp_path / "in" / "a.jpg")
    copy = tmp_path / "otra" / "a_copia.jpg"
    copy.parent.mkdir()
    shutil.copy(a, copy)
    note = tmp_path / "in" / "nota.txt"
    note.write_text("hola")
    result = add_assets(p, [a, copy, note])
    assert len(result.added) == 1
    assert result.duplicates == [copy.resolve()]
    assert result.unsupported == [note.resolve()]
    again = add_assets(p, [a])
    assert again.added == [] and again.duplicates == [a.resolve()]
    assert len(p.assets) == 1
    asset = p.assets[0]
    assert Path(asset.path) == a.resolve() and asset.sha256 == sha256_file(a)


def test_add_folder_recursive_in_order(tmp_path):
    p = open_project(create(tmp_path, "P"))
    folder = tmp_path / "in"
    photo(folder / "b.PNG", 1)
    photo(folder / "a.jpg", 2)
    photo(folder / "sub" / "c.webp", 3)
    flat = add_assets(p, [folder])
    assert [Path(p.asset(i).path).name for i in flat.added] == ["a.jpg", "b.PNG"]
    deep = add_assets(p, [folder], recursive=True)
    assert [Path(p.asset(i).path).name for i in deep.added] == ["c.webp"]


def test_add_recursive_skips_project_folders(tmp_path):
    # Un proyecto guardado junto a las fotos: su caché (miniaturas .jpg) no son fotos del usuario.
    folder = tmp_path / "fotos"
    photo(folder / "a.jpg", 1)
    inner = create(folder, "Viaje")
    photo(inner / "cache" / "thumbs" / "x.jpg", 2)
    p = open_project(inner)
    added = add_assets(p, [folder], recursive=True)
    assert [Path(p.asset(i).path).name for i in added.added] == ["a.jpg"]
    assert added.unsupported == []


def test_add_never_imports_from_inside_a_project(tmp_path):
    folder = tmp_path / "fotos"
    photo(folder / "a.jpg", 1)
    inner = create(folder, "Viaje")
    photo(inner / "cache" / "thumbs" / "x.jpg", 2)
    upper = folder / "Otro.PSTUDIO" / "cache"
    photo(upper / "y.jpg", 3)
    p = open_project(inner)
    deep = add_assets(p, [folder], recursive=True)
    assert [Path(p.asset(i).path).name for i in deep.added] == ["a.jpg"]
    direct = add_assets(p, [inner / "cache" / "thumbs", inner / "cache" / "thumbs" / "x.jpg"])
    assert direct.added == [] and direct.unsupported == []


def test_add_does_not_touch_originals(tmp_path):
    a = photo(tmp_path / "in" / "a.jpg")
    before = sha256_file(a)
    path = create(tmp_path, "P")
    p = open_project(path)
    add_assets(p, [a])
    save(path, p)
    assert sha256_file(a) == before


def test_missing_and_relink(tmp_path):
    p = open_project(create(tmp_path, "P"))
    a = photo(tmp_path / "in" / "a.jpg")
    other = photo(tmp_path / "in" / "b.jpg", seed=9)
    backup = tmp_path / "backup" / "a.jpg"
    backup.parent.mkdir()
    shutil.copy(a, backup)
    asset_id = add_assets(p, [a]).added[0]
    assert missing(p) == []
    a.unlink()
    assert missing(p) == [asset_id]
    with pytest.raises(ProjectError, match="no es la misma foto"):
        relink(p, asset_id, other)
    relink(p, asset_id, backup)
    assert Path(p.asset(asset_id).path) == backup.resolve()
    assert missing(p) == []
