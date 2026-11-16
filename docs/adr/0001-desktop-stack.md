# ADR-0001 — Stack de escritorio: Tauri 2 + React + TypeScript

- **Estado:** Propuesto — validado por el spike #3, pendiente de aprobación
- **Fecha:** 2026-11-12

## Contexto
Necesitamos una app de escritorio Windows-first con visor de imagen/video y timeline.

## Decisión
Tauri 2 + React + TypeScript + Vite. En Windows Tauri usa WebView2 (Chromium), así que la
reproducción de video y las APIs web son equivalentes a Electron.

## Alternativas
- **Electron:** más maduro, sin Rust, pero ~150 MB más pesado y mayor uso de RAM (relevante con 16 GB).
- **Qt/PySide:** UI nativa en Python, pero UI de timeline y diseño moderno más costosos.

## Consecuencias
Requiere instalar Rust. La lógica pesada no vive en Rust sino en el engine Python (ADR-0002);
Rust queda como capa delgada de shell/IPC.

## Validación (spike #3, 2026-11-16)
Ver [`engine/spikes/sidecar/RESULTS.md`](../../engine/spikes/sidecar/RESULTS.md).
- Instalador NSIS de **23.7 MB** con el engine Python y libvips incluidos (85 MB instalado).
- App instalada: **UI lista en ~0.8 s y engine listo en ~0.95 s** (objetivo < 3 s).
- JSON-RPC sobre stdio entre Rust y Python, sin red ni puertos. Empaquetado del engine:
  ADR-0006.
- **Requisito de desarrollo:** con Smart App Control activado no compila (Cargo ejecuta build
  scripts sin firma). En la máquina de desarrollo SAC tiene que estar desactivado.
- **Requisito de distribución:** el instalador tiene que estar firmado para usuarios con SAC.
