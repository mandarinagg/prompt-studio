import threading
import time
from pathlib import Path

import numpy as np
import pytest
import pyvips
from imaging import pixels, synthetic_rgb, to_vips

from pstudio import jobs
from pstudio.jobs import Cancelled, JobInfo, JobQueue
from pstudio.project.history import push
from pstudio.project.store import add_assets, create, open_project
from pstudio.render import sha256_file
from pstudio.render.io import decode, encode
from pstudio.schema import EditPlan

TIMEOUT = 60


def photo(path: Path, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_vips(synthetic_rgb(96, 64, seed=seed)).write_to_file(str(path))
    return path


def big_photo(path: Path) -> Path:
    """6000×4000 con ruido: tarda lo suficiente en codificarse como para cancelar a mitad."""
    path.parent.mkdir(parents=True, exist_ok=True)
    noise = pyvips.Image.gaussnoise(6000, 4000, mean=128, sigma=50)
    rgb = noise.bandjoin([noise.rot180(), noise.fliphor()]).cast("uchar")
    rgb.copy(interpretation="srgb").write_to_file(str(path), Q=95)
    return path


@pytest.fixture(scope="module")
def big(tmp_path_factory) -> Path:
    return big_photo(tmp_path_factory.mktemp("big") / "grande.jpg")


def setup(tmp_path: Path, files: list[Path]):
    project = open_project(create(tmp_path, "P"))
    ids = add_assets(project, files).added
    return project, [project.asset(i) for i in ids]


class Recorder:
    """Junta los eventos de la cola y permite esperar el final de un job."""

    def __init__(self) -> None:
        self.events: list[tuple[str, JobInfo]] = []
        self.cond = threading.Condition()
        self.hooks: list = []

    def __call__(self, name: str, info: JobInfo) -> None:
        for hook in self.hooks:
            hook(name, info)
        with self.cond:
            self.events.append((name, info))
            self.cond.notify_all()

    def of(self, job_id: str) -> list[tuple[str, JobInfo]]:
        with self.cond:
            return [(n, i) for n, i in self.events if i.id == job_id]

    def wait(self, job_id: str) -> tuple[str, JobInfo]:
        def final():
            return [(n, i) for n, i in self.of(job_id) if n in ("job.done", "job.failed")]

        with self.cond:
            assert self.cond.wait_for(final, timeout=TIMEOUT), "el job no terminó"
        return final()[-1]


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture
def q(rec):
    queue = JobQueue(rec)
    yield queue
    queue.close()


def outputs(folder: Path) -> list[str]:
    return sorted(f.name for f in folder.iterdir()) if folder.exists() else []


def gate(rec: Recorder) -> threading.Event:
    """Traba el worker en su primer evento hasta que el test suelte la compuerta."""
    released = threading.Event()
    first = threading.Event()

    def hook(name, info):
        if name == "job.progress" and not first.is_set():
            first.set()
            assert released.wait(TIMEOUT)

    rec.hooks.append(hook)
    return released


# ------------------------------------------------------------------ encode
def test_encode_monitor_false_cancels_without_file(tmp_path, big):
    img, info = decode(big)
    seen: list[float] = []

    def monitor(fraction: float) -> bool:
        seen.append(fraction)
        return fraction < 0.3

    dest = tmp_path / "out" / "x.jpg"
    with pytest.raises(Cancelled):
        encode(img, dest, source=info, monitor=monitor)
    assert outputs(tmp_path / "out") == []
    assert seen and all(0 <= f <= 1 for f in seen) and max(seen) < 1
    # La misma foto se puede volver a exportar (la caché de libvips no guarda la cancelada).
    img, info = decode(big)
    assert encode(img, dest, source=info, monitor=lambda f: True).is_file()
    assert sha256_file(big) == info.sha256


# ------------------------------------------------------------------ cola
def test_batch_of_three_done_with_progress(tmp_path, q, rec):
    files = [photo(tmp_path / "in" / f"f{i}.jpg", seed=i) for i in range(3)]
    before = [sha256_file(f) for f in files]
    project, assets = setup(tmp_path, files)
    out = tmp_path / "out"
    info = q.submit_export(assets, [Path(a.path) for a in assets], out, "original")
    assert info.status == "queued" and info.total == 3 and info.kind == "export"

    name, final = rec.wait(info.id)
    assert [sha256_file(f) for f in files] == before
    assert name == "job.done" and final.status == "done"
    assert final.done == 3 and final.fraction == 1 and final.error is None
    assert final.ms is not None and final.out_dir == str(out)
    paths = [Path(r.path) for r in final.results]
    assert [r.asset for r in final.results] == [a.id for a in assets]
    assert all(p.is_file() and p.parent == out for p in paths) and len(paths) == 3

    progress = [i for n, i in rec.of(info.id) if n == "job.progress"]
    assert progress and all(i.status == "running" for i in progress)
    fractions = [i.fraction for i in progress] + [final.fraction]
    assert fractions == sorted(fractions)
    dones = [i.done for i in progress]
    assert dones == sorted(dones)
    # cada cambio de foto se emite siempre
    assert [f.name for f in files] == list(dict.fromkeys(i.current for i in progress))
    assert q.list()[-1].status == "done"


def test_cancel_mid_second_photo_keeps_first(tmp_path, q, rec, big, monkeypatch):
    monkeypatch.setattr(jobs, "PROGRESS_INTERVAL", 0.0)  # cada señal de libvips → evento
    files = [photo(tmp_path / "in" / "a.jpg"), big, photo(tmp_path / "in" / "c.jpg", seed=2)]
    before = [sha256_file(f) for f in files]
    project, assets = setup(tmp_path, files)
    out = tmp_path / "out"
    cancelled = threading.Event()

    def hook(name, info):
        # a mitad de la 2.ª foto: más allá del 20 % de su parte del job
        if info.current == big.name and info.fraction > 1.2 / 3 and not cancelled.is_set():
            cancelled.set()
            q.cancel(info.id)

    rec.hooks.append(hook)
    info = q.submit_export(assets, [Path(a.path) for a in assets], out, "original")
    name, final = rec.wait(info.id)

    assert cancelled.is_set()
    assert name == "job.done" and final.status == "cancelled"
    assert final.done == 1 and final.fraction < 2 / 3
    first, second, third = final.results
    assert first.path is not None and Path(first.path).is_file() and first.error is None
    assert second.path is None and second.error is None
    assert third.path is None and third.error is None
    assert outputs(out) == [Path(first.path).name]  # ni la 2.ª ni su temporal
    assert [sha256_file(f) for f in files] == before


def test_cancel_queued_job_never_runs(tmp_path, q, rec):
    files = [photo(tmp_path / "in" / f"f{i}.jpg", seed=i) for i in range(2)]
    project, assets = setup(tmp_path, files)
    released = gate(rec)
    a = q.submit_export(assets[:1], [Path(x.path) for x in assets], tmp_path / "a", "original")
    b = q.submit_export(assets[1:], [Path(x.path) for x in assets], tmp_path / "b", "original")
    assert q.cancel(b.id).status == "cancelled"
    released.set()
    assert rec.wait(a.id)[1].status == "done"
    name, final = rec.wait(b.id)
    assert name == "job.done" and final.status == "cancelled"
    assert [n for n, _ in rec.of(b.id)] == ["job.done"]  # nunca pasó por running
    assert not (tmp_path / "b").exists()
    assert q.cancel(b.id).status == "cancelled"  # terminado: sin cambios
    assert q.cancel(a.id).status == "done"
    with pytest.raises(KeyError):
        q.cancel("nope")


def test_missing_photo_is_item_error(tmp_path, q, rec):
    files = [photo(tmp_path / "in" / f"f{i}.jpg", seed=i) for i in range(3)]
    project, assets = setup(tmp_path, files)
    files[1].unlink()
    kept = [files[0], files[2]]
    before = [sha256_file(f) for f in kept]
    info = q.submit_export(assets, [Path(a.path) for a in assets], tmp_path / "out", "web")
    name, final = rec.wait(info.id)
    assert [sha256_file(f) for f in kept] == before
    assert name == "job.done" and final.status == "done" and final.done == 3
    ok1, missing, ok2 = final.results
    assert missing.path is None and "falta" in missing.error
    assert Path(ok1.path).is_file() and Path(ok2.path).is_file()


def test_impossible_out_dir_fails(tmp_path, q, rec):
    project, assets = setup(tmp_path, [photo(tmp_path / "in" / "f.jpg")])
    blocker = tmp_path / "blocker"
    blocker.write_text("no soy una carpeta")
    info = q.submit_export(assets, [Path(assets[0].path)], blocker / "sub", "original")
    name, final = rec.wait(info.id)
    assert name == "job.failed" and final.status == "failed" and final.error


def test_job_uses_stack_snapshot(tmp_path, q, rec):
    files = [photo(tmp_path / "in" / f"f{i}.jpg", seed=i) for i in range(2)]
    before = [sha256_file(f) for f in files]
    project, assets = setup(tmp_path, files)
    protected = [Path(a.path) for a in assets]
    released = gate(rec)
    first = q.submit_export(assets[:1], protected, tmp_path / "a", "original")
    job = q.submit_export(assets[1:], protected, tmp_path / "out", "original")
    # El usuario edita la foto mientras el job espera en la cola.
    push(assets[1], EditPlan.model_validate({"operations": [{"op": "exposure", "ev": 2}]}), "x")
    released.set()
    rec.wait(first.id)
    _, final = rec.wait(job.id)
    assert [sha256_file(f) for f in files] == before
    exported = Path(final.results[0].path)
    assert abs(np.mean(pixels(exported)) - np.mean(pixels(files[1]))) < 3


def test_close_cancels_running_job(tmp_path, rec, big, monkeypatch):
    monkeypatch.setattr(jobs, "PROGRESS_INTERVAL", 0.0)
    before = sha256_file(big)
    q = JobQueue(rec)
    project, assets = setup(tmp_path, [big])
    out = tmp_path / "out"
    started = threading.Event()

    def hook(name, info):
        # A mitad de la foto: el worker espera acá hasta que close() empezó a cancelar, así
        # la foto no puede terminar antes (close marca la cola cerrada y cancela de una vez).
        if info.current == big.name and info.fraction > 0.1 and not started.is_set():
            started.set()
            deadline = time.monotonic() + TIMEOUT
            while not q._closed and time.monotonic() < deadline:
                time.sleep(0.001)

    rec.hooks.append(hook)
    info = q.submit_export(assets, [big], out, "original")
    assert started.wait(TIMEOUT)
    q.close()
    assert not any(t.name == "jobs" for t in threading.enumerate())
    name, final = rec.wait(info.id)
    assert name == "job.done" and final.status == "cancelled"
    assert outputs(out) == []
    assert sha256_file(big) == before
    with pytest.raises(RuntimeError):
        q.submit_export(assets, [big], out, "original")
