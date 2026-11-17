import json

import numpy as np
import pytest
from imaging import to_vips

from pstudio import main
from pstudio.prompting import PROVIDERS
from pstudio.prompting.planner import image_descriptors, plan_for
from pstudio.render import sha256_file
from pstudio.schema import EditPlan


def dark_warm_photo(path):
    arr = (np.full((48, 72, 3), 40, np.float32) * np.array([1.4, 1.0, 0.6])).astype(np.uint8)
    to_vips(arr).write_to_file(str(path))
    return path


def run_cli(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    out, err = capsys.readouterr()
    return exc.value.code, out, err


def test_descriptors_come_from_the_photo(tmp_path):
    d = image_descriptors(dark_warm_photo(tmp_path / "f.png"))
    assert d["width"] == 72 and d["exposure_ev"] < -1 and "cálido" in d["white_balance_estimate"]


def test_plan_for_without_llm_uses_rules(tmp_path):
    res = plan_for("aclarala", dark_warm_photo(tmp_path / "f.png"))
    assert res.provider == "rules" and res.plan.asset == "f.png"
    assert res.plan.operations[0].op == "exposure"


def test_plan_falls_back_with_a_warning(tmp_path, monkeypatch, capsys):
    class Broken:
        name = "broken"

        def propose(self, request, feedback=None):
            return '{"operations": [{"op": "eval"}]}'

    monkeypatch.setitem(PROVIDERS, "broken", Broken)
    code, out, err = run_cli(["plan", "más contraste", "--provider", "broken"], capsys)
    assert code == 0 and "proveedor: rules" in out and "aviso:" in err


def test_cli_plan_then_apply_end_to_end(tmp_path, capsys):
    photo = dark_warm_photo(tmp_path / "foto.png")
    before = sha256_file(photo)
    plan_file = tmp_path / "plan.json"
    code, out, _ = run_cli(
        ["plan", "aclarala, más cálida y cuadrada para la web sin GPS", str(photo),
         "-o", str(plan_file)],
        capsys,
    )  # fmt: skip
    assert code == 0 and "crop aspect_ratio=1:1" in out
    plan = EditPlan.model_validate_json(plan_file.read_text("utf-8"))
    assert plan.export.metadata == "strip_gps" and plan.source_prompt.startswith("aclarala")

    code, out, _ = run_cli(["apply", str(plan_file), str(photo), "-o", str(tmp_path / "o")], capsys)
    assert code == 0 and "1/1 exportadas" in out
    assert sha256_file(photo) == before


def test_cli_plan_json_and_errors(tmp_path, capsys):
    code, out, _ = run_cli(["plan", "pasala a blanco y negro", "--json"], capsys)
    assert code == 0 and json.loads(out)["operations"][0]["op"] == "contrast"
    assert run_cli(["plan", "x", str(tmp_path / "no.jpg")], capsys)[0] == 2
    (tmp_path / "rota.jpg").write_bytes(b"no")
    assert run_cli(["plan", "x", str(tmp_path / "rota.jpg")], capsys)[0] == 2
    assert run_cli(["plan", "x", "--provider", "nope"], capsys)[0] == 2
