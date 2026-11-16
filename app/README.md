# app — PROMPT STUDIO (Tauri 2 + React + TypeScript)

Estado: **spike #3**. Ventana mínima que verifica la comunicación UI → Rust → engine Python.
La UI real llega en M3.

- `src-tauri/src/engine.rs`: cliente JSON-RPC 2.0 del engine (stdio, sin red).
- `src-tauri/src/lib.rs`: comandos `engine_call` y `startup_metrics`.
- El engine viaja como recurso (`engine/`), armado por `engine/packaging/build_embed.py` (ADR-0006).

Comandos y requisitos (incluido Smart App Control desactivado): ver `docs/INSTALLATION.md`.
