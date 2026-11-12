# CLAUDE.md — PROMPT STUDIO

Editor local de fotos/videos controlado por prompts. Leé `docs/PRODUCT_SPEC.md` y
`docs/ARCHITECTURE.md` antes de cambios grandes. Idioma de docs y UI: español; código e
identificadores: inglés.

## Reglas no negociables
1. **El LLM nunca produce código ejecutable.** Solo `EditPlan` con operaciones del catálogo
   (`docs/EDIT_OPERATIONS.md`). No agregues `eval`, `exec`, shell dinámico ni "ops genéricas".
2. **Nunca escribir sobre originales.** Todo export es una copia; tests verifican hashes.
3. **Ningún medio sale del equipo** sin opt-in explícito. El proveedor nube solo recibe texto.
4. **No asumir CUDA.** Hardware objetivo: Ryzen 5 3600, RX 6600 XT (Vulkan/DirectML/AMF), 16 GB.
5. **No descargar modelos grandes** ni instalar dependencias pesadas sin aprobación.
6. **Repo público:** nunca commitear medios personales, claves, `.env` ni rutas privadas.
7. No declarar algo "profesional" o "listo" sin probarlo con material real; reportá resultados reales.

## Forma de trabajo
- **CLI-first:** toda función existe primero en el engine (`engine/`, paquete `pstudio`) y se
  prueba desde terminal; la UI (`app/`) solo la consume.
- Esquema: Pydantic es la fuente única → JSON Schema → tipos TS. Cambiar el catálogo implica:
  modelo + implementación + golden test + regla del proveedor `rules` + eval + doc.
- Decisiones de arquitectura → nuevo ADR en `docs/adr/`.
- Un issue = una rama (`feat/<n>-slug`, `fix/<n>-slug`) = un PR que referencia el issue.
- Definition of Done: ver `docs/PM_ANALYSIS.md` §4.

## Comandos (a medida que existan)
- Engine: `cd engine && uv sync && uv run pytest`
- Lint: `uv run ruff check . && uv run ruff format --check .`
- App: `cd app && pnpm install && pnpm tauri dev`

## Estado
Milestone actual: **M0 — Fundaciones**. Ver issues abiertos con `gh issue list --milestone "M0 - Fundaciones"`.
