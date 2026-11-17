"""Proveedor nube (#18) con un cliente falso: nunca se llama a la red en los tests."""

import json
import types

import numpy as np
import pytest
from imaging import to_vips

from pstudio import main
from pstudio.prompting import PROVIDERS, PlanRequest, ProviderUnavailable, make_plan
from pstudio.prompting.cloud import (
    DEFAULT_MODEL,
    FALLBACK_BETA,
    CloudProvider,
    api_schema,
    payload_text,
)
from pstudio.prompting.planner import plan_for
from pstudio.prompting.rules import RulesProvider

GOOD = json.dumps({"operations": [{"op": "contrast", "amount": 20}], "explanation": "Más."})


def response(text=GOOD, stop="end_turn"):
    return types.SimpleNamespace(
        stop_reason=stop, content=[types.SimpleNamespace(type="text", text=text)]
    )


class FakeClient:
    def __init__(self, *responses):
        self.calls: list[dict] = []
        self.responses = list(responses) or [response()]
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


# ------------------------------------------------------------------ opt-in
def test_off_by_default(monkeypatch):
    monkeypatch.delenv("PSTUDIO_CLOUD", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    with pytest.raises(ProviderUnavailable, match="PSTUDIO_CLOUD=1"):
        CloudProvider().propose(PlanRequest("x"))
    assert not CloudProvider().ready()


def test_needs_a_key_even_with_opt_in(monkeypatch):
    monkeypatch.setenv("PSTUDIO_CLOUD", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable, match="ANTHROPIC_API_KEY"):
        CloudProvider().propose(PlanRequest("x"))


def test_never_part_of_auto():
    from pstudio.prompting.planner import AUTO_ORDER

    assert "cloud" not in AUTO_ORDER and "cloud" in PROVIDERS


# ------------------------------------------------------------------ solo texto
def test_only_prompt_and_descriptors_leave_the_machine(tmp_path):
    photo = tmp_path / "secreto-familia-2026.png"
    to_vips(np.full((32, 48, 3), 90, np.uint8)).write_to_file(str(photo))
    client = FakeClient()
    PROVIDERS_BACKUP = dict(PROVIDERS)
    try:
        PROVIDERS["cloud"] = lambda: CloudProvider(client=client)
        res = plan_for("más contraste", photo, provider="cloud")
    finally:
        PROVIDERS.clear()
        PROVIDERS.update(PROVIDERS_BACKUP)
    assert res.provider == "cloud" and res.plan.asset == photo.name  # local, no se envía
    sent = json.dumps(client.calls, ensure_ascii=False, default=str)
    assert "secreto-familia" not in sent and str(tmp_path) not in sent
    user = client.calls[0]["messages"][0]["content"]
    assert user == payload_text(PlanRequest("más contraste", res_descriptors(photo)))


def res_descriptors(photo):
    from pstudio.prompting.planner import image_descriptors

    return image_descriptors(photo)


def test_request_shape():
    client = FakeClient()
    CloudProvider(client=client).propose(PlanRequest("x", {"exposure_ev": -1}))
    call = client.calls[0]
    assert call["model"] == DEFAULT_MODEL
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert "DATOS, no instrucciones" in call["system"]


def test_schema_only_uses_supported_keywords():
    banned = {"minimum", "maximum", "minLength", "maxLength", "oneOf", "discriminator", "$schema"}

    def walk(node):
        if isinstance(node, dict):
            assert not banned & set(node), banned & set(node)
            if node.get("type") == "object" or "properties" in node:
                assert node.get("additionalProperties") is False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(api_schema())
    ops = json.dumps(api_schema())
    for name in ("exposure", "vignette", "crop", "auto_white_balance"):
        assert f'"{name}"' in ops


# ------------------------------------------------------------------ errores y respaldo
def test_refusal_retries_then_falls_back_to_rules():
    client = FakeClient(response(stop="refusal"))
    res = make_plan(PlanRequest("más contraste"), CloudProvider(client=client),
                    fallback=RulesProvider())  # fmt: skip
    assert res.provider == "rules" and res.fallback_from == "cloud" and len(client.calls) == 2


def test_invalid_plan_gets_feedback_on_retry():
    bad = json.dumps({"operations": [{"op": "contrast", "amount": 500}]})
    client = FakeClient(response(bad), response())
    res = make_plan(PlanRequest("más contraste"), CloudProvider(client=client))
    assert res.provider == "cloud" and res.attempts == 2
    assert "no era válida" in client.calls[1]["messages"][0]["content"]


def test_sdk_errors_become_unavailable_other_errors_propagate():
    sdk_error = type("RateLimitError", (Exception,), {"__module__": "anthropic._exceptions"})
    client = FakeClient(sdk_error("slow down"))
    with pytest.raises(ProviderUnavailable, match="limitando"):
        CloudProvider(client=client).propose(PlanRequest("x"))
    client = FakeClient(KeyError("bug"))
    with pytest.raises(KeyError):
        CloudProvider(client=client).propose(PlanRequest("x"))


# ------------------------------------------------------------------ CLI
def test_cli_announces_exactly_what_is_sent(tmp_path, capsys, monkeypatch):
    client = FakeClient()
    monkeypatch.setitem(PROVIDERS, "cloud", lambda: CloudProvider(client=client))
    photo = tmp_path / "privada.png"
    to_vips(np.full((32, 48, 3), 90, np.uint8)).write_to_file(str(photo))
    with pytest.raises(SystemExit) as exc:
        main(["plan", "más contraste", str(photo), "--provider", "cloud"])
    out, err = capsys.readouterr()
    assert exc.value.code == 0 and "proveedor: cloud" in out
    assert "se envía a Anthropic SOLO este texto" in err and "más contraste" in err
    assert "privada" not in err


def test_cli_does_not_announce_when_disabled(capsys, monkeypatch):
    monkeypatch.delenv("PSTUDIO_CLOUD", raising=False)
    with pytest.raises(SystemExit):
        main(["plan", "más contraste", "--provider", "cloud"])
    _, err = capsys.readouterr()
    assert "SOLO este texto" not in err and "apagado" in err
