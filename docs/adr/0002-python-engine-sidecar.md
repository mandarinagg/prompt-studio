# ADR-0002 — Engine en Python 3.12 como sidecar, CLI-first

- **Estado:** Propuesto
- **Fecha:** 2026-11-12

## Decisión
Paquete Python `pstudio` (Python 3.12, gestionado con `uv`) que funciona como CLI y como
sidecar de Tauri vía JSON-RPC sobre stdio. Pydantic v2 es la fuente única del esquema;
se exporta JSON Schema y se generan tipos TS. Librerías candidatas: pyvips, OpenCV, numpy, FFmpeg.

## Motivos
Ecosistema de imagen/ML maduro, iteración rápida, testeable por Claude Code desde terminal.

## Riesgos
Empaquetado (PyInstaller/Nuitka) y tiempo de arranque → spike en M0. Si el rendimiento de
preview no alcanza, mover ops calientes a Rust/numba sin cambiar el contrato.
