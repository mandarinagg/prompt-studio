import json
import os
from pathlib import Path

import pytest
from imaging import synthetic_rgb, to_vips

from pstudio.render import sha256_file
from pstudio.rpc import (
    ENGINE_ERROR,
    INVALID_PARAMS,
    NO_PROJECT,
    PROJECT_CHANGED,
    handle_line,
)
from pstudio.rpc.session import Session


def photo(path: Path, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_vips(synthetic_rgb(96, 64, seed=seed)).write_to_file(str(path))
    return path


class Client:
    def __init__(self) -> None:
        self.session = Session()

    def raw(self, method, **params):
        req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return handle_line(json.dumps(req), self.session)

    def __call__(self, method, **params):
        resp = self.raw(method, **params)
        assert "result" in resp, resp
        return resp["result"]

    def error(self, method, **params):
        resp = self.raw(method, **params)
        assert "error" in resp, resp
        return resp["error"]


@pytest.fixture
def rpc():
    c = Client()
    yield c
    c.session.close()


def stored(info) -> dict:
    return json.loads((Path(info["path"]) / "project.json").read_text(encoding="utf-8"))


def test_project_and_asset_round_trip(tmp_path, rpc):
    files = [photo(tmp_path / "in" / f"f{i}.jpg", i) for i in range(2)]
    before = [sha256_file(f) for f in files]

    info = rpc("project.create", dir=str(tmp_path), name="Viaje")
    assert info["name"] == "Viaje" and info["assets"] == []
    assert Path(info["cache_dir"]) == Path(info["path"]) / "cache"

    imp = rpc("project.import", paths=[*map(str, files), str(files[0])])
    assert [a["file"] for a in imp["added"]] == ["f0.jpg", "f1.jpg"]
    assert imp["duplicates"] == 1 and imp["unsupported"] == []
    asset = imp["added"][0]["id"]
    assert str(tmp_path) not in json.dumps(imp)  # sin rutas absolutas en los resúmenes

    plan = {"source_prompt": "más luz", "operations": [{"op": "exposure", "ev": 0.5}]}
    st = rpc("asset.apply_plan", asset=asset, plan=plan)
    assert st["stack"]["operations"][0]["ev"] == 0.5
    assert st["label"] == "Pedido: más luz" and st["can_undo"] and not st["can_redo"]
    assert st["changed"] is True
    st = rpc("asset.apply_plan", asset=asset, plan=plan)
    assert st["stack"]["operations"][0]["ev"] == 1.0  # suma
    assert stored(info)["assets"][0]["cursor"] == 2

    st = rpc("asset.undo", asset=asset)
    assert st["stack"]["operations"][0]["ev"] == 0.5 and st["can_redo"]
    st = rpc("asset.redo", asset=asset)
    assert st["stack"]["operations"][0]["ev"] == 1.0
    st = rpc("asset.redo", asset=asset)
    assert st["changed"] is False

    slider = {"operations": [{"op": "exposure", "ev": 0.3}, {"op": "contrast", "amount": 10}]}
    st = rpc("asset.set_stack", asset=asset, stack=slider, label="Exposición +0.3 EV")
    assert [o["op"] for o in st["stack"]["operations"]] == ["exposure", "contrast"]

    st = rpc("asset.reset", asset=asset)
    assert st["stack"]["operations"] == [] and st["label"] == "Restablecer"
    hist = rpc("asset.history", asset=asset)
    assert [e["label"] for e in hist["entries"]] == [
        "Original",
        "Pedido: más luz",
        "Pedido: más luz",
        "Exposición +0.3 EV",
        "Restablecer",
    ]
    st = rpc("asset.jump", asset=asset, index=1)
    assert st["stack"]["operations"][0]["ev"] == 0.5

    reopened = Client()
    info2 = reopened("project.open", path=info["path"])
    assert [a["edited"] for a in info2["assets"]] == [True, False]
    assert [sha256_file(f) for f in files] == before


def test_apply_plan_returns_export_hint(tmp_path, rpc):
    rpc("project.create", dir=str(tmp_path), name="P")
    asset = rpc("project.import", paths=[str(photo(tmp_path / "a.jpg"))])["added"][0]["id"]
    plan = {"operations": [{"op": "resize", "width": 800}]}
    st = rpc("asset.apply_plan", asset=asset, plan=plan)
    assert st["export_hint"]["width"] == 800 and st["changed"] is False


def test_undo_group(tmp_path, rpc):
    rpc("project.create", dir=str(tmp_path), name="P")
    files = [str(photo(tmp_path / f"{i}.jpg", i)) for i in range(2)]
    ids = [a["id"] for a in rpc("project.import", paths=files)["added"]]
    stack = {"operations": [{"op": "vibrance", "amount": 20}]}
    for i in ids:
        rpc("asset.set_stack", asset=i, stack=stack, label="Ajustes pegados", group_id="g1")
    res = rpc("asset.undo_group", group_id="g1")
    assert sorted(res["undone"]) == sorted(ids) and res["skipped"] == []


def test_without_project(rpc):
    err = rpc.error("asset.state", asset="x")
    assert err["code"] == NO_PROJECT and "no hay un proyecto abierto" in err["message"]


def test_bad_inputs(tmp_path, rpc):
    rpc("project.create", dir=str(tmp_path), name="P")
    asset = rpc("project.import", paths=[str(photo(tmp_path / "a.jpg"))])["added"][0]["id"]
    err = rpc.error(
        "asset.set_stack", asset=asset, stack={"operations": [{"op": "exec"}]}, label="x"
    )
    assert err["code"] == INVALID_PARAMS
    err = rpc.error("asset.state", asset="nada")
    assert err["code"] == ENGINE_ERROR and "no existe la foto nada" in err["message"]
    err = rpc.error("project.open", path=str(tmp_path / "otro.pstudio"))
    assert err["code"] == ENGINE_ERROR and "no existe el proyecto" in err["message"]
    assert rpc("ping") == "pong"  # el engine sigue vivo


def test_external_change_is_not_overwritten(tmp_path, rpc):
    info = rpc("project.create", dir=str(tmp_path), name="P")
    asset = rpc("project.import", paths=[str(photo(tmp_path / "a.jpg"))])["added"][0]["id"]
    # Otro programa (la terminal) cambia el proyecto mientras la app lo tiene abierto.
    pj = Path(info["path"]) / "project.json"
    data = json.loads(pj.read_text(encoding="utf-8"))
    data["name"] = "Cambiado afuera"
    pj.write_text(json.dumps(data), encoding="utf-8")
    st = os.stat(pj)
    os.utime(pj, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))

    stack = {"operations": [{"op": "exposure", "ev": 1}]}
    err = rpc.error("asset.set_stack", asset=asset, stack=stack, label="x")
    assert err["code"] == PROJECT_CHANGED
    assert json.loads(pj.read_text(encoding="utf-8"))["name"] == "Cambiado afuera"
    assert rpc("project.info")["name"] == "Cambiado afuera"  # se recargó
    st2 = rpc("asset.set_stack", asset=asset, stack=stack, label="x")  # ahora sí
    assert st2["changed"] is True


def test_relink(tmp_path, rpc):
    f = photo(tmp_path / "in" / "a.jpg")
    rpc("project.create", dir=str(tmp_path), name="P")
    asset = rpc("project.import", paths=[str(f)])["added"][0]["id"]
    moved = tmp_path / "movida" / "a.jpg"
    moved.parent.mkdir()
    f.rename(moved)
    assert rpc("project.info")["assets"][0]["missing"] is True
    assert rpc("project.relink", asset=asset, path=str(moved))["missing"] is False
    other = photo(tmp_path / "b.jpg", seed=9)
    err = rpc.error("project.relink", asset=asset, path=str(other))
    assert "no es la misma foto" in err["message"]


def test_create_requires_an_existing_folder(tmp_path, rpc, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert rpc.error("project.create", dir="", name="P")["code"] == INVALID_PARAMS
    err = rpc.error("project.create", dir=str(tmp_path / "no-existe"), name="P")
    assert err["code"] == ENGINE_ERROR and "no existe la carpeta no-existe" in err["message"]
    assert list(tmp_path.iterdir()) == []


def test_asset_id_cannot_escape_the_cache(tmp_path, rpc):
    # Un project.json editado a mano o compartido no puede llevar un id que sea una ruta.
    info = rpc("project.create", dir=str(tmp_path), name="P")
    rpc("project.import", paths=[str(photo(tmp_path / "a.jpg"))])
    pj = Path(info["path"]) / "project.json"
    data = json.loads(pj.read_text(encoding="utf-8"))
    data["assets"][0]["id"] = "../../../photo"
    pj.write_text(json.dumps(data), encoding="utf-8")
    err = Client().error("project.open", path=info["path"])
    assert "está dañado" in err["message"]


def test_failed_save_does_not_leak_into_the_next_save(tmp_path, rpc, monkeypatch):
    import pstudio.rpc.session as session_mod

    info = rpc("project.create", dir=str(tmp_path), name="P")
    asset = rpc("project.import", paths=[str(photo(tmp_path / "a.jpg"))])["added"][0]["id"]
    real_save = session_mod.save

    def locked(path, project):
        raise PermissionError(13, "Acceso denegado", str(path / "project.json"))

    monkeypatch.setattr(session_mod, "save", locked)
    stack = {"operations": [{"op": "exposure", "ev": 1}]}
    assert "error" in rpc.raw("asset.set_stack", asset=asset, stack=stack, label="x")
    monkeypatch.setattr(session_mod, "save", real_save)
    assert rpc("asset.state", asset=asset)["stack"]["operations"] == []  # se descartó
    other = {"operations": [{"op": "contrast", "amount": 10}]}
    rpc("asset.set_stack", asset=asset, stack=other, label="y")
    saved = stored(info)["assets"][0]
    assert [e["label"] for e in saved["history"]] == ["Original", "y"]


def test_failed_import_is_not_half_applied(tmp_path, rpc, monkeypatch):
    import pstudio.project.store as store

    info = rpc("project.create", dir=str(tmp_path), name="P")
    files = [str(photo(tmp_path / f"{i}.jpg", i)) for i in range(2)]
    real = store.sha256_file
    calls = []

    def flaky(path):
        calls.append(path)
        if len(calls) == 2:
            raise PermissionError(13, "Acceso denegado", str(path))
        return real(path)

    monkeypatch.setattr(store, "sha256_file", flaky)
    assert "error" in rpc.raw("project.import", paths=files)
    monkeypatch.setattr(store, "sha256_file", real)
    assert rpc("project.info")["assets"] == []
    rpc("project.import", paths=files[:1])
    assert len(stored(info)["assets"]) == 1


def test_open_and_create_register_recents(tmp_path, rpc):
    a = rpc("project.create", dir=str(tmp_path), name="A")
    rpc("project.create", dir=str(tmp_path), name="B")
    rpc("project.open", path=a["path"])
    items = rpc("recent.list")["items"]
    assert [i["name"] for i in items] == ["A", "B"]
    assert items[0]["path"] == a["path"] and items[0]["exists"] is True
    left = rpc("recent.forget", path=a["path"])["items"]
    assert [i["name"] for i in left] == ["B"]


def test_recents_write_failure_does_not_break_open(tmp_path, rpc, monkeypatch):
    blocker = tmp_path / "no-es-carpeta"
    blocker.write_text("x")
    monkeypatch.setenv("PSTUDIO_CONFIG_DIR", str(blocker / "cfg"))
    info = rpc("project.create", dir=str(tmp_path), name="A")
    assert rpc("project.open", path=info["path"])["name"] == "A"
    assert rpc("recent.list")["items"] == []


def test_close_project(tmp_path, rpc):
    rpc("project.create", dir=str(tmp_path), name="A")
    assert rpc("project.close") is None
    assert rpc.error("project.info")["code"] == NO_PROJECT
    assert rpc("project.close") is None  # sin proyecto: no hace nada


# ------------------------------------------------------------------------------------- lote
@pytest.fixture
def three(tmp_path, rpc):
    rpc("project.create", dir=str(tmp_path), name="P")
    files = [str(photo(tmp_path / f"{i}.jpg", i)) for i in range(3)]
    rpc.ids = [a["id"] for a in rpc("project.import", paths=files)["added"]]
    return rpc


@pytest.fixture
def commits(monkeypatch):
    calls = []
    real = Session.commit

    def spy(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(Session, "commit", spy)
    return calls


def _current_entries(rpc, ids):
    out = []
    for i in ids:
        h = rpc("asset.history", asset=i)
        out.append(h["entries"][h["cursor"]])
    return out


def test_apply_plan_many_groups_and_saves_once(three, commits):
    plan = {"source_prompt": "más luz", "operations": [{"op": "exposure", "ev": 0.5}]}
    commits.clear()
    res = three("asset.apply_plan_many", assets=three.ids, plan=plan)
    assert res["group_id"]
    assert [s["asset"] for s in res["states"]] == three.ids
    assert all(s["changed"] for s in res["states"])
    entries = _current_entries(three, three.ids)
    assert {e["group_id"] for e in entries} == {res["group_id"]}
    assert {e["label"] for e in entries} == {"Pedido: más luz"}
    assert len(commits) == 1


def test_apply_plan_many_unknown_id_changes_nothing(three, commits):
    plan = {"operations": [{"op": "exposure", "ev": 0.5}]}
    commits.clear()
    a, b = three.ids[0], three.ids[1]
    err = three.error("asset.apply_plan_many", assets=[a, "nope", b], plan=plan)
    assert err["code"] == ENGINE_ERROR
    for i in (a, b):
        assert three("asset.state", asset=i)["stack"]["operations"] == []
    assert commits == []


def test_apply_plan_many_raise_midway_changes_nothing(three, commits, monkeypatch):
    import pstudio.rpc.methods_project as mp

    real = mp.merge
    n = []

    def flaky(stack, plan):
        n.append(1)
        if len(n) == 2:
            raise RuntimeError("boom")
        return real(stack, plan)

    monkeypatch.setattr(mp, "merge", flaky)
    plan = {"operations": [{"op": "exposure", "ev": 0.5}]}
    commits.clear()
    err = three.error("asset.apply_plan_many", assets=three.ids, plan=plan)
    assert err["code"]
    for i in three.ids:
        assert three("asset.state", asset=i)["stack"]["operations"] == []
        assert three("asset.history", asset=i)["cursor"] == 0
    assert commits == []


def test_apply_plan_many_duplicate_ids_rejected(three, commits):
    plan = {"operations": [{"op": "exposure", "ev": 0.5}]}
    commits.clear()
    a = three.ids[0]
    err = three.error("asset.apply_plan_many", assets=[a, a], plan=plan)
    assert err["code"] == INVALID_PARAMS
    assert three("asset.state", asset=a)["stack"]["operations"] == []
    assert commits == []


def test_apply_plan_many_no_change_has_no_group(three, commits):
    commits.clear()
    res = three("asset.apply_plan_many", assets=three.ids, plan={"operations": []})
    assert res["group_id"] is None
    assert not any(s["changed"] for s in res["states"])
    assert commits == []


def test_paste_rpc_label_and_group(three):
    a, b, c = three.ids
    three("asset.set_stack", asset=b, stack={"operations": [{"op": "rotate", "degrees": 90}]},
          label="Girar")  # fmt: skip
    stack = {
        "operations": [
            {"op": "crop", "aspect_ratio": "1:1"},
            {"op": "vibrance", "amount": 20},
        ]
    }
    res = three("asset.paste", assets=[b, c], stack=stack)
    assert res["group_id"]
    ops = [[o["op"] for o in s["stack"]["operations"]] for s in res["states"]]
    assert ops == [["rotate", "vibrance"], ["vibrance"]]  # la geometría de origen no entra
    entries = _current_entries(three, [b, c])
    assert {e["label"] for e in entries} == {"Ajustes pegados"}
    assert {e["group_id"] for e in entries} == {res["group_id"]}

    res = three("asset.paste", assets=[a, b], stack=stack, geometry=True)
    ops = [[o["op"] for o in s["stack"]["operations"]] for s in res["states"]]
    assert ops == [["crop", "vibrance"], ["crop", "vibrance"]]


def test_undo_group_after_edit(three):
    plan = {"operations": [{"op": "exposure", "ev": 0.5}]}
    gid = three("asset.apply_plan_many", assets=three.ids, plan=plan)["group_id"]
    three("asset.set_stack", asset=three.ids[1], label="Después",
          stack={"operations": [{"op": "contrast", "amount": 10}]})  # fmt: skip
    res = three("asset.undo_group", group_id=gid)
    assert sorted(res["undone"]) == sorted([three.ids[0], three.ids[2]])
    assert res["skipped"] == [three.ids[1]]


def test_auto_ops_stay_auto_in_batch(three):
    plan = {"operations": [{"op": "auto_exposure"}]}
    res = three("asset.apply_plan_many", assets=three.ids, plan=plan)
    for s in res["states"]:
        assert [o["op"] for o in s["stack"]["operations"]] == ["auto_exposure"]


# ------------------------------------------------------------------------------ carpeta de export
def test_project_info_export_dir_default(tmp_path, rpc):
    info = rpc("project.create", dir=str(tmp_path), name="P")
    assert info["export_dir"] == str(Path(info["path"]).parent / "Exportadas")
