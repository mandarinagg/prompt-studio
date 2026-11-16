"""Spike #4: encode 1080p por hardware (AMD AMF) vs software, velocidad y calidad (VMAF).

Uso (desde engine/): uv run python spikes/video/amf_bench.py [--bitrates 6 12]
Requiere ffmpeg/ffprobe (build LGPL de ADR-0004) en el PATH o en
%LOCALAPPDATA%/Programs/ffmpeg-lgpl, y las fotos de tests/fixtures (fetch_fixtures.py).

1. Genera un clip de referencia de 20 s 1080p30 sin pérdida (FFV1) a partir de 4 fotos CC0 con
   paneo/zoom: textura real, ruido de ISO alto, piel y movimiento continuo. Contenedor NUT
   (timestamps exactos) para que la comparación cuadro a cuadro sea válida.
2. Codifica con cada encoder al mismo bitrate objetivo y mide tiempo y bitrate real.
3. Mide VMAF (modelo vmaf_v0.6.1), PSNR y SSIM contra la referencia con libvmaf.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
PHOTOS = ENGINE.parent / "tests" / "fixtures" / "photos"
WORK = ENGINE / "dist" / "video"
# NUT y no MKV: MKV redondea timestamps a 1 ms y al pasar a MP4 a 30 fps constantes ffmpeg
# duplicaba/descartaba cuadros (VMAF mín ~31 en los cuadros 123/246/492 con cualquier encoder).
SOURCE = WORK / "source_1080p30.nut"
DURATION_S = 20
FPS = 30
HERE = Path(__file__).resolve().parent


def ffmpeg_bin(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for bindir in (Path(os.environ["LOCALAPPDATA"]) / "Programs" / "ffmpeg-lgpl").glob("*/bin"):
        if (bindir / f"{name}.exe").is_file():
            return str(bindir / f"{name}.exe")
    sys.exit(f"no se encontró {name}")


FFMPEG, FFPROBE = ffmpeg_bin("ffmpeg"), ffmpeg_bin("ffprobe")


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def make_source() -> None:
    if SOURCE.is_file():
        return
    WORK.mkdir(parents=True, exist_ok=True)
    frames = FPS * DURATION_S // 4  # 150 cuadros por foto
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"  # centrado
    wide = "scale=3840:-2"
    clips = [  # (foto, prefiltro, zoom, x, y)
        ("starry-night-noise", wide, "1+0.0015*on", cx, cy),
        ("warm-restaurant", wide, "1.2", "on*4", cy),
        ("backlit-tree", wide, "1.4-0.0015*on", cx, cy),
        ("stage-portrait", f"{wide},crop=3840:2160:0:1400", "1.1", cx, "on"),
    ]
    inputs, chains = [], []
    for i, (photo, pre, z, x, y) in enumerate(clips):
        inputs += ["-i", str(PHOTOS / f"{photo}.jpg")]  # una sola imagen: zoompan genera d cuadros
        chains.append(
            f"[{i}]{pre},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s=1920x1080:fps={FPS}[v{i}]"
        )
    graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(4))
    graph += "concat=n=4:v=1,format=yuv420p,setsar=1"
    t0 = time.perf_counter()
    proc = run([*inputs, "-filter_complex", graph, "-c:v", "ffv1", "-level", "3", str(SOURCE)])
    if proc.returncode:
        sys.exit(proc.stderr[-2000:])
    print(f"referencia generada en {time.perf_counter() - t0:.0f} s", file=sys.stderr)


def encoders(kbps: int) -> dict[str, list[str]]:
    b = ["-b:v", f"{kbps}k", "-maxrate", f"{kbps * 3 // 2}k", "-bufsize", f"{kbps * 2}k"]
    amf = ["-rc", "vbr_peak", *b]
    return {
        "h264_amf speed": ["-c:v", "h264_amf", "-quality", "speed", *amf],
        "h264_amf balanced": ["-c:v", "h264_amf", "-quality", "balanced", *amf],
        "h264_amf quality": ["-c:v", "h264_amf", "-quality", "quality", *amf],
        "hevc_amf speed": ["-c:v", "hevc_amf", "-quality", "speed", *amf],
        "hevc_amf quality": ["-c:v", "hevc_amf", "-quality", "quality", *amf],
        "av1_amf": ["-c:v", "av1_amf", *amf],  # RDNA2 no codifica AV1: se espera que falle
        "libopenh264 (CPU)": ["-c:v", "libopenh264", *b],
        "libsvtav1 p8 (CPU)": ["-c:v", "libsvtav1", "-preset", "8", "-b:v", f"{kbps}k"],
    }  # fmt: skip


def quality(encoded: Path) -> dict[str, float]:
    log = WORK / "vmaf.json"
    graph = (
        # Emparejar cuadro a cuadro en una base de tiempo común y entera. Con pts originales o con
        # setpts=N/FRAME_RATE/TB (bases 1/61440 vs 1/15360) libvmaf comparaba algunos cuadros
        # contra su vecino (VMAF mín ~31 incluso casi sin pérdida). Verificado: una copia sin
        # pérdida da PSNR infinito en los 600 cuadros con este grafo.
        "[0:v]settb=1/30,setpts=N[dist];[1:v]settb=1/30,setpts=N[ref];"
        f"[dist][ref]libvmaf=log_fmt=json:log_path={log.name}:n_threads=12:"
        "feature=name=psnr|name=float_ssim"
    )
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(encoded), "-i", str(SOURCE),
         "-lavfi", graph, "-f", "null", "-"],
        capture_output=True, text=True, cwd=WORK, encoding="utf-8", errors="replace",
    )  # fmt: skip
    if proc.returncode:
        raise RuntimeError(proc.stderr[-1500:])
    pooled = json.loads(log.read_text(encoding="utf-8"))["pooled_metrics"]
    return {
        "vmaf": round(pooled["vmaf"]["mean"], 2),
        "vmaf_min": round(pooled["vmaf"]["min"], 2),
        "psnr_y": round(pooled["psnr_y"]["mean"], 2),
        "ssim": round(pooled["float_ssim"]["mean"], 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bitrates", type=int, nargs="+", default=[6, 12], help="Mbps")
    args = parser.parse_args()
    make_source()

    rows = []
    for mbps in args.bitrates:
        for name, opts in encoders(mbps * 1000).items():
            ext = "mkv" if "av1" in name else "mp4"
            out = WORK / f"{name.split()[0]}_{name.split()[-1].strip('()')}_{mbps}M.{ext}"
            print(f"… {mbps:>2} Mbps {name}", file=sys.stderr, flush=True)
            t0 = time.perf_counter()
            proc = run(["-i", str(SOURCE), "-an", *opts, str(out)])
            seconds = time.perf_counter() - t0
            row = {"encoder": name, "target_mbps": mbps}
            if proc.returncode:
                last = [ln for ln in proc.stderr.splitlines() if ln.strip()][-3:]
                row["error"] = " | ".join(last)[:300]
                rows.append(row)
                continue
            row["seconds"] = round(seconds, 2)
            row["fps"] = round(FPS * DURATION_S / seconds, 1)
            row["realtime_x"] = round(DURATION_S / seconds, 1)
            row["actual_mbps"] = round(out.stat().st_size * 8 / DURATION_S / 1e6, 2)
            row.update(quality(out))
            rows.append(row)

    ver = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True).stdout.split("\n")[0]
    (HERE / "results.json").write_text(
        json.dumps({"ffmpeg": ver, "rows": rows}, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("| Mbps | encoder | fps | ×tiempo real | Mbps real | VMAF | VMAF mín | PSNR-Y | SSIM |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        if "error" in r:
            print(f"| {r['target_mbps']} | {r['encoder']} | ❌ {r['error']} | | | | | | |")
        else:
            print(
                f"| {r['target_mbps']} | {r['encoder']} | {r['fps']} | {r['realtime_x']}× "
                f"| {r['actual_mbps']} | {r['vmaf']} | {r['vmaf_min']} | {r['psnr_y']} "
                f"| {r['ssim']} |"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
