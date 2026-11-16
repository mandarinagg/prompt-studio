# Instalación (entorno de desarrollo, Windows)

Probado en Windows 11 (2026-11-15). Ninguno de estos pasos cambia el `python` del sistema.

> **Smart App Control tiene que estar desactivado en la máquina de desarrollo**: bloquea los
> build scripts de Cargo y no se puede compilar Tauri (`os error 4551`). Seguridad de Windows →
> Control de aplicaciones y navegador → Smart App Control → Desactivado. Ver ADR-0001.

```powershell
# Rust (requerido por Tauri 2); WebView2 ya viene con Windows 11
winget install --id Rustlang.Rustup -e
# Build Tools de C++ (MSVC + Windows SDK, ~6-7 GB), requeridas por Rust en Windows
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

# uv y Python 3.12 para el engine (aislado: no reemplaza el python del sistema)
winget install astral-sh.uv
uv python install 3.12 --no-bin

# FFmpeg LGPL (ADR-0004): build estable de BtbN, verificado por checksum
gh release download latest -R BtbN/FFmpeg-Builds -p "ffmpeg-n9.0-latest-win64-lgpl-9.0.zip" -p checksums.sha256
#   verificar sha256, descomprimir en %LOCALAPPDATA%\Programs\ffmpeg-lgpl y agregar su bin\ al PATH de usuario
```

Verificación:
```powershell
rustc --version
ffmpeg -hide_banner -buildconf | findstr "gpl x264"    # no debe aparecer --enable-gpl
ffmpeg -hide_banner -encoders | findstr amf             # h264_amf / hevc_amf
uv run --no-project --python 3.12 python -V             # Python 3.12.x
```

Engine (desde M1):
```powershell
cd engine
uv sync
uv run pytest
```

App:
```powershell
cd engine
uv run python packaging/build_embed.py   # runtime del engine (python.org embebible + pstudio)
cd ../app
pnpm install
pnpm tauri dev                           # desarrollo
pnpm tauri build                         # instalador NSIS en src-tauri/target/release/bundle/nsis
```
