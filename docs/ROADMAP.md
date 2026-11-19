# Roadmap

Cada milestone tiene un entregable demostrable. Tamaños relativos (S/M/L), no fechas.

## Velocidad observada (recalibración al cerrar M0, 2026-11-16)
M0 (tamaño **S**) cerró sus 7 issues en **2 sesiones de trabajo**: 12 PRs y 8 ADRs aceptados
(0001–0008). Cada spike llevó entre 1 y 3 horas. El tiempo se fue más en el entorno y la
medición que en el código: Smart App Control bloqueando Cargo, el emparejamiento de cuadros en
VMAF y el contexto de Vulkan en llama.cpp.

Equivalencia de tamaños, de acá en adelante: **S ≈ 1–2 sesiones · M ≈ 3–5 · L ≈ 6–10**.

- **M1 (M, 9 issues: #8–#14, #24 ✅, #31):** se mantiene en **M**, unas 3–4 sesiones. A
  diferencia de M0 es código de producto con golden tests, y #11–#13 (18 ops) son lo más
  largo. Ya está hecho el armado del paquete (falta la CI de #8), hay un borrador del esquema
  (`engine/spikes/llm/edit_plan.py`) y pyvips está elegido con su rendimiento medido.
### Cierre de M1 (2026-11-17)
M1 cerró en **2 sesiones** (estimado: 3–4), con 9 PRs (#33–#41). Los dos últimos issues, la
caché (#31) y la página de comparación, los hicieron subagentes en paralelo.
- **Qué quedó:** las 18 ops del catálogo, `pstudio apply` con 6 presets y modo lote,
  `pstudio analyze` y la caché de preview. Son 421 tests; las golden images son de 16 bits.
- **Rendimiento:**
  - El export de 24 MP con 10 ops tarda 2.7 s (objetivo < 3 s).
  - El lote web de 8 fotos de 24–48 MP tarda 14.4 s.
  - La preview de casi todas las ops queda bajo 150 ms. La de **denoise no** (≈ 280 ms).
  - Al mover el slider de la última op de una cadena, la respuesta queda bajo 30 ms solo si
    esa op es barata. Va como #42, en M3: es un tema de la app.
- **Aprendizaje:** revisar cada op sobre fotos reales encontró 6 fallas que los tests de
  propiedades no veían. Entre ellas: gray world invirtiendo colores, auto_exposure griseando
  una foto de producto, una raya roja del denoise y vibrance sin efecto. Mantener esa revisión
  visual para M2 (planes) y M3 (UI).

### Cierre de M2 (2026-11-17)
M2 cerró en **~1 sesión** (estimado: 3–5), con 8 PRs (#44–#52). Tres de ellos los hicieron
subagentes: dos sets de casos y el proveedor LLM local.
- **Qué quedó:**
  - `pstudio plan` → `pstudio apply` de punta a punta, más `pstudio eval` y
    `pstudio compare` (informe HTML antes/después).
  - Proveedores `rules` (offline), `local_llm` (llama-server + Qwen3-8B) y `cloud` (opt-in,
    solo texto).
  - 151 casos de eval.
- **Medido:**
  - Reglas: ~90% correcto **a ciegas** (90.1% y 90.0%, con dos sets escritos por agentes que no
    vieron el código), ~1.5 ms.
  - LLM local: 99.3% válido y 88.1% correcto (87.5% a ciegas), mediana 3.5 s, 5.3 GiB de VRAM.
- **Decisión:** `auto` usa las reglas; el LLM queda opt-in y el híbrido se mide en #53.
- **Sin probar:** el proveedor nube contra la API real (no hay credencial en este equipo).
- **Aprendizaje:** medir solo con sets ciegos de otro agente y anotar el número antes de
  corregir. Los sets "vistos" llegan al 100% y no dicen nada.
- **Uso:** con 3 agentes en paralelo se llegó al límite de uso dos veces. Máximo 2 a la vez.

- **M2 (M):** sube de riesgo. El spike #5 mostró ~75% de planes correctos con el LLM solo, así
  que el proveedor de reglas (#15) y los evals (#16) pesan más de lo previsto. Se mantiene en
  M, pero con #15 como camino crítico.
- **M3 (L):** la estimación pasa de 6–10 a **~11–14 sesiones** (diseño de M3 §11). La
  diferencia es el engine de proyecto (#55) y de jobs (#60), que no estaban contados. La firma
  del instalador (#23) depende de terceros (certificado o SignPath) y puede fijar la fecha de
  v0.1.

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

## M0 — Fundaciones (detalle) — ✅ cerrado 2026-11-16
- [x] Instalar Rust, FFmpeg (build LGPL), uv + Python 3.12. (#1)
- [x] Spike: pyvips vs OpenCV vs Pillow — tiempo de preview/export en 24 MP. (#2 → ADR-0005: pyvips)
- [x] Spike: sidecar Python dentro de Tauri — tamaño y arranque. (#3 → ADR-0006: Python embebible; instalador 23.7 MB, arranque < 1 s)
- [x] Spike: FFmpeg AMF (h264_amf/hevc_amf) en la RX 6600 XT. (#4: ~10× tiempo real, calidad ≈ OpenH264; sin AV1 por hardware)
- [x] Spike: llama.cpp Vulkan + JSON Schema con modelo 7–8B Q4 — latencia y validez. (#5 → ADR-0007: Qwen3-8B, 100% planes válidos con gramática, ~75% correctos, 4 s de mediana)
- [x] Aprobar ADR-0001…0006. (aceptados 2026-11-16)
- [x] Fixtures de prueba con licencia libre (fotos 24 MP, contraluz, interior cálido, ruido).

## Fuera de roadmap hasta nuevo aviso
Ver "Fuera de alcance" en `PRODUCT_SPEC.md`.
