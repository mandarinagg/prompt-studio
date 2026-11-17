"""Arma el runtime del sidecar: Python embebible oficial (firmado por la PSF) + pstudio.

Uso (desde engine/): uv run python packaging/build_embed.py
Resultado: engine/dist/embed/pstudio-engine/{python/, lib/}. La app Tauri lo incluye como
recurso y lanza `python/python.exe -I -m pstudio rpc` (ver spikes/sidecar/RESULTS.md).

Por qué no PyInstaller: su bootloader fue bloqueado por Smart App Control y arranca más lento.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PY_VERSION = "3.14.10"  # misma versión exacta que .python-version (ADR-0008)
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
EMBED_SHA256 = "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159"

ENGINE = Path(__file__).resolve().parents[1]
DIST = ENGINE / "dist"
OUT = DIST / "embed" / "pstudio-engine"
CACHE = DIST / "cache"


def fetch_embed() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE / Path(EMBED_URL).name
    if not zip_path.is_file():
        print(f"descargando {EMBED_URL}")
        req = urllib.request.Request(EMBED_URL, headers={"User-Agent": "prompt-studio-build"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            zip_path.write_bytes(resp.read())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if digest != EMBED_SHA256:
        zip_path.unlink()
        sys.exit(f"SHA-256 inesperado para {zip_path.name}: {digest}")
    return zip_path


def run(*args: str) -> None:
    subprocess.run(args, cwd=ENGINE, check=True)


def main() -> None:
    zip_path = fetch_embed()
    if OUT.exists():
        shutil.rmtree(OUT)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(OUT / "python")

    wheel_dir = DIST / "wheel"
    shutil.rmtree(wheel_dir, ignore_errors=True)
    run("uv", "build", "--wheel", "--out-dir", str(wheel_dir))
    wheel = next(wheel_dir.glob("pstudio-*.whl"))
    run(
        "uv", "pip", "install", "--quiet", "--target", str(OUT / "lib"),
        "--python-version", "3.14", "--python-platform", "x86_64-pc-windows-msvc", str(wheel),
    )  # fmt: skip
    # ._pth: rutas de import del Python embebible (no lee PYTHONPATH ni site-packages del sistema)
    tag = "".join(PY_VERSION.split(".")[:2])
    (OUT / "python" / f"python{tag}._pth").write_text(
        f"python{tag}.zip\n.\n..\\lib\n", encoding="ascii", newline="\n"
    )
    shutil.rmtree(OUT / "lib" / "bin", ignore_errors=True)  # scripts de consola: no se usan

    out = subprocess.run(
        [str(OUT / "python" / "python.exe"), "-I", "-m", "pstudio", "rpc"],
        input='{"jsonrpc":"2.0","id":1,"method":"engine.version"}\n',
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 2**20
    print(f"listo: {OUT} ({size:.0f} MB)\n{out.stdout.strip()}")


if __name__ == "__main__":
    main()
