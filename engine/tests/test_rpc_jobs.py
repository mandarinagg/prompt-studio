"""`job.*` por RPC (#60): export en la cola, eventos por el Notifier y bucle RPC libre."""

import json
import threading
import time
from pathlib import Path

import pytest
from test_rpc_media import Client, photo

from pstudio import jobs
from pstudio.render import sha256_file
from pstudio.rpc import ENGINE_ERROR, INVALID_PARAMS, METHOD_NOT_FOUND, handle_line
from pstudio.rpc.session import Session

FINAL = ("job.done", "job.failed")


class JobClient(Client):
    def job_events(self, job_id: str) -> list[dict]:
        return [
            e
            for e in self.events()
            if e.get("method", "").startswith("job.") and e["params"]["id"] == job_id
        ]

    def wait(self, job_id: str, timeout: float = 30) -> dict:
        """Espera el evento final del job y lo devuelve (sus `params`)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            final = [e for e in self.job_events(job_id) if e["method"] in FINAL]
            if final:
                assert len(final) == 1, final
                return final[0]
            time.sleep(0.02)
        raise AssertionError(f"el job {job_id} no terminó")


@pytest.fixture
def rpc(tmp_path):
    c = JobClient()
    c.files = [photo(tmp_path / "in" / f"f{i}.jpg", i) for i in range(2)]
    c.before = [sha256_file(f) for f in c.files]
    c("project.create", dir=str(tmp_path), name="P")
    c.ids = [a["id"] for a in c("project.import", paths=list(map(str, c.files)))["added"]]
    yield c
    c.session.close()
    assert [sha256_file(f) for f in c.files] == c.before  # nunca se tocan los originales


@pytest.fixture
def gate(monkeypatch):
    """Frena al worker antes de exportar hasta que el test haga `gate.release.set()`."""
    real = jobs.export_copies

    class Gate:
        entered = threading.Event()
        release = threading.Event()
        protected: tuple[Path, ...] = ()

    def held(*args, **kwargs):
        Gate.protected = kwargs["protected"]
        Gate.entered.set()
        assert Gate.release.wait(30)
        return real(*args, **kwargs)

    monkeypatch.setattr(jobs, "export_copies", held)
    yield Gate
    Gate.release.set()


def test_export_returns_queued_then_events_arrive(rpc):
    bright = {"operations": [{"op": "exposure", "ev": 1}]}
    rpc("asset.set_stack", asset=rpc.ids[0], stack=bright, label="x")
    project_dir = Path(rpc("project.info")["path"])
    info = rpc("job.export", assets=rpc.ids, preset="web")
    assert info["status"] == "queued" and info["total"] == 2 and info["kind"] == "export"
    assert Path(info["out_dir"]) == project_dir.parent / "Exportadas"
    final = rpc.wait(info["id"])
    assert final["method"] == "job.done"
    done = final["params"]
    assert done["status"] == "done" and done["done"] == 2 and done["fraction"] == 1
    assert [r["asset"] for r in done["results"]] == rpc.ids
    paths = [Path(r["path"]) for r in done["results"]]
    assert all(p.is_file() and p.parent == project_dir.parent / "Exportadas" for p in paths)
    assert [p.stem for p in paths] == ["f0_web", "f1_web"]
    progress = [e for e in rpc.job_events(info["id"]) if e["method"] == "job.progress"]
    assert progress and progress[0]["params"]["status"] == "running"


def test_rpc_loop_answers_while_a_job_runs(rpc, gate):
    info = rpc("job.export", assets=[rpc.ids[0]])
    assert gate.entered.wait(10)
    # El job está ocupado: el bucle sigue respondiendo.
    assert rpc("ping") == "pong"
    r = rpc("preview.render", asset=rpc.ids[1], long_side=256)
    assert Path(r["path"]).is_file()
    running = {j["id"]: j for j in rpc("job.list")["jobs"]}[info["id"]]
    assert running["status"] == "running"
    gate.release.set()
    assert rpc.wait(info["id"])["params"]["status"] == "done"


def test_every_project_photo_is_protected(rpc, gate):
    rpc("job.export", assets=[rpc.ids[0]])
    assert gate.entered.wait(10)
    assert set(gate.protected) == {Path(f) for f in rpc.files}


def test_cancel_queued_job_and_list(rpc, gate):
    first = rpc("job.export", assets=[rpc.ids[0]])
    assert gate.entered.wait(10)
    second = rpc("job.export", assets=[rpc.ids[1]], preset="original")
    cancelled = rpc("job.cancel", job=second["id"])
    assert cancelled["status"] == "cancelled"
    final = rpc.wait(second["id"])
    assert final["method"] == "job.done" and final["params"]["status"] == "cancelled"
    listed = rpc("job.list")["jobs"]
    assert [j["id"] for j in listed] == [first["id"], second["id"]]
    assert [j["status"] for j in listed] == ["running", "cancelled"]
    gate.release.set()
    assert rpc.wait(first["id"])["params"]["status"] == "done"
    assert [j["status"] for j in rpc("job.list")["jobs"]] == ["done", "cancelled"]


def test_cancel_unknown_job_is_an_error(rpc):
    err = rpc.error("job.cancel", job="nope")
    assert err["code"] == ENGINE_ERROR and "no existe el trabajo nope" in err["message"]


def test_export_unknown_asset_is_an_error_before_queueing(rpc):
    err = rpc.error("job.export", assets=[rpc.ids[0], "nope"])
    assert err["code"] == ENGINE_ERROR
    assert rpc("job.list")["jobs"] == []


def test_export_needs_at_least_one_asset(rpc):
    assert rpc.error("job.export", assets=[])["code"] == INVALID_PARAMS


def test_export_never_overwrites_and_keeps_original(rpc):
    first = rpc.wait(rpc("job.export", assets=[rpc.ids[0]])["id"])["params"]
    path = Path(first["results"][0]["path"])
    second = rpc.wait(rpc("job.export", assets=[rpc.ids[0]])["id"])["params"]
    assert Path(second["results"][0]["path"]).stem == "f0_web_2" and path.is_file()
    assert sha256_file(rpc.files[0]) == rpc.before[0]


def test_export_to_given_folder(rpc, tmp_path):
    out = tmp_path / "otra"
    info = rpc("job.export", assets=[rpc.ids[1]], preset="original", out_dir=str(out))
    assert Path(info["out_dir"]) == out
    done = rpc.wait(info["id"])["params"]
    assert Path(done["results"][0]["path"]).parent == out


def test_export_missing_file_is_a_readable_item_error(rpc):
    rpc.files[0].rename(rpc.files[0].with_name("movida.jpg"))
    rpc.files[0] = rpc.files[0].with_name("movida.jpg")
    done = rpc.wait(rpc("job.export", assets=rpc.ids)["id"])
    assert done["method"] == "job.done"
    first, second = done["params"]["results"]
    assert first["path"] is None and "falta el archivo f0.jpg" in first["error"]
    assert second["error"] is None and Path(second["path"]).is_file()


def test_asset_export_no_longer_exists(rpc):
    err = rpc.error("asset.export", asset=rpc.ids[0])
    assert err["code"] == METHOD_NOT_FOUND


def test_session_without_notifier_still_runs_jobs(tmp_path):
    s = Session()
    f = photo(tmp_path / "in" / "a.jpg")

    def call(method, **params):
        req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return handle_line(json.dumps(req), s)["result"]

    try:
        call("project.create", dir=str(tmp_path), name="P")
        (asset,) = call("project.import", paths=[str(f)])["added"]
        info = call("job.export", assets=[asset["id"]])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            (job,) = call("job.list")["jobs"]
            if job["status"] == "done":
                break
            time.sleep(0.02)
        assert job["id"] == info["id"] and job["status"] == "done"
    finally:
        s.close()


def test_job_export_remembers_out_dir(rpc, tmp_path):
    chosen = tmp_path / "elegida"
    info = rpc("job.export", assets=[rpc.ids[0]], preset="original", out_dir=str(chosen))
    rpc.wait(info["id"])
    assert rpc("project.info")["export_dir"] == str(chosen)
    path = rpc("project.info")["path"]
    rpc("project.close")
    assert rpc("project.open", path=path)["export_dir"] == str(chosen)
    again = rpc("job.export", assets=[rpc.ids[1]], preset="original")
    assert Path(again["out_dir"]) == chosen
    done = rpc.wait(again["id"])["params"]
    assert Path(done["results"][0]["path"]).parent == chosen


def test_job_export_relative_out_dir_rejected(rpc, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    err = rpc.error("job.export", assets=[rpc.ids[0]], out_dir="relativa")
    assert err["code"] == INVALID_PARAMS
    assert err["message"] == "la carpeta destino tiene que ser una ruta completa"
    assert rpc("job.list")["jobs"] == []
    assert not Path("relativa").exists()
