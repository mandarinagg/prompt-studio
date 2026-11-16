"""Corre bench.py para cada backend × imagen y escribe results.json + tabla en consola.

Uso (desde engine/): uv run --group spike python spikes/imaging/run_all.py
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import PIL
import pyvips

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parents[2] / "tests" / "fixtures" / "photos"
IMAGES = ["candle-lowlight", "starry-night-noise", "backlit-tree", "product-white"]
BACKENDS = ["pillow", "opencv", "pyvips"]
METRICS = [
    "open_proxy",
    "preview_1op",
    "preview_4op",
    "preview_10op",
    "export_4op",
    "export_10op",
]


def main() -> int:
    rows = []
    for image in IMAGES:
        path = FIXTURES / f"{image}.jpg"
        if not path.is_file():
            print(f"falta {path}; correr tests/fixtures/fetch_fixtures.py", file=sys.stderr)
            return 1
        for backend in BACKENDS:
            print(f"… {backend:7} {image}", file=sys.stderr, flush=True)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "bench.py"),
                    "--backend",
                    backend,
                    "--image",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            rows.append(json.loads(proc.stdout.strip().splitlines()[-1]))

    env = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "opencv": cv2.__version__,
        "libvips": ".".join(str(pyvips.version(i)) for i in range(3)),
        "cpu": platform.processor(),
    }
    (HERE / "results.json").write_text(
        json.dumps({"env": env, "rows": rows}, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    header = "| imagen | backend | " + " | ".join(METRICS) + " | pico RAM |"
    print(header)
    print("|" + "---|" * (len(METRICS) + 3))
    for r in rows:
        cells = " | ".join(f"{r[m]['median_ms']:.0f}" for m in METRICS)
        print(f"| {r['image']} | {r['backend']} | {cells} | {r['peak_mem_mb']} MB |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
