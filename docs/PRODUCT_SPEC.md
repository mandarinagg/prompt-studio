# PROMPT STUDIO — Especificación de producto (v1)

> Editor local de fotos y videos controlado mediante prompts.
> v1 refina el documento original (`docs/archive/03_PROMPT_STUDIO_v0.md`); los cambios
> y su justificación están en `docs/PM_ANALYSIS.md`.

**Tipo:** aplicación de escritorio + motor multimedia local (Windows primero)
**Interfaz:** prompts, controles visuales, timeline
**Procesamiento:** local-first

## 1. Visión
Importar fotos y videos, describir cambios en lenguaje natural, convertirlos en operaciones
de edición **declarativas, reproducibles y reversibles**, previsualizar, ajustar, comparar
versiones y exportar. La IA propone; el motor validado ejecuta.

No es un wrapper de FFmpeg: combina edición visual, automatización, interpretación de
prompts, previsualización, parámetros editables, historial y exportación de calidad.

## 2. Usuarios
- **Primario:** creador / vendedor que edita fotos de producto y contenido para redes:
  catálogo, formatos cuadrado/vertical, lotes, correcciones rápidas sin saber de edición.
- **Secundario:** editor con experiencia que quiere velocidad (prompt) + control fino (sliders).

### Casos de uso priorizados (v0.1)
1. "Mejorá la luz y el balance de blancos de esta foto de producto" → revisar → exportar.
2. "Hacé una versión cuadrada 1080×1080 para Instagram y otra 4:5" → dos exports.
3. Aplicar el mismo plan a 50 fotos (lote).
4. Ajustar a mano un parámetro que el prompt propuso y volver atrás.

## 3. Principios (no negociables)
1. Local-first. Ningún medio sale del equipo sin consentimiento explícito por operación.
2. Nunca sobrescribir originales (se verifica hash).
3. Edición no destructiva: el proyecto es una lista de operaciones sobre referencias.
4. Previsualizar antes de exportar; una preview nunca se presenta como export final.
5. El prompt se convierte en un **plan estructurado validado**, nunca en código.
6. Todo parámetro es inspeccionable y editable.
7. Informar qué se usa: CPU/GPU, modelo, local o nube.
8. Todas las funciones clásicas funcionan sin IA.
9. No prometer funciones no probadas en el hardware objetivo.
10. Proyectos reabribles y portables.

## 4. Experiencia de usuario
Espacio de trabajo: biblioteca, visor, propiedades, prompt, historial, antes/después,
cola de render, exportación. Timeline y capas en las fases correspondientes.

### Flujo de prompt
1. Analizar archivo (descriptores locales: histograma, exposición, clipping, WB estimado, EXIF).
2. Interpretar prompt + descriptores → plan estructurado.
3. Validar contra el catálogo; marcar operaciones no soportadas.
4. Si hay ambigüedad relevante, pedir aclaración (máximo una pregunta concreta).
5. Mostrar plan: operaciones, valores, explicación en lenguaje natural.
6. Preview (proxy) con antes/después.
7. El usuario ajusta, acepta o descarta operaciones individuales.
8. Aplicar al proyecto (entrada de historial).
9. Exportar copia con un perfil.

Si una operación requiere un modelo no instalado: informar, ofrecer alternativa clásica.

## 5. Plan de edición estructurado
Ver `docs/PROMPT_ENGINE.md` y `docs/EDIT_OPERATIONS.md`. Claves:
- Esquema versionado (`schema_version`), tipado y validado (fuente única: modelos Pydantic →
  JSON Schema → tipos TypeScript).
- Valores **relativos** (`+0.5 EV`) o **automáticos** (`auto_white_balance`) resueltos por el motor.
- Incluye `explanation`, `unsupported[]` y `clarification` opcional.

## 6. Módulos
- **6.1 Biblioteca:** importar imagen/video/audio, metadatos, búsqueda, detección de faltantes,
  referencias sin duplicar.
- **6.2 Fotografía (v0.1):** exposición, contraste, altas luces/sombras, blancos/negros,
  temperatura/matiz relativos, saturación, vibrancia, crop por aspecto, rotación/enderezado,
  resize, nitidez, denoise, viñeta, auto-exposición, auto-WB, export por lotes.
  *Luego:* curvas, máscaras locales, perspectiva, RAW.
  *IA opcional (v0.4+):* fondo, selección de sujeto, inpainting, upscaling.
- **6.3 Video (v0.2):** importar clips, cortar, unir, reordenar, aspecto/escala, color básico,
  transiciones simples, títulos, subtítulos importados (SRT), volumen/fades, extraer audio, render.
  *Avanzado (v0.4+):* STT local, detección de escenas, reencuadre, estabilización.
- **6.4 Motor de prompts:** ver `docs/PROMPT_ENGINE.md`.
- **6.5 Preview:** proxies, caché por operación, cancelación, actualización al mover sliders.
- **6.6 Timeline/capas:** modelo OpenTimelineIO para video; pila de ajustes para foto.
- **6.7 Exportación:** perfiles en `docs/EXPORT_PRESETS.md`, siempre como copia.

Cada modelo IA declara licencia, tamaño, VRAM/RAM, tiempo estimado y local/nube (`docs/AI_MODELS.md`).

## 7. Requisitos no funcionales (objetivos a validar en M0)
| Métrica | Objetivo |
|---|---|
| Preview de 1 ajuste, imagen 24 MP (proxy 2048 px) | < 150 ms |
| Export 24 MP con 10 operaciones (CPU) | < 3 s |
| Plan por reglas / LLM local | < 50 ms / < 8 s |
| Arranque de la app | < 3 s |
| Diferencia preview vs export reducido | SSIM > 0.99 |
| Originales modificados | 0 (hash verificado) |

## 8. Criterios de aceptación
### v0.1 "Foto + Prompt"
- Funciona offline (reglas) para edición clásica.
- Importa JPG, PNG, TIFF, WebP.
- No modifica originales.
- Ajustes del catálogo v1 con sliders y por prompt.
- Prompts → plan validado; el usuario revisa antes de aplicar.
- Operaciones no soportadas se identifican y explican.
- Preview, progreso y cancelación de export.
- Undo/redo; proyectos guardables y reabribles.
- Lote: mismo plan a N fotos.
- No ejecuta código arbitrario; no envía medios a la nube.
- Tests (unitarios, golden images, evals de prompts) y documentación.

### v0.2 "Video básico"
- Secuencia simple: cortar, unir, texto, audio, render H.264 (AMF) / VP9.
- Proxies de video y cancelación de render.

## 9. Fuera de alcance (por ahora)
Proyecto mixto foto+video, colaboración, plugins de terceros, móvil, macOS/Linux
(el diseño no lo impide), generación de imágenes, edición multi-cámara.

## 10. Documentación mantenida
`README.md`, `CLAUDE.md` y `docs/`: PRODUCT_SPEC, PM_ANALYSIS, ARCHITECTURE, MEDIA_PIPELINE,
PROMPT_ENGINE, EDIT_OPERATIONS, VIDEO_TIMELINE, AI_MODELS, HARDWARE_COMPATIBILITY,
PRIVACY_AND_SECURITY, EXPORT_PRESETS, ROADMAP, TESTING, INSTALLATION, KNOWN_LIMITATIONS, adr/.

**Regla final:** el prompt se traduce a una edición controlable, verificable y reversible.
