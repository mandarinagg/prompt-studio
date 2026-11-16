"""Spike #3: arranque del sidecar (dev vs PyInstaller onedir vs onefile).

Uso (desde engine/): uv run python spikes/sidecar/measure_startup.py [--rounds 10]
Para cada variante: lanza el proceso, mide el tiempo hasta la respuesta a `ping`, a
`engine.version` (carga libvips) y a `image.info` sobre una foto de 24 MP, y cierra stdin.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
PHOTO = ENGINE.parent / "tests" / "fixtures" / "photos" / "candle-lowlight.jpg"
VARIANTS = {
    "dev (python -m pstudio)": [sys.executable, "-m", "pstudio", "rpc"],
    "onedir": [str(ENGINE / "dist" / "onedir" / "pstudio-engine" / "pstudio-engine.exe"), "rpc"],
    "onefile": [str(ENGINE / "dist" / "onefile" / "pstudio-engine.exe"), "rpc"],
    "embed (python.org firmado)": [
        str(ENGINE / "dist" / "embed" / "pstudio-engine" / "python" / "python.exe"),
        "-m",
        "pstudio",
        "rpc",
    ],
}


def one_run(cmd: list[str]) -> dict[str, float]:
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    marks = {}
    requests = [
        ("ping", "ping", {}),
        ("version", "engine.version", {}),
        ("image_info", "image.info", {"path": str(PHOTO)}),
    ]
    for i, (label, method, params) in enumerate(requests, 1):
        req = {"jsonrpc": "2.0", "id": i, "method": method, "params": params}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        assert "result" in resp, resp
        marks[label] = (time.perf_counter() - t0) * 1000
    proc.stdin.close()
    proc.wait(timeout=30)
    marks["exit_code"] = proc.returncode
    return marks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()
    if not PHOTO.is_file():
        print("faltan fixtures: correr tests/fixtures/fetch_fixtures.py", file=sys.stderr)
        return 1

    print(
        "| variante | 1ª respuesta (ping) | + libvips cargado | + leer foto 24 MP | 1ª ejecución |"
    )
    print("|---|---|---|---|---|")
    for name, cmd in VARIANTS.items():
        if not Path(cmd[0]).is_file():
            print(f"| {name} | (no construido) | | | |")
            continue
        try:
            runs = [one_run(cmd) for _ in range(args.rounds + 1)]
        except OSError as exc:  # p. ej. WinError 4551: bloqueado por Smart App Control
            print(f"| {name} | BLOQUEADO ({exc.strerror}) | | | |")
            continue
        first, rest = runs[0], runs[1:]
        assert all(r["exit_code"] == 0 for r in runs)

        def med(key, rest=rest):
            return statistics.median(r[key] for r in rest)

        print(
            f"| {name} | {med('ping'):.0f} ms | {med('version'):.0f} ms "
            f"| {med('image_info'):.0f} ms | {first['image_info']:.0f} ms |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
