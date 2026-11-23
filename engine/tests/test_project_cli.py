import json
import sys
from pathlib import Path

import pytest
from imaging import synthetic_rgb, to_vips

from pstudio import main
from pstudio.render import sha256_file


def run(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["project", *argv])
    out, err = capsys.readouterr()
    return exc.value.code, out, err


def photo(path: Path, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_vips(synthetic_rgb(96, 64, seed=seed)).write_to_file(str(path))
    return path


def test_project_cli_end_to_end(tmp_path, capsys):
    files = [photo(tmp_path / "in" / f"f{i}.jpg", i) for i in range(2)]
    before = [sha256_file(f) for f in files]

    code, out, _ = run(["new", str(tmp_path), "Verano"], capsys)
    assert code == 0
    proj = str(tmp_path / "Verano.pstudio")
    assert out.strip() == proj

    code, out, _ = run(["add", proj, *map(str, files), str(files[0])], capsys)
    assert code == 0 and "2 agregadas" in out and "1 duplicada" in out

    code, out, _ = run(["list", proj, "--json"], capsys)
    assets = json.loads(out)
    assert [a["file"] for a in assets] == ["f0.jpg", "f1.jpg"]
    assert not any(a["edited"] or a["missing"] for a in assets)
    first = assets[0]["id"]

    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "source_prompt": "más luz",
                "operations": [{"op": "exposure", "ev": 0.5}, {"op": "resize", "width": 800}],
            }
        ),
        encoding="utf-8",
    )
    code, out, _ = run(["edit", proj, first, "--plan", str(plan)], capsys)
    assert code == 0 and "resize" in out  # avisa la sugerencia de export

    code, out, _ = run(["show", proj, first, "--json"], capsys)
    shown = json.loads(out)
    assert shown["stack"]["operations"] == [{"op": "exposure", "ev": 0.5}]
    assert [h["label"] for h in shown["history"]] == ["Original", "Pedido: más luz"]
    assert shown["cursor"] == 1

    code, out, _ = run(["show", proj, first], capsys)
    assert "▶" in out and "Pedido: más luz" in out

    assert run(["undo", proj, first], capsys)[0] == 0
    code, out, _ = run(["show", proj, first, "--json"], capsys)
    assert json.loads(out)["stack"]["operations"] == []
    assert run(["undo", proj, first], capsys)[0] == 1  # nada que deshacer
    assert run(["redo", proj, first], capsys)[0] == 0

    code, out, _ = run(["list", proj, "--json"], capsys)
    assert json.loads(out)[0]["edited"] is True

    code, out, _ = run(["export", proj, "-o", str(tmp_path / "out"), "--preset", "web"], capsys)
    assert code == 0
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["f0_web.webp", "f1_web.webp"]
    assert [sha256_file(f) for f in files] == before


def test_project_cli_replace_and_relink(tmp_path, capsys):
    f = photo(tmp_path / "in" / "a.jpg")
    run(["new", str(tmp_path), "P"], capsys)
    proj = str(tmp_path / "P.pstudio")
    run(["add", proj, str(f)], capsys)
    asset = json.loads(run(["list", proj, "--json"], capsys)[1])[0]["id"]
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps({"operations": [{"op": "exposure", "ev": 0.5}]}), encoding="utf-8")
    run(["edit", proj, asset, "--plan", str(plan)], capsys)
    run(["edit", proj, asset, "--plan", str(plan), "--replace", "--label", "Slider"], capsys)
    shown = json.loads(run(["show", proj, asset, "--json"], capsys)[1])
    assert shown["stack"]["operations"] == [{"op": "exposure", "ev": 0.5}]  # reemplazo: no suma

    moved = tmp_path / "movida" / "a.jpg"
    moved.parent.mkdir()
    f.rename(moved)
    assert json.loads(run(["list", proj, "--json"], capsys)[1])[0]["missing"] is True
    assert run(["relink", proj, asset, str(moved)], capsys)[0] == 0
    assert json.loads(run(["list", proj, "--json"], capsys)[1])[0]["missing"] is False


def test_project_cli_errors(tmp_path, capsys):
    code, _, err = run(["list", str(tmp_path / "nada.pstudio")], capsys)
    assert code == 2 and "no existe el proyecto" in err
    run(["new", str(tmp_path), "P"], capsys)
    proj = str(tmp_path / "P.pstudio")
    code, _, err = run(["undo", proj, "zz"], capsys)
    assert code == 2 and "no existe la foto zz" in err
    bad = tmp_path / "bad.json"
    bad.write_text('{"operations": [{"op": "exec"}]}', encoding="utf-8")
    f = photo(tmp_path / "a.jpg")
    run(["add", proj, str(f)], capsys)
    asset = json.loads(run(["list", proj, "--json"], capsys)[1])[0]["id"]
    assert run(["edit", proj, asset, "--plan", str(bad)], capsys)[0] == 1


def test_project_cli_os_errors_have_no_traceback(tmp_path, capsys):
    blocker = tmp_path / "soy_un_archivo"
    blocker.write_text("x")
    code, _, err = run(["new", str(blocker), "X"], capsys)
    assert code == 2 and "Traceback" not in err and "no se pudo" in err
    run(["new", str(tmp_path), "P"], capsys)
    proj = str(tmp_path / "P.pstudio")
    run(["add", proj, str(photo(tmp_path / "a.jpg"))], capsys)
    code, _, err = run(["export", proj, "-o", str(blocker)], capsys)
    assert code == 2 and "Traceback" not in err and "no se pudo" in err


def test_project_recent(tmp_path, capsys):
    from pstudio import recent

    code, out, _ = run(["recent"], capsys)
    assert code == 0 and "no hay proyectos recientes" in out
    a = tmp_path / "A.pstudio"
    a.mkdir()
    (a / "project.json").write_text("{}")
    recent.touch(a, "A")
    recent.touch(tmp_path / "B.pstudio", "B")  # ya no existe
    code, out, _ = run(["recent"], capsys)
    lines = out.strip().splitlines()
    assert lines[0].startswith("B  ") and lines[0].endswith("(no encontrado)")
    assert lines[1] == f"A  {a.resolve()}"
    code, out, _ = run(["recent", "--json"], capsys)
    assert [i["name"] for i in json.loads(out)] == ["B", "A"]


def _project_with(tmp_path, capsys, n):
    files = [photo(tmp_path / "in" / f"f{i}.jpg", i) for i in range(n)]
    run(["new", str(tmp_path), "P"], capsys)
    proj = str(tmp_path / "P.pstudio")
    run(["add", proj, *map(str, files)], capsys)
    return proj, files


def test_export_progress_per_photo_without_tty(tmp_path, capsys):
    proj, _ = _project_with(tmp_path, capsys, 2)
    code, out, err = run(["export", proj, "-o", str(tmp_path / "out")], capsys)
    assert code == 0
    assert "\r" not in err
    lines = [ln for ln in err.splitlines() if ln.startswith("[")]
    assert lines == ["[1/2] f0.jpg 100%", "[2/2] f1.jpg 100%"]
    assert out.count("(") == 2  # stdout: una línea por foto terminada, como antes


def test_export_ctrl_c_cancels_and_leaves_no_temporaries(tmp_path, capsys, monkeypatch):
    _ctrl_c_export(tmp_path, capsys, monkeypatch, tty=False)


def test_export_ctrl_c_on_tty_ends_progress_line(tmp_path, capsys, monkeypatch):
    err = _ctrl_c_export(tmp_path, capsys, monkeypatch, tty=True)
    assert "\r[2/3] f1.jpg 0%" in err
    # el mensaje de cancelación va en su propia línea, no pegado al progreso
    assert "\ncancelado: " in err
    assert "%cancelado" not in err


def _ctrl_c_export(tmp_path, capsys, monkeypatch, *, tty):
    import io
    import threading

    from pstudio.project import cli, export

    proj, files = _project_with(tmp_path, capsys, 3)
    before = [sha256_file(f) for f in files]
    real = export.export_assets
    reached = threading.Event()

    def fake(project, ids, out, preset, *, on_progress, cancel):
        def gated(i, total, asset_id, fraction):
            if tty and i == 1 and fraction > 0:  # cancelada a mitad de foto: no llega al 100 %
                return
            on_progress(i, total, asset_id, fraction)
            if i == 1 and fraction == 0.0:  # la segunda foto empieza: acá llega Ctrl+C
                reached.set()
                assert cancel.wait(10)

        return real(project, ids, out, preset, on_progress=gated, cancel=cancel)

    def interrupted(worker):
        assert reached.wait(10)
        raise KeyboardInterrupt

    monkeypatch.setattr(export, "export_assets", fake)
    monkeypatch.setattr(cli, "_wait", interrupted)
    out_dir = tmp_path / "out"
    if tty:

        class TtyErr(io.StringIO):
            def isatty(self):
                return True

        fake_err = TtyErr()
        monkeypatch.setattr(sys, "stderr", fake_err)
    code, out, err = run(["export", proj, "-o", str(out_dir)], capsys)
    if tty:
        err = fake_err.getvalue()
    assert code == 130
    # una foto tan chica puede terminar antes de ver la señal: lo firme es que no queden
    # temporales, que lo terminado se conserve y que el resto no se exporte
    kept = sorted(p.name for p in out_dir.iterdir())
    assert 1 <= len(kept) < 3 and all(".tmp" not in n for n in kept)
    assert f"cancelado: {len(kept)} exportadas, el resto no" in err
    assert all(n in out for n in kept)
    assert [sha256_file(f) for f in files] == before
    return err
