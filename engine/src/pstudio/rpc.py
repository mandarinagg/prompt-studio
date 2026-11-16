"""Servidor JSON-RPC 2.0 sobre stdio (una petición/respuesta JSON por línea).

Es el único canal entre la app (Tauri) y el engine: sin red ni puertos abiertos (ARCHITECTURE.md).
stdout se reserva para el protocolo; cualquier `print` accidental se desvía a stderr.
"""

from __future__ import annotations

import inspect
import json
import platform
import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from pstudio import __version__

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
ENGINE_ERROR = -32000


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------------------------- métodos
def ping() -> str:
    return "pong"


def engine_version() -> dict[str, str]:
    import pyvips

    return {
        "pstudio": __version__,
        "python": platform.python_version(),
        "libvips": ".".join(str(pyvips.version(i)) for i in range(3)),
    }


def image_info(path: str) -> dict[str, Any]:
    import pyvips

    file = Path(path)
    if not file.is_file():
        raise RpcError(ENGINE_ERROR, f"no existe el archivo: {file.name}")
    try:
        img = pyvips.Image.new_from_file(str(file), access="sequential")
    except pyvips.Error as exc:
        raise RpcError(ENGINE_ERROR, f"formato no soportado: {file.name}") from exc
    return {"width": img.width, "height": img.height, "bands": img.bands, "format": img.format}


METHODS: dict[str, Callable[..., Any]] = {
    "ping": ping,
    "engine.version": engine_version,
    "image.info": image_info,
}


# ------------------------------------------------------------------------------------- despacho
def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_line(line: str) -> dict[str, Any] | None:
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
    method = METHODS.get(req["method"])
    params = req.get("params", {})
    try:
        if method is None:
            raise RpcError(METHOD_NOT_FOUND, f"método desconocido: {req['method']}")
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params debe ser un objeto")
        try:
            inspect.signature(method).bind(**params)
        except TypeError as exc:
            raise RpcError(INVALID_PARAMS, str(exc)) from exc
        result = method(**params)
    except RpcError as exc:
        return None if is_notification else _error(req_id, exc.code, exc.message)
    except Exception as exc:  # nunca tumbar el servidor por un fallo de un método
        print(f"error interno en {req['method']}: {exc!r}", file=sys.stderr)
        return None if is_notification else _error(req_id, ENGINE_ERROR, "error interno")
    return None if is_notification else {"jsonrpc": "2.0", "id": req_id, "result": result}


def serve(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> None:
    """Bucle principal: lee hasta EOF (la app cierra stdin para apagar el engine)."""
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout
    if stdout is None:
        sys.stdout = sys.stderr  # protege el canal: prints sueltos van a stderr
    for line in stdin:
        if not line.strip():
            continue
        response = handle_line(line)
        if response is not None:
            out.write(json.dumps(response, ensure_ascii=False) + "\n")
            out.flush()
