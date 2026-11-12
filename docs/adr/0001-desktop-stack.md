# ADR-0001 — Stack de escritorio: Tauri 2 + React + TypeScript

- **Estado:** Propuesto (confirmar con spike de M0)
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
