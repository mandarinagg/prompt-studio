"""Spike #3: arranque de la app Tauri completa (ventana + engine embebido).

Uso (desde engine/): uv run python spikes/sidecar/measure_app.py [--exe <ruta>] [--rounds 10]
Lanza la app con PSTUDIO_SPIKE_METRICS; la app escribe sus métricas y se cierra sola cuando
la UI (WebView2 + React) y el engine (ping) están listos.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXE = ROOT / "app" / "src-tauri" / "target" / "release" / "prompt-studio.exe"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()

    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(args.rounds + 1):
            metrics_file = Path(tmp) / f"m{i}.json"
            env = {**os.environ, "PSTUDIO_SPIKE_METRICS": str(metrics_file)}
            t0 = time.perf_counter()
            subprocess.run([str(args.exe)], env=env, timeout=60, check=True)
            wall = (time.perf_counter() - t0) * 1000
            m = json.loads(metrics_file.read_text(encoding="utf-8"))
            m["wall_ms"] = wall
            runs.append(m)

    for i, r in enumerate(runs):
        print(f"  ronda {i:2}: " + "  ".join(f"{k}={r[k]:.0f}" for k in r), file=sys.stderr)
    first, rest = runs[0], runs[1:]
    keys = ["engine_spawn_ms", "engine_ready_ms", "ui_ready_ms", "wall_ms"]
    print("| métrica | 1ª ejecución | mediana | p90 |")
    print("|---|---|---|---|")
    for k in keys:
        vals = sorted(r[k] for r in rest)
        p90 = vals[min(len(vals) - 1, int(len(vals) * 0.9))]
        print(f"| {k} | {first[k]:.0f} ms | {statistics.median(vals):.0f} ms | {p90:.0f} ms |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
