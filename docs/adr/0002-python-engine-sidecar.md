# ADR-0002 — Engine en Python 3.12 como sidecar, CLI-first

- **Estado:** Aceptado (2026-11-16)
- **Fecha:** 2026-11-12

## Decisión
Paquete Python `pstudio` (Python 3.12, gestionado con `uv`) que funciona como CLI y como
sidecar de Tauri vía JSON-RPC sobre stdio. Pydantic v2 es la fuente única del esquema;
se exporta JSON Schema y se generan tipos TS. Librerías candidatas: pyvips, OpenCV, numpy, FFmpeg.

## Motivos
Ecosistema de imagen/ML maduro, iteración rápida, testeable por Claude Code desde terminal.

## Riesgos
Empaquetado y tiempo de arranque → resuelto en el spike #3: ver ADR-0006 (Python embebible). Si el rendimiento de
preview no alcanza, mover ops calientes a Rust/numba sin cambiar el contrato.
