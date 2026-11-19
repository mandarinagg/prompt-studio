# Diseño M3 — App de escritorio (v0.1 "Foto + Prompt")

Fecha: 2026-11-19 · Estado: aprobado 2026-11-19 · Milestone: M3

## 1. Intención
Primera versión usable de PROMPT STUDIO. El usuario principal no sabe editar
(`PRODUCT_SPEC.md` §2): importa fotos, **pide en palabras** lo que quiere, revisa el plan, lo
afina con sliders si quiere, compara antes/después y exporta copias, de a una o en lote. El
usuario secundario (con experiencia) usa los mismos sliders para control fino.

El dueño del producto delegó el diseño de UI/UX ("diseñalo como experto"): **todas las
decisiones de interfaz de este documento son llamadas del diseñador** y pueden corregirse.

## 2. Objetivos, no-objetivos, anti-objetivos
**Objetivos (criterios de `PRODUCT_SPEC.md` §8, v0.1):** offline con reglas; importa JPG/PNG/
TIFF/WebP; nunca toca originales; las 18 ops con sliders y por prompt; el plan se revisa antes
de aplicar; las ops no soportadas se explican; preview, progreso y cancelación de export;
undo/redo; proyectos guardables y reabribles; lote (mismo plan a N fotos); sin código
arbitrario ni medios a la nube.

**No-objetivos v0.1:** video, máscaras/curvas/RAW, presets de usuario, tema claro, varias
ventanas, idiomas fuera del español, sincronización en la nube, catálogo global tipo Lightroom
(cada proyecto es independiente).

**Anti-objetivos (fracaso aunque "funcione"):**
- El prompt aplica cambios sin que el usuario vea y acepte el plan.
- Los sliders se sienten trabados (> 100 ms de respuesta percibida en ops baratas).
- Se pierde trabajo si la app o el engine se cierran de golpe.
- Hace falta saber jerga de edición para sacar una buena foto con el prompt.
- Cualquier escritura sobre un original o cualquier medio enviado fuera del equipo.

## 3. Restricciones
- CLAUDE.md: CLI-first (toda función existe primero en `pstudio` y se prueba desde
  terminal), catálogo cerrado, Pydantic → JSON Schema → TS, sin CUDA, sin dependencias
  pesadas sin aprobación, repo público.
- Stack fijado por ADR-0001/0002/0006: Tauri 2 + React 19 + TS + Vite; engine Python
  embebido por stdio JSON-RPC (sin puertos).
- Hardware objetivo: Ryzen 5 3600, RX 6600 XT, 16 GB.
- Estado actual: `app/` es el esqueleto del spike #3 (cliente Rust JSON-RPC de 121 líneas,
  `App.tsx` de 54). El RPC expone solo `ping`, `engine.version`, `image.info`. **No existen**
  `project/` ni `jobs/`; sí existen plan/apply/export/analyze/compare y la caché de preview por
  prefijo (`render/preview.py`, proxy 2048 px, 512 MB).

## 4. Enfoques considerados
| Enfoque | Qué cambia | Costo |
|---|---|---|
| **A. Recorrido vertical primero** *(elegido)* | Engine mínimo de proyecto + RPC, luego una foto de punta a punta (abrir → pedir → plan → sliders → preview → export); después biblioteca, lote, cola, ajustes | Algo usable en 2–3 sesiones; latencia y flujo se validan temprano |
| B. Por capas | Todo el engine, después todas las pantallas | Nada usable hasta el final; errores de API RPC se ven tarde |
| C. UI primero con engine simulado | Itera lo visual rápido | Viola CLI-first; integración rehecha |

Elegido A por el diseñador (el dueño delegó el "cómo"): reduce el riesgo principal de M3, que
es la latencia percibida y el flujo prompt → plan → aplicar, no la cantidad de pantallas.

## 5. Modelo de datos (engine)
### Proyecto
- Un proyecto es una carpeta `<Nombre>.pstudio/` con `project.json` (versionado,
  `schema_version`) y `cache/` (miniaturas, previews; borrable sin perder nada).
- `project.json` contiene: assets (id, ruta absoluta, tamaño, hash SHA-256, fecha de import),
  la **pila de ajustes** de cada asset y su historial.
- **Guardado automático** después de cada cambio (escritura atómica: archivo temporal +
  rename). No hay botón Guardar.
- Faltantes: si la ruta no existe, el asset queda marcado "falta"; "Ubicar…" permite elegir el
  archivo nuevo y se acepta solo si el hash coincide.
- SQLite (mencionado en ARCHITECTURE.md) **se posterga**: para v0.1 alcanzan el JSON y la
  caché en disco por hash. *Llamada del diseñador*; se registra en el ADR.

### Pila de ajustes = un `EditPlan` por asset
- Como mucho **una op de cada tipo**, en un **orden canónico fijo** que define el engine
  (no el orden en que se agregaron). Así cada slider corresponde a exactamente un valor y el
  resultado no depende del historial. El orden exacto lo fija el builder, documentado en
  `EDIT_OPERATIONS.md`.
- **Fusión de un plan del prompt sobre la pila:**
  - ops con `amount`/`ev`/`shift`: el valor del plan se **suma** al actual y se recorta al
    rango del esquema ("más luz" dos veces = más luz);
  - ops auto (`auto_exposure`, `auto_white_balance`): se agregan o reemplazan. **Quedan
    como op auto en la pila** y el engine las resuelve en cada render según la foto. No se
    convierten en valores fijos. El slider manual del mismo grupo (exposición, temperatura)
    **suma encima** del resultado auto. Por eso en lote cada foto recibe su propio ajuste;
  - geometría (`crop`, `rotate`, `straighten`): **reemplazan**;
  - `resize` no vive en la pila: es cosa del export (presets). Si un plan lo trae, pasa a ser
    sugerencia de export en el diálogo.
- Una op con valor neutro se quita de la pila.

### Historial
- **Por foto**, lineal, con undo/redo. Cada entrada guarda la pila completa resultante (son
  pocos KB de JSON) y una etiqueta legible: "Pedido: más luz y colores vivos", "Exposición
  +0.3 EV", "Ajustes pegados", "Restablecer".
- Mover un slider crea **una** entrada al soltar, no una por cada cuadro.
- Una acción en lote crea una entrada en el historial de cada foto afectada, todas con el
  mismo `group_id`. En la biblioteca, Ctrl+Z deshace ese grupo completo si sigue siendo lo
  último en cada foto. Si alguna foto cambió después, deshace solo las que no cambiaron y lo
  avisa.
- Límite: 200 entradas por foto (configurable en el builder).

### Jobs
- Cola local en el engine para trabajos largos: export, lote, miniaturas, análisis.
- Progreso y cancelación por job. Cancelar deja borrados los archivos parciales.
- El bucle RPC **nunca se bloquea** por un job: los jobs corren en un worker (hilo o proceso;
  lo decide el builder midiendo con pyvips) y la preview sigue respondiendo durante un export.

### CLI (antes que la UI)
`pstudio project new|add|list|show`, `pstudio project edit <asset> --plan plan.json`,
`pstudio project undo|redo <asset>`, `pstudio project export <assets…> --preset web`.
Cada uno con tests, incluido el hash de originales.

## 6. Contrato RPC
- Métodos agrupados: `project.*` (open, create, recent, import, relink, remove),
  `asset.*` (stack, set_stack, undo, redo, history, reset, copy/paste), `plan.create`
  (pedido + asset → plan validado, usando el proveedor configurado), `preview.render`,
  `thumbnail.get`, `analyze`, `job.*` (submit export/batch, cancel, list), `settings.*`.
- Eventos del engine como notificaciones JSON-RPC (sin `id`): `job.progress`, `job.done`,
  `job.failed`, `thumbnail.ready`. Rust los reenvía como eventos de Tauri.
- Tipos TS **generados** desde el JSON Schema de Pydantic (plan y payloads RPC). Nada se tipa
  a mano en dos lados.
- **Preview:** el engine escribe la preview en `cache/` y devuelve su ruta. La UI la muestra
  con el protocolo de assets de Tauri, con el alcance limitado a `cache/`. La resolución es la
  del visor, no siempre 2048 px. *Llamada del diseñador:* si la medición da > 15 ms de
  transporte, se prueba con bytes en base64 por stdio y se registra el resultado en el ADR.
- **"Gana el último":** durante un arrastre la UI tiene como mucho una preview en vuelo y una
  pendiente (la más reciente). Las intermedias se descartan, no se encolan.
- Engine caído: Rust lo relanza, la UI muestra "El motor se reinició" y reabre el proyecto.
  No se pierde nada gracias al guardado automático.

## 7. Experiencia de usuario
### Principios
1. **El pedido es la puerta de entrada.** El panel derecho arranca con el cuadro de pedido,
   no con los sliders.
2. **Nada se aplica sin verlo.** Un plan se muestra como **borrador** aplicado en la preview,
   con una etiqueta visible, y solo entra a la pila con "Aplicar".
3. **Todo es reversible.** Undo/redo, restablecer y nunca tocar originales.
4. **Interfaz neutra.** Grises oscuros neutros (no sesgan la percepción del color), acento
   único y sobrio, la foto es lo más saturado de la pantalla.
5. **Palabras simples.** "Luz", "Color", "Detalle", no "tone mapping".

### Pantallas
**Inicio** (sin proyecto abierto): "Nuevo proyecto", "Abrir…" y la lista de recientes.
Arrastrar fotos acá crea un proyecto nuevo con ellas.

**Biblioteca** (cuadrícula):
```
┌───────────────────────────────────────────────────────────────────────┐
│ PROMPT STUDIO · Verano 2026        [+ Importar]   [Exportar 3…]  ⚙    │
├───────────────────────────────────────────────────────────────────────┤
│  ▣ ▣ ▢ ▢ ▣ ▢     ● = editada   ⚠ = falta el archivo                   │
│  ▢ ▢ ▢ ▢ ▢ ▢     Clic: seleccionar · Doble clic / Enter: editar       │
├───────────────────────────────────────────────────────────────────────┤
│ 3 seleccionadas  ✦ [Pedido para las 3…]  [Pegar ajustes]  [Exportar]  │
└───────────────────────────────────────────────────────────────────────┘
```
- Importar con botón, arrastrando archivos o carpetas. Las fotos se referencian, no se copian.
- Miniaturas generadas en segundo plano (job), con un marcador mientras tanto.
- Con varias seleccionadas, la barra inferior ofrece pedido en lote, pegar ajustes y exportar.

**Editor** (una foto):
```
┌──────────────────────────────────────────────────────────┬───────────────────────┐
│ ◀ Biblioteca   foto_012.jpg      ↶ ↷   ◐ Antes/Después    │       [Exportar…]     │
├──────────────────────────────────────────────────────────┼───────────────────────┤
│                                                          │ ✦ ¿Qué querés hacer?  │
│                                                          │ ┌───────────────────┐ │
│                                                          │ │más luz, colores   │ │
│                    VISOR                                 │ │vivos              │ │
│         (ajustar a ventana · 100% · divisor A/D)         │ └───────────────────┘ │
│                                                          │ Plan propuesto        │
│      ┌ Vista previa del plan — sin aplicar ┐             │ ☑ Exposición  +0.4 EV │
│                                                          │ ☑ Vibrancia   +20     │
│                                                          │ ⚠ "quitar el fondo":  │
│                                                          │   no disponible aún   │
│                                                          │ [Aplicar]  Descartar  │
│                                                          │ ───────────────────── │
│                                                          │ Ajustes │ Historial   │
│                                                          │ ▾ Luz   ▸ Color       │
│                                                          │ ▸ Detalle ▸ Geometría │
├──────────────────────────────────────────────────────────┴───────────────────────┤
│ ▢ ▢ ▣ ▢ ▢ ▢ ▢ (tira de fotos)                                  Exportando 2/8 ▸   │
└──────────────────────────────────────────────────────────────────────────────────┘
```
- **Pedido:** Enter envía, Shift+Enter hace salto de línea. Vacío, muestra 4–6 ejemplos
  clicables escritos en lenguaje de usuario ("Más luz", "Colores más vivos", "Enderezar",
  "Recorte cuadrado para Instagram").
- **Plan:** cada op es una fila con casilla (incluir/excluir), valor editable y explicación
  breve. El número editable es **el cambio** que propone el plan (+0.4 EV); al lado, en gris,
  el resultado sobre la foto actual ("→ +0.7"). En lote se muestra solo el cambio. El borrador
  se dibuja como pila ⊕ plan. Al llegar el plan, la preview lo muestra enseguida como borrador. "Aplicar" lo fusiona
  en la pila (§5) y crea una entrada de historial; "Descartar" vuelve atrás.
  - `unsupported` → fila ámbar con el motivo y la alternativa, no bloquea el resto.
  - `clarification` → la pregunta aparece en lugar del plan, con un campo de respuesta. La
    respuesta se agrega al pedido y se vuelve a planificar.
  - Mientras planifica: con reglas es instantáneo; con IA local se ve "Pensando…" con un botón
    para cancelar.
- **Ajustes:** grupos plegables:
  - Luz: exposición, contraste, altas luces, sombras, blancos, negros, botón Auto.
  - Color: temperatura, matiz, saturación, vibrancia, botón Auto.
  - Detalle: nitidez, reducción de ruido.
  - Efectos: viñeta.
  - Geometría: recorte por proporción fija (1:1, 4:5, 9:16, 16:9, 3:2; "Sin recorte" lo
    quita) con un marco que se **arrastra para encuadrar** (sin manijas de tamaño). Rotar 90°
    y enderezar. El recorte libre con manijas queda fuera de v0.1.

  Cada slider tiene un valor numérico editable, doble clic para restablecerlo y flechas para
  ajuste fino (con Shift, pasos más grandes). Un punto marca los grupos modificados.
- **Antes/después:** mantener `\` o el botón ◐ muestra el original; clic en ◐ alterna la
  **vista dividida** con un divisor arrastrable. "Antes" es siempre el original. Si la pila
  tiene geometría (recorte, rotación, enderezado), la vista dividida no se ofrece porque los
  encuadres no coinciden; queda solo mantener para ver el original completo.
- **Historial:** pestaña con la lista de entradas; clic para volver a ese punto (no borra las
  posteriores hasta que se hace un cambio nuevo, como undo).
- **Visor:** ajustar a la ventana por defecto, 100% con doble clic o `Z`, y desplazar
  arrastrando. Si la preview tarda, se ve la anterior hasta que llega la nueva, sin parpadeo
  ni spinner sobre la foto.

**Exportar** (diálogo):
- Tarjetas con los presets de `EXPORT_PRESETS.md`, descritos para el usuario ("Web — liviana
  para subir", "Cuadrada 1080 — catálogo", "Vertical 4:5", "Historia 9:16", "Original",
  "Máxima calidad").
- Carpeta destino: por defecto `Exportadas/` junto al proyecto, recordada por proyecto.
- Nombre `{nombre}_{preset}.{ext}`; si ya existe, se agrega un sufijo. **Nunca se
  sobrescribe**.
- Al confirmar, crea un job y el diálogo se cierra. El progreso queda en la cola.

**Cola** (cajón inferior derecho): cada job con barra, foto actual, cancelar y "Abrir
carpeta" al terminar. Un aviso discreto cuando termina un lote.

**Lote:**
- "Pedido para N" planifica **una vez** sobre la foto activa o la primera seleccionada,
  muestra el plan y, al aplicar, lo fusiona en la pila de cada foto. Las ops auto se resuelven
  por foto en el engine.
- "Copiar/Pegar ajustes" copia la pila completa, sin la geometría salvo que se pida.

**Configuración (⚙):** "Cómo entiendo tus pedidos":
- **Reglas** (por defecto: rápido, sin conexión).
- **IA local** (más lenta, requiere el modelo instalado; si falta, se explica y no se ofrece
  descarga automática).
- **IA en la nube** (requiere un consentimiento explícito que dice "solo se envía el texto del
  pedido y datos numéricos de la foto, nunca la imagen"). La clave se guarda en el almacén de
  credenciales del sistema, nunca en el proyecto.

Lo que hace el modo híbrido (#53) depende de su medición: si gana, pasa a ser parte de "Reglas".

### Atajos
Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y, `\` antes/después, `Z` zoom, ←/→ foto anterior/siguiente,
Ctrl+E exportar, Ctrl+K o `/` foco en el pedido, Esc vuelve a la biblioteca o cierra el
diálogo, Ctrl+I importar.

### Accesibilidad
Todo se puede hacer con el teclado y el foco siempre se ve. El texto tiene contraste AA sobre
el fondo oscuro y los sliders tienen etiquetas y valores accesibles. Los estados nunca se
indican solo con color.

## 8. Presupuestos de rendimiento
| Qué | Objetivo |
|---|---|
| Slider → píxeles en pantalla (op barata, cadena de 10) | < 50 ms percibido; engine < 30 ms (#42) |
| Op cara (denoise) | Se acepta render progresivo (primero sin la op, después con ella) si #42 lo justifica |
| Mover un slider temprano en el orden (recalcula toda la cadena) | Mientras se arrastra, preview a resolución reducida (≈1024 px de lado largo) en < 100 ms; al soltar se refina a la resolución del visor |
| Plan por reglas → borrador visible | < 150 ms |
| Abrir foto en el editor | < 500 ms hasta la primera preview |
| Arranque de la app hasta la pantalla de inicio | < 3 s |
| Preview durante un export en curso | sigue cumpliendo el objetivo de slider |

## 9. Tecnología de la UI (llamadas del diseñador)
- CSS propio con tokens (variables CSS); sin framework de componentes pesado.
- Primitivas accesibles livianas (Radix: Slider, Dialog, Tooltip, Tabs) y un store chico
  (zustand). Ambas son livianas; se listan en el PR para aprobación según CLAUDE.md regla 5.
- Generación de tipos TS: `json-schema-to-typescript` (dependencia de desarrollo).

## 10. Pruebas
- Engine: pytest para el proyecto (fusión, orden canónico, historial, guardado atómico,
  faltantes/hash), jobs (progreso, cancelación, archivos parciales borrados), RPC (contrato por
  método) y hash de originales intacto en todo export.
- UI: vitest para la lógica del store (gana el último, fusión del borrador, undo).
- **Recorrido manual con fotos reales** al cerrar el recorrido vertical y antes del release,
  con capturas y revisión visual (lección de M1). Se reportan resultados reales, sin declarar
  "listo" antes.

## 11. Orden de trabajo (issues propuestos)
Tamaños: S ≈ ½ sesión, M ≈ 1, L ≈ 2.

**Recorrido vertical**
1. `engine`: proyecto + pila + historial + CLI `pstudio project …` — **M**. ADR-0009 (formato
   de proyecto e historial).
2. `engine/app`: RPC v1 (project/asset/plan/preview/thumbnail), notificaciones, puente Rust
   de eventos y tipos TS generados — **M**. ADR-0010 (transporte de preview).
3. `app`: shell, sistema de diseño (tokens, tipografía, componentes base), pantalla de inicio,
   abrir/crear proyecto — **M**.
4. `app`: editor con visor, antes/después, sliders, marco de recorte y preview en vivo "gana
   el último", con resolución reducida mientras se arrastra — **L**. **No espera a #42**:
   cierra con la preview de arrastre dentro del presupuesto (§8). #42 mejora la versión
   refinada.
5. `app`: pedido + panel de plan (borrador, unsupported, clarification, aplicar/descartar) y
   export simple de la foto actual — **M**. **Hito: recorrido completo con fotos reales.**

**Ampliar**
6. `engine`: jobs (cola, progreso, cancelación) y export/lote/miniaturas como jobs, con CLI —
   **M**.
7. `app`: biblioteca (importar, cuadrícula, miniaturas, faltantes/ubicar, tira de fotos) —
   **M**.
8. `app`: diálogo de export, cola, lote (pedido para N, copiar/pegar ajustes) — **M**.
9. `app`: panel de historial y atajos completos — **S**.
10. `app`: configuración de proveedores con consentimiento de nube — **S**.
11. `infra`: empaquetado v0.1. Engine embebido (ADR-0006) con pyvips/libvips y FFmpeg en el
    bundle de Tauri, instalador y arranque medido en la máquina objetivo — **S/M** (el spike
    #3 ya resolvió lo esencial).

**En paralelo**
- #42 preview < 30 ms: antes de cerrar el issue 4.
- #53 híbrido: independiente, en cualquier momento. Si gana, cambia `auto`.

**Cierre**
12. QA v0.1: checklist de §8 de PRODUCT_SPEC con material real, documentación de usuario y
    `KNOWN_LIMITATIONS` — **M**.
- #23 firma del instalador: puede fijar la fecha del release.

Total estimado: ~11–14 sesiones (el roadmap dice L ≈ 6–10). La diferencia es el engine de
proyecto y jobs, que no estaba contado. No se recorta alcance: v0.1 lo exige. Si hiciera falta
postergar algo, lo primero sería el issue 10, porque las reglas funcionan sin configurar nada.
El roadmap se actualiza con este número.

## 12. Lo que queda al builder
- Orden canónico exacto de las ops y su documentación.
- Hilo o proceso para los jobs (medir con pyvips y el GIL).
- Formato y calidad de la preview en caché (JPEG o PNG; resolución según el visor).
- Detalles visuales finos (tipografía, espaciados, iconos) dentro de los principios del §7.
- Límite y poda de la caché en disco.
