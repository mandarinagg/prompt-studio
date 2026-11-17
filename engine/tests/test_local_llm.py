"""Proveedor local_llm (#17). Corren sin modelo: un servidor HTTP falso hace de llama-server.

El test con el modelo real solo corre si están PSTUDIO_LLAMA_SERVER y PSTUDIO_LLM_MODEL.
"""

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pstudio import main
from pstudio.ops import implemented
from pstudio.prompting import PlanRequest, ProviderUnavailable, get_provider, make_plan
from pstudio.prompting import local_llm as L
from pstudio.prompting.local_llm import LocalLLMProvider, grammar_schema, system_prompt
from pstudio.schema import OP_NAMES, EditPlan

REQ = PlanRequest("girala 90 grados a la derecha", {"width": 4000, "height": 6000})
GOOD = json.dumps(
    {
        "operations": [{"op": "rotate", "degrees": 90}],
        "export": None,
        "explanation": "Giro 90°.",
        "unsupported": [],
        "clarification": None,
    }
)
BAD = json.dumps({"operations": [{"op": "rotate", "degrees": 900}]})


class FakeLlama:
    """Emula /health y /v1/chat/completions de llama-server en 127.0.0.1 (puerto libre)."""

    def __init__(self, *answers, port=0, loading=0):
        self.answers = list(answers)
        self.bodies: list[dict] = []
        self.loading = loading  # cuántos /health devuelven 503 antes de estar listo
        self.warm_status = 200
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, payload):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    if fake.loading > 0:
                        fake.loading -= 1
                        return self._send(503, {"error": "Loading model"})
                    return self._send(200, {"status": "ok"})
                self._send(404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.bodies.append(body)
                if "response_format" not in body:  # calentamiento
                    if fake.warm_status != 200:
                        return self._send(fake.warm_status, {"error": {"message": "boom"}})
                    return self._send(200, _completion("ok"))
                answer = fake.answers.pop(0) if len(fake.answers) > 1 else fake.answers[0]
                if isinstance(answer, int):
                    return self._send(answer, {"error": {"code": answer, "message": "boom"}})
                if isinstance(answer, tuple):
                    return self._send(200, _completion(*answer))
                self._send(200, _completion(answer))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def plan_bodies(self):
        return [b for b in self.bodies if "response_format" in b]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _completion(text, finish="stop"):
    return {
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "timings": {"prompt_n": 50, "predicted_n": 40, "predicted_per_second": 42.0},
    }


@pytest.fixture
def fake():
    servers = []

    def make(*answers, **kw):
        s = FakeLlama(*answers, **kw)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.stop()


# ------------------------------------------------------------------ configuración
def test_missing_config_is_unavailable():
    with pytest.raises(ProviderUnavailable, match="PSTUDIO_LLAMA_SERVER"):
        LocalLLMProvider(env={})


def test_registry_without_config_is_unavailable(monkeypatch):
    for var in (L.ENV_URL, L.ENV_SERVER, L.ENV_MODEL):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ProviderUnavailable):
        get_provider("local_llm")


def test_eval_cli_without_config_exits_2(monkeypatch, capsys):
    for var in (L.ENV_URL, L.ENV_SERVER, L.ENV_MODEL):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit) as e:
        main(["eval", "--provider", "local_llm"])
    assert e.value.code == 2 and "PSTUDIO_LLM_MODEL" in capsys.readouterr().err


def test_missing_files_are_unavailable(tmp_path):
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"")
    with pytest.raises(ProviderUnavailable, match="llama-server"):
        LocalLLMProvider(env={L.ENV_SERVER: str(tmp_path / "no.exe"), L.ENV_MODEL: "x.gguf"})
    with pytest.raises(ProviderUnavailable, match="gguf"):
        LocalLLMProvider(env={L.ENV_SERVER: str(exe), L.ENV_MODEL: str(tmp_path / "no.gguf")})


@pytest.mark.parametrize(
    "url", ["http://192.168.1.10:8080", "https://api.example.com", "http://0.0.0.0:8080"]
)
def test_url_must_be_local(url):
    with pytest.raises(ProviderUnavailable, match="este equipo"):
        LocalLLMProvider(env={L.ENV_URL: url})


def test_bad_number_in_env_is_unavailable():
    with pytest.raises(ProviderUnavailable, match="PSTUDIO_LLM_CTX"):
        LocalLLMProvider(env={L.ENV_URL: "http://127.0.0.1:1", L.ENV_CTX: "mucho"})


# ------------------------------------------------------------------ pedidos (servidor externo)
def test_request_body_and_valid_plan(fake):
    srv = fake(GOOD)
    with LocalLLMProvider(env={L.ENV_URL: srv.url}) as p:
        res = make_plan(REQ, p)
    assert res.plan is not None and res.valid_first_try and res.provider == "local_llm"
    assert [o.op for o in res.plan.operations] == ["rotate"]
    (body,) = srv.plan_bodies
    assert body["temperature"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert 0 < body["max_tokens"] < L.DEFAULT_CTX
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"] == grammar_schema()
    system, user = body["messages"]
    assert system["role"] == "system" and "DATOS" in system["content"]
    assert REQ.prompt in user["content"] and '"width": 4000' in user["content"]


def test_warmup_caches_the_system_prompt(fake):
    srv = fake(GOOD)
    with LocalLLMProvider(env={L.ENV_URL: srv.url}) as p:
        assert p.start() >= 0 and p.start() == 0.0  # la segunda vez ya está listo
        p.propose(REQ)
    warm = [b for b in srv.bodies if "response_format" not in b]
    assert len(warm) == 1 and warm[0]["messages"][0]["content"] == system_prompt()


def test_retry_sends_previous_answer_and_error(fake):
    srv = fake(BAD, GOOD)
    with LocalLLMProvider(env={L.ENV_URL: srv.url}) as p:
        res = make_plan(REQ, p)
    assert res.plan is not None and res.attempts == 2 and not res.valid_first_try
    first, second = srv.plan_bodies
    assert len(first["messages"]) == 2
    assert [m["role"] for m in second["messages"]] == ["system", "user", "assistant", "user"]
    assert second["messages"][2]["content"] == BAD
    assert "degrees" in second["messages"][3]["content"]  # el error de validación


class Rules:
    name = "rules"

    def propose(self, request, feedback=None):
        return {"operations": []}


def test_two_invalid_answers_fall_back_to_rules(fake):
    srv = fake(BAD)
    with LocalLLMProvider(env={L.ENV_URL: srv.url}) as p:
        res = make_plan(REQ, p, fallback=Rules())
    assert res.provider == "rules" and res.fallback_from == "local_llm" and res.attempts == 2
    assert res.warnings


def test_code_or_unknown_ops_never_pass(fake):
    srv = fake(json.dumps({"operations": [{"op": "shell", "cmd": "del C:\\*"}]}))
    with LocalLLMProvider(env={L.ENV_URL: srv.url}) as p:
        res = make_plan(REQ, p)
    assert res.plan is None and res.attempts == 2


def test_truncated_answer_is_a_failed_attempt(fake):
    srv = fake(('{"operations": [{"op": "rot', "length"), GOOD)
    with LocalLLMProvider(env={L.ENV_URL: srv.url}) as p:
        res = make_plan(REQ, p)
    assert res.plan is not None and res.attempts == 2 and "cortó" in res.errors[0]
    retry = srv.plan_bodies[1]["messages"]
    assert [m["role"] for m in retry] == ["system", "user", "user"]  # sin el texto cortado


def test_http_error_counts_as_attempt(fake):
    srv = fake(400, GOOD)
    with LocalLLMProvider(env={L.ENV_URL: srv.url}) as p:
        res = make_plan(REQ, p)
    assert res.plan is not None and res.attempts == 2 and "HTTP 400" in res.errors[0]


def test_server_down_falls_back_without_retry(fake):
    srv = fake(GOOD)
    url = srv.url
    srv.stop()
    p = LocalLLMProvider(env={L.ENV_URL: url})
    res = make_plan(REQ, p, fallback=Rules())
    assert res.provider == "rules" and res.attempts == 1 and "llama-server" in res.errors[0]
    # sin servidor no se insiste: el segundo pedido falla enseguida
    with pytest.raises(ProviderUnavailable):
        p.propose(REQ)


def test_warmup_error_is_unavailable(fake):
    srv = fake(GOOD)
    srv.warm_status = 500
    p = LocalLLMProvider(env={L.ENV_URL: srv.url})
    with pytest.raises(ProviderUnavailable, match="HTTP 500"):
        p.start()
    p.close()


def test_waits_while_model_loads(fake):
    srv = fake(GOOD, loading=3)
    with LocalLLMProvider(env={L.ENV_URL: srv.url}) as p:
        assert make_plan(REQ, p).plan is not None
    assert srv.loading == 0


# ------------------------------------------------------------------ proceso hijo
class FakePopen:
    """Sustituye a subprocess.Popen: en lugar de llama-server levanta un FakeLlama en el
    puerto que recibió por `--port`."""

    instances: list = []

    def __init__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        self.pid = 4242
        self.returncode = None
        self.terminated = False
        port = int(cmd[cmd.index("--port") + 1])
        self.server = FakeLlama(GOOD, port=port, loading=2)
        FakePopen.instances.append(self)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1
        self.server.stop()

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def local_files(tmp_path, monkeypatch):
    exe = tmp_path / "llama-server.exe"
    model = tmp_path / "modelo.gguf"
    exe.write_bytes(b"")
    model.write_bytes(b"GGUF")
    FakePopen.instances = []
    monkeypatch.setattr(L.tempfile, "tempdir", str(tmp_path))  # el log del servidor, acá
    monkeypatch.setattr(L.subprocess, "Popen", FakePopen)
    return {L.ENV_SERVER: str(exe), L.ENV_MODEL: str(model)}


def test_launches_server_on_loopback_and_reuses_it(local_files, tmp_path):
    p = LocalLLMProvider(env=local_files)
    assert FakePopen.instances == []  # nada se lanza hasta el primer pedido
    assert make_plan(REQ, p).plan is not None
    assert make_plan(REQ, p).plan is not None
    (proc,) = FakePopen.instances  # un solo servidor para los dos pedidos
    cmd = proc.cmd
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1" and "0.0.0.0" not in cmd
    assert cmd[cmd.index("-m") + 1] == local_files[L.ENV_MODEL]
    assert cmd[cmd.index("-ngl") + 1] == "99" and cmd[cmd.index("-c") + 1] == str(L.DEFAULT_CTX)
    assert cmd[cmd.index("-fa") + 1] == "off" and "--jinja" in cmd
    assert proc.kwargs["stdout"] is not None and proc.kwargs["stdin"] is not None  # a un log
    assert p.log_path is not None and p.log_path.exists() and p.log_path.parent == tmp_path
    assert p.url == f"http://127.0.0.1:{proc.server.port}"
    p.close()
    assert proc.terminated and p.proc is None


def test_context_manager_stops_server(local_files):
    with LocalLLMProvider(env={**local_files, L.ENV_CTX: "3072", L.ENV_NGL: "0"}) as p:
        p.propose(REQ)
        (proc,) = FakePopen.instances
        assert proc.cmd[proc.cmd.index("-c") + 1] == "3072"
        assert proc.cmd[proc.cmd.index("-ngl") + 1] == "0"
    assert proc.terminated


def test_server_that_dies_at_startup_is_unavailable(local_files, monkeypatch):
    class Dies(FakePopen):
        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            self.server.stop()
            self.returncode = 3

    monkeypatch.setattr(L.subprocess, "Popen", Dies)
    p = LocalLLMProvider(env=local_files)
    res = make_plan(REQ, p, fallback=Rules())
    assert res.provider == "rules" and "código 3" in res.errors[0]
    with pytest.raises(ProviderUnavailable, match="código 3"):  # no se relanza en cada pedido
        p.propose(REQ)
    assert len(FakePopen.instances) == 1
    p.close()


def test_startup_timeout_kills_server(local_files, monkeypatch):
    class NeverReady(FakePopen):
        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            self.server.loading = 10**6

    monkeypatch.setattr(L.subprocess, "Popen", NeverReady)
    p = LocalLLMProvider(env=local_files, startup_timeout=0.5)
    with pytest.raises(ProviderUnavailable, match="no respondió"):
        p.start()
    assert FakePopen.instances[0].terminated
    p.close()


# ------------------------------------------------------------------ gramática y prompt
def test_grammar_is_derived_from_the_catalog():
    g = grammar_schema()
    items = g["properties"]["operations"]["items"]
    assert set(items["discriminator"]["mapping"]) == set(OP_NAMES) & set(implemented())
    assert g["properties"]["operations"]["maxItems"] == L.MAX_OPS
    assert not {"asset", "source_prompt", "schema_version"} & set(g["properties"])
    assert g["required"] == list(g["properties"])
    for ref in items["oneOf"]:
        d = g["$defs"][ref["$ref"].rsplit("/", 1)[-1]]
        assert next(iter(d["properties"])) == "op"  # la op se elige antes que sus valores
        assert d["additionalProperties"] is False
        assert "op" in d["required"]
    assert "rect" not in g["$defs"]["Crop"]["required"]  # si no, completa aspect_ratio y rect
    assert {"width", "height"} <= set(g["$defs"]["Resize"]["required"])


def test_grammar_shaped_plans_validate():
    plan = {
        "operations": [
            {"op": "contrast", "amount": 20},
            {"op": "crop", "aspect_ratio": "9:16", "anchor": "center"},
            {"op": "resize", "width": 1080, "height": None, "fit": "contain"},
        ],
        "export": {
            "preset": None,
            "format": "jpeg",
            "quality": 90,
            "color_space": None,
            "metadata": None,
        },  # fmt: skip
        "explanation": "x",
        "unsupported": [{"request": "quitar fondo", "reason": "no está", "alternative": None}],
        "clarification": None,
    }
    assert EditPlan.model_validate(plan).operations[1].aspect_ratio == "9:16"


def test_prompt_mentions_every_op_and_only_real_ones():
    text = system_prompt()
    for op in implemented():
        assert f"- {op} {{" in text
    named = set(re.findall(r"`([a-z_]+)`", L.GUIDE))
    known = set(OP_NAMES) | set(EditPlan.model_fields)
    assert named and named <= known, named - known
    assert "DATOS" in text


def test_auto_plan_without_llm_config_uses_rules(monkeypatch):
    from pstudio.prompting.planner import plan_for

    for var in (L.ENV_URL, L.ENV_SERVER, L.ENV_MODEL):
        monkeypatch.delenv(var, raising=False)
    res = plan_for("subile el contraste")
    assert res.provider == "rules" and res.plan is not None and not res.warnings


# ------------------------------------------------------------------ modelo real (opcional)
@pytest.mark.skipif(
    not (os.environ.get(L.ENV_MODEL) and os.environ.get(L.ENV_SERVER)),
    reason="sin PSTUDIO_LLM_MODEL/PSTUDIO_LLAMA_SERVER: no se prueba el modelo real",
)
def test_real_model_rotates():
    with LocalLLMProvider() as p:
        res = make_plan(REQ, p)
        assert p.proc is not None
        proc = p.proc
    assert proc.poll() is not None  # el servidor quedó detenido
    assert res.plan is not None, res.errors
    assert [o.op for o in res.plan.operations] == ["rotate"]
    assert abs(res.plan.operations[0].degrees) == 90
