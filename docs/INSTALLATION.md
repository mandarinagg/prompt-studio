# Instalación (entorno de desarrollo, Windows)

Faltan en el equipo actual: **Rust**, **FFmpeg**, **uv/Python 3.12**.

```powershell
# Rust (requerido por Tauri 2) + WebView2 ya viene con Windows 11
winget install Rustlang.Rustup
# Build Tools de C++ si no están: winget install Microsoft.VisualStudio.2022.BuildTools

# uv y Python 3.12 para el engine
winget install astral-sh.uv
uv python install 3.12

# FFmpeg — para desarrollo cualquier build sirve; para distribuir usar build LGPL (ver ADR-0004)
winget install Gyan.FFmpeg
ffmpeg -hide_banner -encoders | findstr amf   # verificar encoders AMD
```

Engine (desde M1):
```powershell
cd engine
uv sync
uv run pytest
```

App (desde M3):
```powershell
cd app
pnpm install
pnpm tauri dev
```
