import json

import numpy as np
import pytest
import pyvips

from pstudio import main
from pstudio.analysis import analyze
from pstudio.prompting import PROVIDERS, PlanRequest, ProviderUnavailable, make_plan
from pstudio.prompting.descriptors import describe, white_balance_label
from pstudio.prompting.evals import REPO_EVALS, CaseError, grade, load_cases, run_eval
from pstudio.schema import EditPlan


class Scripted:
    """Proveedor de prueba: devuelve las respuestas en orden y guarda el feedback recibido."""

    def __init__(self, *answers, name="scripted"):
        self.name = name
        self.answers = list(answers)
        self.feedback: list[str | None] = []

    def propose(self, request, feedback=None):
        self.feedback.append(feedback)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


GOOD = {"operations": [{"op": "exposure", "ev": 0.5}]}
REQ = PlanRequest("aclarala", {"mean_luminance": 0.2})


# ------------------------------------------------------------------ pipeline
def test_valid_first_try():
    res = make_plan(REQ, Scripted(json.dumps(GOOD)))
    assert res.plan is not None and res.valid_first_try and res.attempts == 1
    assert res.plan.source_prompt == "aclarala"


def test_retry_gets_the_error_as_feedback():
    p = Scripted('{"operations": [{"op": "exposure", "ev": 9}]}', GOOD)
    res = make_plan(REQ, p)
    assert res.plan is not None and res.attempts == 2 and not res.valid_first_try
    assert p.feedback[0] is None and "ev" in p.feedback[1]


@pytest.mark.parametrize(
    "bad",
    [
        "no es json",
        "[1, 2]",
        '{"operations": [{"op": "eval", "code": "import os"}]}',  # nada fuera del catálogo
        '{"operations": [{"op": "exposure", "ev": 0.5, "shell": "rm -rf /"}]}',
        '{"operations": [], "python": "print(1)"}',
    ],
)
def test_anything_outside_the_schema_is_rejected(bad):
    res = make_plan(REQ, Scripted(bad))
    assert res.plan is None and res.attempts == 2 and len(res.errors) == 2


def test_falls_back_to_rules_and_warns():
    res = make_plan(REQ, Scripted("roto", name="llm"), fallback=Scripted(GOOD, name="rules"))
    assert res.plan is not None and res.provider == "rules" and res.fallback_from == "llm"
    assert res.warnings and "llm" in res.warnings[0]


def test_unavailable_provider_does_not_retry():
    p = Scripted(ProviderUnavailable("sin modelo"))
    res = make_plan(REQ, p, fallback=Scripted(GOOD, name="rules"))
    assert res.attempts == 1 and res.provider == "rules" and res.errors == ["sin modelo"]


# ------------------------------------------------------------------ casos
def test_repo_cases_load():
    cases = load_cases([REPO_EVALS])
    assert len(cases) >= 20
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:  # los planes de ejemplo del criterio usan ops y campos que existen
        for path in [*c.get("sign", {}), *c.get("values", {}), *c.get("abs", {})]:
            assert "." in path


@pytest.mark.parametrize(
    ("toml", "msg"),
    [
        ('[[cases]]\nid = "a"\nprompt = "x"\n', "expect"),
        ('[[cases]]\nid = "a"\nprompt = "x"\nexpect = "opps"\n', "no existe"),
        (
            '[[cases]]\nid = "a"\nprompt = "x"\nexpect = "ops"\nrequiere = ["crop"]\n',
            "desconocidas",
        ),
        ('[[cases]]\nid = "a"\nprompt = "x"\nexpect = "any"\n' * 2, "repetido"),
    ],
)
def test_bad_cases_are_reported(tmp_path, toml, msg):
    f = tmp_path / "c.toml"
    f.write_text(toml, "utf-8")
    with pytest.raises(CaseError, match=msg):
        load_cases([f])


# ------------------------------------------------------------------ puntaje
def plan(**data) -> EditPlan:
    return EditPlan.model_validate(data)


@pytest.mark.parametrize(
    ("case", "p", "ok"),
    [
        ({"expect": "ops", "require": [["exposure", "auto_exposure"]]}, plan(**GOOD), True),
        ({"expect": "ops", "require": ["crop"]}, plan(**GOOD), False),
        ({"expect": "ops", "forbid": ["exposure"]}, plan(**GOOD), False),
        ({"expect": "ops", "sign": {"exposure.ev": "-"}}, plan(**GOOD), False),
        ({"expect": "ops", "sign": {"exposure.ev": "+"}}, plan(**GOOD), True),
        (
            {"expect": "any", "values": {"export.format": "webp"}},
            plan(export={"format": "webp"}),
            True,
        ),  # fmt: skip
        (
            {"expect": "ops", "abs": {"rotate.degrees": 90}},
            plan(operations=[{"op": "rotate", "degrees": -90}]),
            True,
        ),  # fmt: skip
        (
            {"expect": "ops", "max": {"saturation.amount": -90}},
            plan(operations=[{"op": "saturation", "amount": -50}]),
            False,
        ),  # fmt: skip
        (
            {"expect": "ops", "min": {"sharpen.amount": 20}},
            plan(operations=[{"op": "sharpen", "amount": 30}]),
            True,
        ),  # fmt: skip
        ({"expect": "unsupported"}, plan(**GOOD), False),
        (
            {"expect": "unsupported"},
            plan(unsupported=[{"request": "quitar fondo", "reason": "no hay IA"}]),
            True,
        ),  # fmt: skip
        ({"expect": "clarification"}, plan(clarification="¿qué formato?"), True),
        ({"expect": "clarification_or_ops", "require_if_ops": ["crop"]}, plan(**GOOD), False),
        (
            {"expect": "clarification_or_ops", "require_if_ops": ["crop"]},
            plan(operations=[{"op": "crop", "aspect_ratio": "1:1"}]),
            True,
        ),  # fmt: skip
        ({"expect": "unsupported_or_ops"}, plan(), False),
        (
            {"expect": "ops", "max_ops": 1},
            plan(operations=[GOOD["operations"][0], {"op": "contrast", "amount": 5}]),
            False,
        ),  # fmt: skip
    ],
)
def test_grade(case, p, ok):
    assert (grade(p, case) == []) is ok


def test_run_eval_scores_and_never_falls_back(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text(
        '[[cases]]\nid = "a"\nprompt = "aclarala"\nexpect = "ops"\nrequire = ["exposure"]\n'
        '[[cases]]\nid = "b"\nprompt = "recortá"\nexpect = "ops"\nrequire = ["crop"]\n'
        '[[cases]]\nid = "c"\nprompt = "x"\nexpect = "any"\n',
        "utf-8",
    )

    class ByPrompt:
        name = "by-prompt"

        def propose(self, request, feedback=None):
            return {"aclarala": GOOD, "recortá": GOOD}.get(request.prompt, "roto")

    report = run_eval(ByPrompt(), load_cases([f]))
    s = report.summary
    assert s["cases"] == 3 and s["valid_pct"] == 66.7 and s["correct_pct"] == 33.3
    assert [r.correct for r in report.results] == [True, False, False]
    assert report.results[2].fails[0].startswith("inválido")


def test_cli_eval(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(PROVIDERS, "fake", lambda: Scripted(GOOD, name="fake"))
    out_json = tmp_path / "r.json"
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--provider", "fake", "--json", str(out_json)])
    out = capsys.readouterr().out
    assert exc.value.code == 0 and "fake:" in out and "correcto" in out
    data = json.loads(out_json.read_text("utf-8"))
    assert data["summary"]["cases"] >= 20
    with pytest.raises(SystemExit) as exc:
        main(["eval", "--provider", "no-existe"])
    assert exc.value.code == 2


# ------------------------------------------------------------------ descriptores
def test_white_balance_label():
    assert white_balance_label((0.2, 0.2, 0.2)) == "neutro"
    assert white_balance_label((0.3, 0.2, 0.12)).startswith("muy cálido")
    assert white_balance_label((0.17, 0.2, 0.24)) == "frío"
    assert white_balance_label((0.2, 0.3, 0.2)).endswith("verdoso")


def test_describe_dark_warm_image():
    arr = np.full((60, 90, 3), 0.02, np.float32) * np.array([1.6, 1.0, 0.5], np.float32)
    img = pyvips.Image.new_from_array(arr).copy(interpretation="scrgb")
    d = describe(analyze(img), 6000, 4000)
    assert d["orientation"] == "horizontal" and d["width"] == 6000
    assert d["exposure_ev"] < -2.5 and d["mean_luminance"] < 0.25
    assert d["white_balance_estimate"].startswith("muy cálido")
    json.dumps(d)  # serializable: es lo único que reciben los proveedores
