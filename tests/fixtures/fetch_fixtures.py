"""Descarga y verifica las fotos de prueba CC0 listadas en manifest.json.

Uso (desde la raíz del repo):
    uv run --no-project --python 3.14 tests/fixtures/fetch_fixtures.py            # descargar + verificar
    uv run --no-project --python 3.14 tests/fixtures/fetch_fixtures.py --verify   # solo verificar
    uv run --no-project --python 3.14 tests/fixtures/fetch_fixtures.py --sources  # regenerar SOURCES.md

Solo usa la biblioteca estándar. Los archivos van a tests/fixtures/photos/ (ignorado por git).
Cada archivo se verifica contra el SHA-1 publicado por Wikimedia Commons y el SHA-256 fijado
en el manifiesto. `--pin` completa los SHA-256 vacíos tras una descarga verificada por SHA-1.
Wikimedia limita la descarga de originales (HTTP 429, Retry-After de hasta 10 min); el script
lo respeta, así que la primera descarga completa puede tardar ~15 min.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
PHOTOS = HERE / "photos"
SOURCES = HERE / "SOURCES.md"
USER_AGENT = "prompt-studio-fixtures/0.1 (open-source test tooling)"
CHUNK = 1 << 20


def hashes(path: Path) -> tuple[str, str]:
    sha1, sha256 = hashlib.sha1(), hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            sha1.update(chunk)
            sha256.update(chunk)
    return sha1.hexdigest(), sha256.hexdigest()


def is_valid(path: Path, entry: dict) -> bool:
    if not path.is_file() or path.stat().st_size != entry["bytes"]:
        return False
    sha1, sha256 = hashes(path)
    return sha1 == entry["sha1"] and (not entry["sha256"] or sha256 == entry["sha256"])


def download(url: str, dest: Path, attempts: int = 5) -> bool:
    """Descarga a `dest`. Respeta HTTP 429/Retry-After. Devuelve False si se agotan los intentos."""
    tmp = dest.with_suffix(".part")
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as out:
                while chunk := resp.read(CHUNK):
                    out.write(chunk)
            tmp.replace(dest)
            return True
        except (urllib.error.URLError, TimeoutError) as exc:
            tmp.unlink(missing_ok=True)
            if attempt == attempts:
                print(f"    sin éxito tras {attempts} intentos: {str(exc)[:80]}")
                return False
            retry_after = getattr(exc, "headers", None) and exc.headers.get("Retry-After")
            wait = (
                int(retry_after)
                if retry_after and retry_after.isdigit()
                else 15 * 2 ** (attempt - 1)
            )
            print(f"    reintento {attempt}/{attempts - 1} en {wait}s ({str(exc)[:60]})")
            time.sleep(wait)
    return False


def save_manifest(manifest: dict) -> None:
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    write_sources(manifest["photos"])


def write_sources(photos: list[dict]) -> None:
    lines = [
        "# Fuentes de fixtures",
        "",
        "Solo medios CC0 / dominio público. Generado desde `manifest.json` con",
        "`fetch_fixtures.py --sources`; no editar a mano.",
        "",
        "Descarga: `uv run --no-project --python 3.14 tests/fixtures/fetch_fixtures.py`",
        "(los archivos quedan en `tests/fixtures/photos/`, ignorado por git).",
        "",
        "| id | Caso | Resolución | Licencia | Autor | Origen | SHA-256 |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in photos:
        mp = p["width"] * p["height"] / 1e6
        lines.append(
            f"| `{p['id']}` | {p['purpose']} | {p['width']}×{p['height']} ({mp:.1f} MP) "
            f"| {p['license']} | {p['author']} | [Commons]({p['page']}) | `{p['sha256'][:16]}…` |"
        )
    SOURCES.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="solo verificar, no descargar")
    parser.add_argument("--pin", action="store_true", help="completar SHA-256 vacíos")
    parser.add_argument("--sources", action="store_true", help="regenerar SOURCES.md")
    args = parser.parse_args()
    # progreso visible aunque la salida sea un pipe; UTF-8 para la consola de Windows
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    photos = manifest["photos"]
    if args.sources:
        write_sources(photos)
        print(f"SOURCES.md regenerado ({len(photos)} fotos)")
        return 0

    PHOTOS.mkdir(exist_ok=True)
    failures, downloaded = 0, False
    for entry in photos:
        dest = PHOTOS / f"{entry['id']}.jpg"
        label = f"{entry['id']:20} {entry['bytes'] / 1e6:5.1f} MB"
        if not is_valid(dest, entry):
            if args.verify:
                print(f"FALTA/INVÁLIDO {label}")
                failures += 1
                continue
            if downloaded:
                time.sleep(5)  # cortesía: Wikimedia limita descargas de originales
            print(f"bajando {label} ...")
            downloaded = True
            if not download(entry["url"], dest) or not is_valid(dest, entry):
                dest.unlink(missing_ok=True)
                print(f"FALLÓ {label}")
                failures += 1
                continue
        if not entry["sha256"]:
            if args.pin:
                entry["sha256"] = hashes(dest)[1]
                save_manifest(manifest)  # guardar en cada paso: una falla no pierde lo fijado
            else:
                print(f"AVISO {entry['id']}: sin SHA-256 fijado; correr con --pin")
        print(f"ok   {label}")
    print(f"\n{len(photos) - failures}/{len(photos)} fotos válidas en {PHOTOS}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
