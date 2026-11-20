import io
import json
import time
from pathlib import Path

import numpy as np
import pytest
import pyvips
from imaging import synthetic_rgb, to_vips

from pstudio.render import sha256_file
from pstudio.rpc import ENGINE_ERROR, INVALID_PARAMS, Notifier, handle_line
from pstudio.rpc.session import Session


def photo(path: Path, seed: int = 0, w: int = 300, h: int = 200) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_vips(synthetic_rgb(w, h, seed=seed)).write_to_file(str(path))
    return path


class Client:
    def __init__(self) -> None:
        self.out = io.StringIO()
        self.session = Session(Notifier(self.out))

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

    def events(self):
        return [json.loads(x) for x in self.out.getvalue().splitlines()]


@pytest.fixture
def rpc(tmp_path):
    c = Client()
    c.files = [photo(tmp_path / "in" / f"f{i}.jpg", i) for i in range(2)]
    c.before = [sha256_file(f) for f in c.files]
    c("project.create", dir=str(tmp_path), name="P")
    c.ids = [a["id"] for a in c("project.import", paths=list(map(str, c.files)))["added"]]
    yield c
    c.session.close()
    assert [sha256_file(f) for f in c.files] == c.before  # nunca se tocan los originales


def mean(path) -> float:
    return float(np.mean(pyvips.Image.new_from_file(str(path)).numpy()))


def test_preview_is_jpeg_in_cache(rpc):
    r = rpc("preview.render", asset=rpc.ids[0], long_side=256)
    path = Path(r["path"])
    cache = Path(rpc("project.info")["cache_dir"])
    assert path.is_file() and path.suffix == ".jpg" and cache in path.parents
    assert max(r["width"], r["height"]) <= 256
    img = pyvips.Image.new_from_file(str(path))
    assert (img.width, img.height) == (r["width"], r["height"])
    assert r["render_ms"] >= 0 and r["encode_ms"] >= 0


def test_preview_uses_given_stack_or_asset_stack(rpc):
    base = Path(rpc("preview.render", asset=rpc.ids[0])["path"])
    base_mean = mean(base)
    bright = {"operations": [{"op": "exposure", "ev": 1}]}
    draft = rpc("preview.render", asset=rpc.ids[0], stack=bright)
    assert mean(draft["path"]) > base_mean + 10
    # sin `stack` usa la pila guardada (todavía vacía)
    again = rpc("preview.render", asset=rpc.ids[0])
    assert abs(mean(again["path"]) - base_mean) < 1


def test_previews_do_not_pile_up(rpc):
    for ev in (0.1, 0.2, 0.3, 0.4, 0.5):
        rpc(
            "preview.render", asset=rpc.ids[0], stack={"operations": [{"op": "exposure", "ev": ev}]}
        )
    rpc("preview.render", asset=rpc.ids[1])
    folder = Path(rpc("project.info")["cache_dir"]) / "preview"
    assert len(list(folder.iterdir())) == 2  # una por foto


def test_preview_cache_cleared_on_open(rpc):
    r = rpc("preview.render", asset=rpc.ids[0])
    info = rpc("project.info")
    rpc("project.open", path=info["path"])
    assert not Path(r["path"]).exists()


def test_preview_missing_file(rpc):
    rpc.files[0].rename(rpc.files[0].with_name("movida.jpg"))
    err = rpc.error("preview.render", asset=rpc.ids[0])
    assert err["code"] == ENGINE_ERROR and "falta el archivo f0.jpg" in err["message"]
    rpc.files[0] = rpc.files[0].with_name("movida.jpg")


def test_preview_long_side_bounds(rpc):
    assert rpc.error("preview.render", asset=rpc.ids[0], long_side=10)["code"] == INVALID_PARAMS


def test_plan_create_with_asset_returns_draft(rpc):
    stack = {"operations": [{"op": "exposure", "ev": 0.5}]}
    rpc("asset.set_stack", asset=rpc.ids[0], stack=stack, label="x")
    r = rpc("plan.create", prompt="más luz", asset=rpc.ids[0])
    assert r["provider"] == "rules" and r["plan"]["source_prompt"] == "más luz"
    ev_plan = next(o["ev"] for o in r["plan"]["operations"] if o["op"] == "exposure")
    ev_draft = next(o["ev"] for o in r["draft"]["operations"] if o["op"] == "exposure")
    assert ev_draft == pytest.approx(min(0.5 + ev_plan, 5.0))
    # la pila guardada no cambia hasta aplicar
    assert rpc("asset.state", asset=rpc.ids[0])["stack"]["operations"] == stack["operations"]


def test_plan_create_without_asset(rpc):
    r = rpc("plan.create", prompt="blanco y negro")
    assert r["plan"]["operations"] and r["draft"] is None


def test_plan_create_rejects_cloud(rpc):
    err = rpc.error("plan.create", prompt="x", provider="cloud")
    assert err["code"] == INVALID_PARAMS


def wait_event(rpc, name, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for e in rpc.events():
            if e.get("method") == name:
                return e["params"]
        time.sleep(0.02)
    raise AssertionError(f"no llegó {name}")


def test_thumbnail_async_then_cached(rpc):
    r = rpc("thumbnail.get", asset=rpc.ids[0])
    assert r == {"asset": rpc.ids[0], "path": None}
    ev = wait_event(rpc, "thumbnail.ready")
    assert ev["asset"] == rpc.ids[0] and ev["error"] is None
    thumb = Path(ev["path"])
    assert Path(rpc("project.info")["cache_dir"]) in thumb.parents
    img = pyvips.Image.new_from_file(str(thumb))
    assert max(img.width, img.height) <= 320
    assert rpc("thumbnail.get", asset=rpc.ids[0])["path"] == str(thumb)


def test_thumbnail_missing_file_reports_error(rpc):
    rpc.files[1].rename(rpc.files[1].with_name("otra.jpg"))
    rpc("thumbnail.get", asset=rpc.ids[1])
    ev = wait_event(rpc, "thumbnail.ready")
    assert ev["path"] is None and "falta el archivo f1.jpg" in ev["error"]
    rpc.files[1] = rpc.files[1].with_name("otra.jpg")


def test_plan_create_analyzes_the_proxy_not_the_original(rpc, monkeypatch):
    # Hashear y decodificar el original en cada pedido cuesta 150–620 ms con fotos de 24–53 MP
    # (presupuesto del borrador: 150 ms). Se mide el proxy, que ya está en memoria.
    import pstudio.prompting.planner as planner
    from pstudio.analysis import analyze
    from pstudio.prompting.descriptors import describe
    from pstudio.render.io import decode

    img, info = decode(rpc.files[0])
    full = describe(analyze(img), info.width, info.height)

    def boom(path):
        raise AssertionError("no debe decodificar el original completo")

    monkeypatch.setattr(planner, "image_descriptors", boom)
    seen = {}
    real = planner.make_plan

    def spy(request, *args, **kwargs):
        seen["r"] = request
        return real(request, *args, **kwargs)

    monkeypatch.setattr(planner, "make_plan", spy)
    r = rpc("plan.create", prompt="más luz", asset=rpc.ids[0])
    assert r["plan"] is not None
    d = seen["r"].descriptors
    assert (d["width"], d["height"]) == (full["width"], full["height"])
    for key in ("mean_luminance", "exposure_ev", "median_luminance"):
        assert d[key] == pytest.approx(full[key], abs=0.05), key
    assert d["white_balance_estimate"] == full["white_balance_estimate"]


# ---------------------------------------------------------------------- plan.draft / export
def test_plan_draft_merges_over_current_stack(rpc):
    stack = {"operations": [{"op": "exposure", "ev": 0.3}]}
    rpc("asset.set_stack", asset=rpc.ids[0], stack=stack, label="x")
    plan = {"operations": [{"op": "exposure", "ev": 0.4}]}
    r = rpc("plan.draft", asset=rpc.ids[0], plan=plan)
    ev = next(o["ev"] for o in r["draft"]["operations"] if o["op"] == "exposure")
    assert ev == pytest.approx(0.7) and r["export_hint"] is None
    # no escribe nada
    assert rpc("asset.state", asset=rpc.ids[0])["stack"]["operations"] == stack["operations"]
    assert len(rpc("asset.history", asset=rpc.ids[0])["entries"]) == 2


def test_plan_draft_with_resize_returns_export_hint(rpc):
    plan = {"operations": [{"op": "resize", "width": 800}, {"op": "saturation", "amount": 10}]}
    r = rpc("plan.draft", asset=rpc.ids[0], plan=plan)
    assert r["export_hint"]["width"] == 800
    assert [o["op"] for o in r["draft"]["operations"]] == ["saturation"]


def test_asset_export_writes_a_copy_and_never_overwrites(rpc):
    bright = {"operations": [{"op": "exposure", "ev": 1}]}
    rpc("asset.set_stack", asset=rpc.ids[0], stack=bright, label="x")
    project_dir = Path(rpc("project.info")["path"])
    first = rpc("asset.export", asset=rpc.ids[0], preset="web")
    path = Path(first["path"])
    assert path.is_file() and path.parent == project_dir.parent / "Exportadas"
    assert Path(first["out_dir"]) == path.parent and first["ms"] >= 0
    assert path.stem == "f0_web"
    second = rpc("asset.export", asset=rpc.ids[0], preset="web")
    assert Path(second["path"]).stem == "f0_web_2" and path.is_file()
    assert sha256_file(rpc.files[0]) == rpc.before[0]


def test_asset_export_to_given_folder(rpc, tmp_path):
    r = rpc("asset.export", asset=rpc.ids[1], preset="original", out_dir=str(tmp_path / "otra"))
    assert Path(r["path"]).parent == tmp_path / "otra"


def test_asset_export_missing_file_is_a_readable_error(rpc):
    rpc.files[0].rename(rpc.files[0].with_name("movida.jpg"))
    err = rpc.error("asset.export", asset=rpc.ids[0])
    assert err["code"] == ENGINE_ERROR and "falta el archivo f0.jpg" in err["message"]
    rpc.files[0] = rpc.files[0].with_name("movida.jpg")
