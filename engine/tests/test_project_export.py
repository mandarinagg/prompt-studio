from pathlib import Path

import numpy as np
from imaging import pixels, synthetic_rgb, to_vips

from pstudio.project.export import export_assets
from pstudio.project.history import push
from pstudio.project.store import add_assets, create, open_project
from pstudio.render import sha256_file
from pstudio.schema import EditPlan


def photo(path: Path, seed: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    to_vips(synthetic_rgb(96, 64, seed=seed)).write_to_file(str(path))
    return path


def setup(tmp_path: Path, n: int = 1):
    project = open_project(create(tmp_path, "P"))
    files = [photo(tmp_path / "in" / f"f{i}.jpg", seed=i) for i in range(n)]
    ids = add_assets(project, files).added
    return project, files, ids


def test_export_applies_stack(tmp_path):
    project, files, ids = setup(tmp_path)
    push(
        project.asset(ids[0]),
        EditPlan.model_validate({"operations": [{"op": "exposure", "ev": 1}]}),
        "x",
    )
    [result] = export_assets(project, ids, tmp_path / "out")
    assert result.error is None and result.dest == tmp_path / "out" / "f0_original.jpg"
    assert np.mean(pixels(result.dest)) > np.mean(pixels(files[0])) + 10


def test_export_never_overwrites_and_keeps_originals(tmp_path):
    project, files, ids = setup(tmp_path, 2)
    before = [sha256_file(f) for f in files]
    out = tmp_path / "out"
    first = export_assets(project, ids, out)
    second = export_assets(project, ids, out)
    assert [r.dest.name for r in first] == ["f0_original.jpg", "f1_original.jpg"]
    assert [r.dest.name for r in second] == ["f0_original_2.jpg", "f1_original_2.jpg"]
    # Exportar junto a los originales: no pisa nada.
    beside = export_assets(project, ids, files[0].parent, preset="web")
    assert all(r.error is None and r.dest.parent == files[0].parent for r in beside)
    assert [sha256_file(f) for f in files] == before


def test_export_missing_asset_reports_error_and_continues(tmp_path):
    project, files, ids = setup(tmp_path, 2)
    files[0].unlink()
    results = export_assets(project, ids, tmp_path / "out")
    assert results[0].dest is None and "falta" in results[0].error
    assert results[1].error is None and results[1].dest.is_file()
