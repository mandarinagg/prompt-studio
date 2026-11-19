"""Métodos básicos: salud del engine e info de una imagen."""

from __future__ import annotations

import platform
from pathlib import Path

from pydantic import BaseModel

from pstudio import __version__
from pstudio.rpc.server import ENGINE_ERROR, Params, RpcError, method
from pstudio.rpc.session import Session


class EngineVersion(BaseModel):
    pstudio: str
    python: str
    libvips: str


class PathParams(Params):
    path: str


class ImageInfo(BaseModel):
    width: int
    height: int
    bands: int
    format: str


@method("ping")
def ping(s: Session) -> str:
    return "pong"


@method("engine.version")
def engine_version(s: Session) -> EngineVersion:
    import pyvips

    return EngineVersion(
        pstudio=__version__,
        python=platform.python_version(),
        libvips=".".join(str(pyvips.version(i)) for i in range(3)),
    )


@method("image.info")
def image_info(s: Session, p: PathParams) -> ImageInfo:
    import pyvips

    file = Path(p.path)
    if not file.is_file():
        raise RpcError(ENGINE_ERROR, f"no existe el archivo: {file.name}")
    try:
        img = pyvips.Image.new_from_file(str(file), access="sequential")
    except pyvips.Error as exc:
        raise RpcError(ENGINE_ERROR, f"formato no soportado: {file.name}") from exc
    return ImageInfo(width=img.width, height=img.height, bands=img.bands, format=img.format)
