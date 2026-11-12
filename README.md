# PROMPT STUDIO

**Editor local de fotos y videos controlado por prompts.**
Escribís *"mejorá la luz, corregí el balance de blancos y hacé una versión cuadrada para
catálogo"*, el sistema genera un **plan de edición estructurado**, lo revisás, ajustás
cualquier parámetro, ves el antes/después y exportás. Sin tocar tus originales.

> **La IA propone; el motor validado ejecuta.**
> El modelo nunca genera código: solo operaciones de un catálogo cerrado, validadas y reversibles.

**Estado:** 🟡 Fase de planificación (Milestone M0). Todavía no hay código ejecutable.

## Por qué es distinto
- **Local-first:** tus fotos y videos no salen de tu equipo. La nube es opt-in y solo recibe texto.
- **No destructivo:** el proyecto es una lista de operaciones; undo/redo e historial completos.
- **Funciona sin IA:** un intérprete de reglas offline cubre prompts simples; los LLM (locales o en la nube) son opcionales.
- **Reproducible:** el mismo plan sobre la misma imagen da el mismo resultado. Aplicable en lote.
- **Honesto con el hardware:** detecta CPU/GPU reales; no asume CUDA.

## Roadmap
| Release | Contenido |
|---|---|
| v0.1 | Foto + prompt: ajustes, crop, resize, plan revisable, preview, historial, export, lote |
| v0.2 | Video básico: timeline, cortes, unión, texto, audio, render |
| v0.3 | Prompts de video |
| v0.4 | IA local: fondo, upscaling, subtítulos |

Detalle en [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Stack propuesto
Tauri 2 + React + TypeScript · Engine Python 3.12 (`pstudio`, CLI + sidecar) · Pydantic ·
pyvips/OpenCV · FFmpeg · OpenTimelineIO · llama.cpp (Vulkan) opcional.
Ver [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) y [`docs/adr/`](docs/adr/).

## Documentación
- [Especificación de producto](docs/PRODUCT_SPEC.md) · [Análisis de PM](docs/PM_ANALYSIS.md)
- [Motor de prompts](docs/PROMPT_ENGINE.md) · [Catálogo de operaciones](docs/EDIT_OPERATIONS.md)
- [Hardware](docs/HARDWARE_COMPATIBILITY.md) · [Privacidad y seguridad](docs/PRIVACY_AND_SECURITY.md)
- [Pruebas](docs/TESTING.md) · [Instalación](docs/INSTALLATION.md) · [Limitaciones](docs/KNOWN_LIMITATIONS.md)

## Contribuir
Issues y milestones en GitHub. Un issue = una rama = un PR. Ver [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licencia
MIT — ver [`LICENSE`](LICENSE).
