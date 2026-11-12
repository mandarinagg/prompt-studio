# Arquitectura (propuesta — ver ADRs en `docs/adr/`)

```
┌──────────────────────────── App de escritorio (Tauri 2) ─────────────────────────────┐
│  UI: React + TypeScript + Vite                                                       │
│  Biblioteca · Visor · Propiedades · Prompt · Plan · Historial · Timeline · Export    │
│                ▲  tipos TS generados desde JSON Schema                               │
└────────────────┼─────────────────────────────────────────────────────────────────────┘
                 │ JSON-RPC (stdio)  — sin red, sin puertos abiertos
┌────────────────▼──────────────── Engine (sidecar Python 3.12) ───────────────────────┐
│  schema/      Pydantic: Plan, Operation, Project  → JSON Schema (fuente única)       │
│  analyze/     descriptores deterministas (histograma, clipping, WB, EXIF)            │
│  prompt/      PlanProvider: reglas | LLM local | LLM nube (opt-in)  → validación     │
│  ops/         catálogo cerrado: cada op = función pura (img, params) → img           │
│  render/      pipeline float32 lineal, proxies, caché por hash de (asset, ops[:i])   │
│  video/       OpenTimelineIO → FFmpeg filtergraph                                    │
│  jobs/        cola local, progreso, cancelación                                      │
│  project/     project.json versionado + SQLite (índice/caché)                        │
└──────────────────────────────────────────────────────────────────────────────────────┘
        │                    │                         │
     FFmpeg (LGPL)     pyvips / OpenCV            llama.cpp / ONNX Runtime (opcional)
```

## Decisiones clave
- **El motor es independiente de la UI** y se usa también como CLI (`pstudio`). Toda
  funcionalidad existe primero en el CLI.
- **Un solo motor** renderiza preview y export (evita divergencias).
- **Caché incremental:** el resultado de aplicar `ops[0..i]` se cachea por hash; mover el
  slider de la op *i* solo recalcula desde *i*.
- **Catálogo cerrado:** el LLM no puede referenciar nada fuera del registro de operaciones.
- **Rutas:** el engine solo lee de medios importados y escribe en el directorio del
  proyecto/export; toda ruta se normaliza y valida (anti path traversal).

## Estructura del repo
```
app/        UI Tauri + React (M3)
engine/     paquete Python `pstudio` (M1)
tests/      tests del engine; fixtures/ con medios de licencia libre
evals/      casos de evaluación del motor de prompts
docs/       especificación, arquitectura, ADRs
```
