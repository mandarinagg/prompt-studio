# Análisis de Project Management — PROMPT STUDIO

> Revisión del documento original (`docs/archive/03_PROMPT_STUDIO_v0.md`) — 2026-11-12.
> Resultado: `docs/PRODUCT_SPEC.md` (v1), `docs/ROADMAP.md`, ADRs en `docs/adr/`.

## 1. Veredicto

La visión es sólida y los **principios son el mejor activo del documento**: local-first,
no destructivo, "la IA propone, el motor validado ejecuta", catálogo cerrado de operaciones.
Eso es exactamente lo que diferencia este producto de un "chat que llama a FFmpeg".

El problema es de **alcance y de definición de la pieza central**. Tal como está, el
documento describe Lightroom + Premiere + un motor de IA, con un MVP que exige foto **y**
video **y** prompts. Para un desarrollador solo (con Claude Code) eso es un proyecto de
años sin un primer entregable usable. Hay que cortar el alcance y definir mejor el motor
de prompts, que es lo que hace único al producto.

## 2. Fortalezas (mantener)

| Fortaleza | Por qué importa |
|---|---|
| Plan declarativo validado, nunca código | Seguridad, reproducibilidad, testabilidad |
| Edición no destructiva + historial | Undo/redo y versiones salen casi gratis si el proyecto es "lista de operaciones" |
| Local-first, IA opcional | Funciona sin GPU/modelos; privacidad como feature |
| Roadmap por fases, video después de foto | Orden correcto de riesgo |
| Diagnóstico de hardware explícito | Evita prometer lo que el equipo no puede |

## 3. Problemas detectados y propuestas

### P1 — El MVP es demasiado grande
Los criterios de aceptación mezclan foto, video, prompts, timeline, cancelación, etc.
**Propuesta:** dividir en releases con valor propio:
- **v0.1 "Foto + Prompt"**: editor fotográfico + prompt → plan → revisión → preview → export.
- **v0.2 "Video básico"**: cortes, unión, texto, audio, render.
- **v0.3 "Prompts de video"**, **v0.4 "IA local"**.

### P2 — Falta un "walking skeleton" antes de la UI
**Propuesta: engine-first / CLI-first.** Primer hito = un CLI:
`pstudio apply plan.json foto.jpg -o out.jpg` y `pstudio plan "mejorá la luz" foto.jpg`.
Valida esquema, motor y prompts sin escribir UI, y le permite a Claude Code probar todo
desde la terminal. La UI se monta encima de un motor que ya funciona.

### P3 — El LLM no puede adivinar valores absolutos
El ejemplo `"temperature": 5200` implica que el LLM "ve" la foto. Si no la ve, inventa;
si la ve (modelo de visión), estás enviando el medio al modelo.
**Propuesta: separar intención de parámetros.**
1. Un **analizador local determinista** extrae descriptores (histograma, exposición media,
   % de clipping, WB estimado, dimensiones, EXIF).
2. El LLM recibe **prompt + descriptores en texto** y produce operaciones con valores
   **relativos** (`exposure: +0.5 EV`) o **automáticos** (`auto_white_balance`).
3. El motor resuelve los automáticos con algoritmos clásicos y muestra los valores finales.
Así el plan es reproducible, explicable y no requiere enviar la imagen a nadie.

### P4 — No se define el proveedor del LLM
Es la pieza central y no está decidida. **Propuesta (ADR-0003):** interfaz `PlanProvider`
con tres implementaciones, en este orden:
1. **Reglas** (offline, sin modelos): parser de palabras clave ES/EN → cubre el 60–70 % de
   prompts simples y es el fallback garantizado (principio 8).
2. **LLM local** vía llama.cpp/Ollama con backend **Vulkan** (funciona en la RX 6600 XT)
   y decodificación restringida por JSON Schema. Modelo ~7–8B cuantizado Q4 (~5 GB VRAM).
3. **LLM en la nube opt-in** (p. ej. Claude con salida estructurada/tool use). Solo se
   envía texto: prompt + descriptores. Nunca píxeles sin consentimiento explícito.

### P5 — Faltan requisitos no funcionales medibles
"Rápido" y "profesional" no se pueden testear. **Propuesta** (objetivos iniciales, a validar en Fase 0):
- Preview de un ajuste en imagen 24 MP (proxy 2048 px): **< 150 ms**.
- Export full-res de 24 MP con 10 operaciones: **< 3 s** en CPU.
- Plan desde prompt: reglas **< 50 ms**, LLM local **< 8 s**.
- Arranque de la app: **< 3 s**. Cero pérdidas: originales con hash verificado.

### P6 — Preview vs export: riesgo de que no coincidan
Si la preview se hace con shaders en la UI y el export con otro motor, los resultados
divergen. **Propuesta:** un solo motor (backend) renderiza tanto el proxy como el export,
con el mismo código. Test automático: export reducido ≈ preview (SSIM > 0.99).

### P7 — Calidad "profesional" sin gestión de color
No se mencionan profundidad de bits, ICC ni RAW. **Propuesta:** pipeline interno en float
32 lineal, entrada/salida con ICC (sRGB/Display P3), preservar EXIF opcionalmente.
RAW (LibRaw/rawpy) queda para v0.4 pero el pipeline se diseña para admitirlo.

### P8 — Timeline: no reinventar el modelo de datos
**Propuesta:** usar **OpenTimelineIO** (Apache-2.0, Academy Software Foundation) como
modelo de timeline e intercambio, renderizado con FFmpeg filtergraphs. Permite exportar
a/desde DaVinci/Premiere en el futuro. Evaluar MLT (GPL) solo si el render propio no escala.

### P9 — Licencias: FFmpeg puede "contagiar" GPL
**Propuesta:** distribuir un build **LGPL** de FFmpeg (sin x264/x265) y codificar H.264/HEVC
con **AMF** (encoder por hardware AMD) o OpenH264. Licencia del proyecto: MIT (ver ADR-0004).
Cada modelo IA declara licencia en `docs/AI_MODELS.md` antes de integrarse.

### P10 — El hardware real impone límites concretos
Ver `docs/HARDWARE_COMPATIBILITY.md`. Resumen: **sin CUDA**; ROCm en Windows es limitado;
usar **Vulkan** (llama.cpp, whisper.cpp, ncnn) y **ONNX Runtime DirectML**. RDNA2 **no
codifica AV1** por hardware. Solo **56 GB libres en C:** → modelos y caché en directorio
configurable (sugerido `F:`). Python 3.15 instalado es demasiado nuevo para wheels de ML →
fijar **Python 3.12** con `uv`.

### P11 — El motor de prompts necesita evaluación, no solo tests
**Propuesta:** `evals/prompts/` con casos `prompt + descriptores → plan esperado`
(ES y EN, ambiguos, imposibles, maliciosos). Métrica: % de planes válidos y correctos por
proveedor. Se corre en cada cambio del catálogo o del prompt de sistema.

### P12 — No hay proceso de trabajo
**Propuesta:** GitHub Issues + milestones por release, ADRs para decisiones, Definition of
Done (abajo), `CLAUDE.md` con las reglas para que cada sesión de Claude Code respete los
principios. Un issue = una rama = un PR.

### P13 — No hay usuario objetivo ni casos de uso priorizados
**Propuesta:** persona primaria = **creador/vendedor que edita fotos de producto y contenido
para redes** (catálogo, cuadrado/vertical, lotes). Es concreto, frecuente y encaja con el
ejemplo del propio documento. El colorista profesional es persona secundaria.

## 4. Definition of Done (para cada issue)
- [ ] Código + tests (unitarios y, si toca píxeles, golden image con tolerancia).
- [ ] Esquema/tipos actualizados si cambió el catálogo.
- [ ] Docs afectadas actualizadas (`EDIT_OPERATIONS.md`, etc.).
- [ ] Ningún original modificado; ningún medio de usuario commiteado.
- [ ] Probado en el hardware objetivo si toca GPU/rendimiento.

## 5. Principales riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Alcance infinito / nunca se publica | Alta | Alto | Releases chicos, v0.1 solo foto |
| Prompts mal interpretados | Alta | Alto | Plan siempre revisable, evals, aclaraciones |
| Preview lenta en Python | Media | Alto | Proxies, caché por operación, pyvips; spike en Fase 0 |
| Empaquetado Python + Tauri en Windows | Media | Medio | Spike temprano de sidecar (PyInstaller/Nuitka) |
| IA en AMD/Windows inestable | Alta | Medio | IA opcional, Vulkan/DirectML, fallback CPU |
| Licencias (FFmpeg/modelos) | Media | Alto | Build LGPL, registro de licencias |
| Espacio en disco | Media | Medio | Caché con límite y limpieza, ruta configurable |

## 6. Próximos pasos inmediatos
1. Aprobar/ajustar ADR-0001…0004 (stack, sidecar, proveedores LLM, licencia).
2. Instalar herramientas de Fase 0 (ver `docs/INSTALLATION.md`).
3. Ejecutar los spikes de Milestone M0 (issues en GitHub).
4. Empezar M1: motor CLI de foto.
