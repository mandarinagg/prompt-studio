import json
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
