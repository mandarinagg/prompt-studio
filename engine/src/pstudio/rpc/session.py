"""Estado del engine mientras la app está abierta: el proyecto abierto y sus cachés."""

from __future__ import annotations

from pstudio.rpc.server import Notifier


class Session:
    def __init__(self, notifier: Notifier | None = None) -> None:
        self.notifier = notifier

    def close(self) -> None:
        pass
