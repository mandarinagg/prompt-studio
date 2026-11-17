import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from pstudio import main
from pstudio.schema import OP_NAMES, EditPlan, json_schema
from pstudio.schema.plan import OP_TYPES

REPO = Path(__file__).resolve().parents[2]
SCHEMA_FILE = REPO / "engine" / "schema" / "edit-plan-1.0.schema.json"


FULL = {"x": 0, "y": 0, "width": 1, "height": 1}


def plan(*ops: dict, **extra) -> EditPlan:
    return EditPlan.model_validate({"operations": list(ops), **extra})


# ------------------------------------------------------------------- sincronía con la doc
def test_catalog_matches_edit_operations_doc():
    doc = (REPO / "docs" / "EDIT_OPERATIONS.md").read_text(encoding="utf-8")
    table = doc.split("## Export")[0]
    documented = set()
    for line in table.splitlines():
        if line.startswith("| `"):
            documented |= set(re.findall(r"`([a-z_]+)`", line.split("|")[1]))
    assert documented == set(OP_NAMES)


def test_prompt_engine_doc_example_is_valid():
    doc = (REPO / "docs" / "PROMPT_ENGINE.md").read_text(encoding="utf-8")
    example = re.search(r"```json\n(.*?)```", doc, re.S).group(1)
    p = EditPlan.model_validate_json(example)
    assert [o.op for o in p.operations] == [
        "auto_exposure",
        "auto_white_balance",
        "shadows",
        "crop",
    ]
    assert p.export.preset == "catalog_square"


def test_committed_json_schema_is_up_to_date():
    # El archivo versionado lo consumen la app (tipos TS) y los proveedores de plan.
    # Si falla: `uv run pstudio schema --out schema/edit-plan-1.0.schema.json`.
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == json_schema()


# --------------------------------------------------------------------------- planes válidos
def test_empty_plan_is_valid_and_defaults():
    p = EditPlan.model_validate({})
    assert p.schema_version == "1.0"
    assert p.operations == [] and p.unsupported == [] and p.clarification is None


def test_full_catalog_plan():
    p = plan(
        {"op": "exposure", "ev": 0.7},
        {"op": "auto_exposure", "strength": 0.5},
        {"op": "contrast", "amount": 20},
        {"op": "highlights", "amount": -40},
        {"op": "shadows", "amount": 30},
        {"op": "whites", "amount": 10},
        {"op": "blacks", "amount": -10},
        {"op": "white_balance", "temperature_shift": -15, "tint_shift": 5},
        {"op": "auto_white_balance", "method": "white_patch"},
        {"op": "saturation", "amount": -100},
        {"op": "vibrance", "amount": 25},
        {"op": "crop", "rect": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8}},
        {"op": "rotate", "degrees": 90},
        {"op": "straighten", "degrees": -2.5},
        {"op": "resize", "width": 1080, "height": 1080, "fit": "cover"},
        {"op": "sharpen", "amount": 40, "radius": 1.2},
        {"op": "denoise", "strength": 0.4},
        {"op": "vignette", "amount": -30, "midpoint": 40},
        export={"preset": "web", "quality": 80, "metadata": "strip"},
    )
    assert len(p.operations) == len(OP_NAMES) == 18


def test_order_is_preserved():
    p = plan({"op": "crop", "aspect_ratio": "4:5"}, {"op": "exposure", "ev": 1})
    assert [o.op for o in p.operations] == ["crop", "exposure"]


def test_empty_clarification_is_normalized_to_null():
    assert plan(clarification="").clarification is None


def test_plan_round_trips_through_json():
    p = plan({"op": "resize", "width": 2048}, {"op": "vignette", "amount": -20})
    assert EditPlan.model_validate_json(p.model_dump_json()) == p


# --------------------------------------------------------------------------- neutros
@pytest.mark.parametrize("op_type", OP_TYPES, ids=OP_NAMES)
def test_defaults_are_neutral(op_type):
    name = op_type.model_fields["op"].annotation.__args__[0]
    required = {
        "crop": {"aspect_ratio": "1:1"},
        "resize": {"width": 100},
    }
    op = op_type.model_validate({"op": name, **required.get(name, {})})
    automatic_or_geometric = {"auto_exposure", "auto_white_balance", "crop", "resize"}
    assert op.is_noop() is (name not in automatic_or_geometric)


def test_non_neutral_values_are_not_noop():
    p = plan({"op": "exposure", "ev": 0.1}, {"op": "white_balance", "tint_shift": 1})
    assert not any(o.is_noop() for o in p.operations)


# --------------------------------------------------------------------------- planes inválidos
@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ({"operations": [{"op": "shell", "cmd": "del C:\\*"}]}, "does not match"),
        ({"operations": [{"op": "exposure", "ev": 6}]}, "less than or equal to 5"),
        ({"operations": [{"op": "contrast", "amount": -101}]}, "greater than or equal to -100"),
        ({"operations": [{"op": "contrast", "amount": 10, "code": "x"}]}, "Extra inputs"),
        ({"operations": [{"op": "contrast"}, {"op": "contrast"}]}, "una sola vez"),
        ({"operations": [{"op": "crop"}]}, "exactamente uno"),
        (
            {"operations": [{"op": "crop", "aspect_ratio": "1:1", "rect": FULL}]},
            "exactamente uno",
        ),
        (
            {"operations": [{"op": "crop", "rect": {"x": 0.5, "y": 0, "width": 0.6, "height": 1}}]},
            "se sale",
        ),
        ({"operations": [{"op": "crop", "aspect_ratio": "7:3"}]}, "Input should be"),
        ({"operations": [{"op": "resize"}]}, "width, height o ambos"),
        ({"operations": [{"op": "resize", "width": 100, "fit": "cover"}]}, "width y height"),
        ({"operations": [{"op": "sharpen", "amount": 10, "radius": 9}]}, "less than or equal to 5"),
        ({"schema_version": "2.0"}, "Input should be '1.0'"),
        ({"export": {"format": "bmp"}}, "Input should be"),
        ({"export": {"preset": "inventado"}}, "Input should be"),
        ({"script": "import os"}, "Extra inputs"),
        ({"operations": [{"ev": 1}]}, "Unable to extract tag"),
    ],
)  # fmt: skip
def test_invalid_plans(data, fragment):
    with pytest.raises(ValidationError) as exc:
        EditPlan.model_validate(data)
    assert fragment in str(exc.value)


def test_models_are_immutable():
    p = plan({"op": "exposure", "ev": 1})
    with pytest.raises(ValidationError):
        p.operations[0].ev = 2


# --------------------------------------------------------------------------- JSON Schema
def test_json_schema_shape():
    s = json_schema()
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert s["additionalProperties"] is False
    op_defs = [d for d in s["$defs"].values() if "op" in d.get("properties", {})]
    assert sorted(d["properties"]["op"]["const"] for d in op_defs) == sorted(OP_NAMES)
    assert all(d["additionalProperties"] is False for d in op_defs)


# --------------------------------------------------------------------------- CLI
def run_cli(argv, capsys) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    out, err = capsys.readouterr()
    return exc.value.code, out, err


def test_cli_schema_stdout(capsys):
    code, out, _ = run_cli(["schema"], capsys)
    assert code == 0 and json.loads(out) == json_schema()


def test_cli_validate_ok_and_error(tmp_path, capsys):
    good = tmp_path / "bien.json"
    good.write_text(json.dumps({"operations": [{"op": "exposure", "ev": 0.5}]}), "utf-8")
    code, out, _ = run_cli(["validate", str(good)], capsys)
    assert code == 0 and "plan válido (exposure)" in out

    bad = tmp_path / "mal.json"
    bad.write_text(json.dumps({"operations": [{"op": "eval", "code": "1"}]}), "utf-8")
    code, _, err = run_cli(["validate", str(bad)], capsys)
    assert code == 1 and "plan inválido" in err

    code, _, err = run_cli(["validate", str(tmp_path / "no.json")], capsys)
    assert code == 2
