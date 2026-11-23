"""RPC del engine para la app: JSON-RPC 2.0 por stdio, métodos tipados con Pydantic."""

from pstudio.rpc.server import (
    ENGINE_ERROR,
    EVENTS,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    METHODS,
    NO_PROJECT,
    PARSE_ERROR,
    PROJECT_CHANGED,
    Notifier,
    RpcError,
    handle_line,
    serve,
)

# Registran sus métodos al importarse.
from pstudio.rpc import methods_core, methods_jobs, methods_media, methods_project  # noqa: E402, F401  isort: skip

__all__ = [
    "ENGINE_ERROR",
    "EVENTS",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "METHODS",
    "NO_PROJECT",
    "PARSE_ERROR",
    "PROJECT_CHANGED",
    "Notifier",
    "RpcError",
    "handle_line",
    "serve",
]
