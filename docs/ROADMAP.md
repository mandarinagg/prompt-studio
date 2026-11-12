# Roadmap

Cada milestone tiene un entregable demostrable. Tamaños relativos (S/M/L), no fechas:
se recalibran al cerrar M0 con datos reales de velocidad.

| Milestone | Entregable | Tamaño | Release |
|---|---|---|---|
| **M0 — Fundaciones** | Herramientas instaladas, spikes de rendimiento y empaquetado, ADRs aprobados | S | — |
| **M1 — Motor de foto (CLI)** | `pstudio apply plan.json in.jpg -o out.jpg` con catálogo v1, golden tests | M | — |
| **M2 — Motor de prompts (CLI)** | `pstudio plan "..." in.jpg` con proveedor de reglas + LLM local, evals | M | — |
| **M3 — App de escritorio foto** | Tauri: biblioteca, visor, sliders, prompt, plan, preview, historial, export, lote | L | **v0.1** |
| **M4 — Video básico** | Timeline OTIO, cortes, unión, texto, audio, proxies, render | L | **v0.2** |
| **M5 — Prompts de video** | Plan aplicado al timeline | M | v0.3 |
| **M6 — IA local** | Fondo, upscaling, denoise IA, subtítulos (whisper.cpp) según hardware | L | v0.4 |
| **M7 — Avanzado** | Máscaras, curvas, RAW, tracking, plantillas | L | v0.5+ |

## M0 — Fundaciones (detalle)
- [ ] Instalar Rust, FFmpeg (build LGPL), uv + Python 3.12.
- [ ] Spike: pyvips vs OpenCV vs Pillow — tiempo de preview/export en 24 MP.
- [ ] Spike: sidecar Python dentro de Tauri (PyInstaller) — tamaño y arranque.
- [ ] Spike: FFmpeg AMF (h264_amf/hevc_amf) en la RX 6600 XT.
- [ ] Spike: llama.cpp Vulkan + JSON Schema con modelo 7–8B Q4 — latencia y validez.
- [ ] Aprobar ADR-0001…0004.
- [ ] Fixtures de prueba con licencia libre (fotos 24 MP, contraluz, interior cálido, ruido).

## Fuera de roadmap hasta nuevo aviso
Ver "Fuera de alcance" en `PRODUCT_SPEC.md`.
