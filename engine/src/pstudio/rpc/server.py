"""Servidor JSON-RPC 2.0 sobre stdio (una petición/respuesta JSON por línea).

Es el único canal entre la app (Tauri) y el engine: sin red ni puertos abiertos (ARCHITECTURE.md).
stdout se reserva para el protocolo; cualquier `print` accidental se desvía a stderr.

Cada método se registra con `@method("grupo.nombre")`. Sus params son un modelo Pydantic (se
validan antes de llamar) y su resultado se serializa con Pydantic. De ese registro sale el
contrato en JSON Schema y, de ahí, los tipos TS de la app (`contract.py`). Los eventos son
notificaciones JSON-RPC (sin `id`) que el engine emite por su cuenta, también desde otros hilos:
todas las escrituras a stdout pasan por el lock de `Notifier`.
"""

from __future__ import annotations

import json
import sys
import threading
import typing
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from pstudio.project.store import ProjectError

if TYPE_CHECKING:
    from pstudio.rpc.session import Session

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
ENGINE_ERROR = -32000
NO_PROJECT = -32001
PROJECT_CHANGED = -32002


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Params(BaseModel):
    """Base de los params: un campo desconocido es un error (no se ignora en silencio)."""

    model_config = ConfigDict(extra="forbid")


class NoParams(Params):
    pass


@dataclass
class Method:
    name: str
    params: type[BaseModel]
    result: Any
    fn: Callable[..., Any]
    takes_params: bool
    adapter: TypeAdapter


METHODS: dict[str, Method] = {}
EVENTS: dict[str, type[BaseModel]] = {}


def method(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registra `fn(session)` o `fn(session, p: ModeloParams) -> Resultado`."""

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        hints = typing.get_type_hints(fn)
        params = hints.get("p", NoParams)
        result = hints["return"]
        METHODS[name] = Method(name, params, result, fn, "p" in hints, TypeAdapter(result))
        return fn

    return register


def event(name: str) -> Callable[[type[BaseModel]], type[BaseModel]]:
    def register(model: type[BaseModel]) -> type[BaseModel]:
        EVENTS[name] = model
        return model

    return register


class Notifier:
    """Escritor de líneas JSON con lock: respuestas del bucle y eventos de los workers."""

    def __init__(self, out: IO[str]) -> None:
        self._out = out
        self._lock = threading.Lock()

    def send(self, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self._lock:
            self._out.write(line)
            self._out.flush()

    def emit(self, name: str, payload: BaseModel) -> None:
        self.send({"jsonrpc": "2.0", "method": name, "params": payload.model_dump(mode="json")})


# ------------------------------------------------------------------------------------- despacho
def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors(include_url=False):
        loc = ".".join(str(x) for x in e["loc"])
        parts.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return "; ".join(parts[:5])


_default_session: Session | None = None


def _session() -> Session:
    global _default_session
    if _default_session is None:
        from pstudio.rpc.session import Session

        _default_session = Session()
    return _default_session


def handle_line(line: str, session: Session | None = None) -> dict[str, Any] | None:
    """Procesa una línea. Devuelve la respuesta, o None si era una notificación (sin id)."""
    try:
        req = json.loads(line)
    except json.JSONDecodeError:
        return _error(None, PARSE_ERROR, "JSON inválido")
    if (
        not isinstance(req, dict)
        or req.get("jsonrpc") != "2.0"
        or not isinstance(req.get("method"), str)
    ):
        return _error(
            req.get("id") if isinstance(req, dict) else None, INVALID_REQUEST, "petición inválida"
        )
    req_id = req.get("id")
    is_notification = "id" not in req
    m = METHODS.get(req["method"])
    raw = req.get("params", {})
    try:
        if m is None:
            raise RpcError(METHOD_NOT_FOUND, f"método desconocido: {req['method']}")
        if not isinstance(raw, dict):
            raise RpcError(INVALID_PARAMS, "params debe ser un objeto")
        try:
            p = m.params.model_validate(raw)
        except ValidationError as exc:
            raise RpcError(INVALID_PARAMS, _validation_message(exc)) from exc
        s = session or _session()
        value = m.fn(s, p) if m.takes_params else m.fn(s)
        result = m.adapter.dump_python(value, mode="json")
    except RpcError as exc:
        return None if is_notification else _error(req_id, exc.code, exc.message)
    except ProjectError as exc:
        return None if is_notification else _error(req_id, ENGINE_ERROR, str(exc))
    except OSError as exc:
        name = Path(exc.filename).name if exc.filename else ""
        msg = f"no se pudo usar {name}: {exc.strerror or exc}" if name else str(exc.strerror or exc)
        return None if is_notification else _error(req_id, ENGINE_ERROR, msg)
    except Exception as exc:  # nunca tumbar el servidor por un fallo de un método
        print(f"error interno en {req['method']}: {exc!r}", file=sys.stderr)
        return None if is_notification else _error(req_id, ENGINE_ERROR, "error interno")
    return None if is_notification else {"jsonrpc": "2.0", "id": req_id, "result": result}


def serve(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> None:
    """Bucle principal: lee hasta EOF (la app cierra stdin para apagar el engine)."""
    from pstudio.rpc.session import Session

    if stdin is None:
        # El protocolo es UTF-8. En Windows, con pipes, Python usa la página de códigos ANSI
        # (cp1252): rutas como "Año/日本.jpg" llegaban rotas y daban "no existe el archivo".
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if stdout is None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout
    if stdout is None:
        sys.stdout = sys.stderr  # protege el canal: prints sueltos van a stderr
    notifier = Notifier(out)
    session = Session(notifier)
    try:
        for line in stdin:
            if not line.strip():
                continue
            response = handle_line(line, session)
            if response is not None:
                notifier.send(response)
    finally:
        session.close()
