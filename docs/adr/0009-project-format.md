# ADR-0009 — Formato de proyecto, pila de ajustes e historial

- **Estado:** Propuesto
- **Fecha:** 2026-11-19
- **Issue:** #55
- **Diseño:** `docs/superpowers/specs/2026-11-19-m3-app-escritorio-design.md` §5

## Contexto
v0.1 exige proyectos guardables y reabribles, undo/redo y lotes (`PRODUCT_SPEC.md` §8). El
engine solo sabía aplicar un `EditPlan` a un archivo. Faltaba decidir:
- dónde viven las fotos y sus ajustes;
- cómo se combina un plan del prompt con lo que la foto ya tiene;
- cómo se guarda el historial.

`ARCHITECTURE.md` mencionaba `project.json` + SQLite.

## Decisión
- **Carpeta `<Nombre>.pstudio/`** con `project.json` (`schema_version` "1.0", modelos Pydantic
  en `pstudio/schema/project.py`) y `cache/`, que se puede borrar sin perder nada.
- **Guardado atómico y automático:** se escribe `project.json.tmp` y después `os.replace`. Si
  algo falla, el archivo anterior queda intacto. No hay botón Guardar.
- **Fotos por referencia:** ruta absoluta + tamaño + SHA-256. Se detectan duplicados por hash.
  Una foto movida se vuelve a ubicar solo si el hash coincide.
- **Pila de ajustes:** un `EditPlan` por foto, con como mucho una op por tipo y en **orden
  canónico fijo** (`pstudio.project.stack.CANONICAL_ORDER`, ver `EDIT_OPERATIONS.md`). Cada
  slider es un único valor y el resultado no depende del orden en que se tocaron los ajustes.
- **Fusión de planes:**
  - Los campos relativos (`ev`, `amount`, `temperature_shift`, `tint_shift`, `strength` de
    denoise) se **suman** y se recortan al rango del esquema.
  - La geometría y las ops `auto_*` **reemplazan**.
  - `resize` no entra a la pila: vuelve como sugerencia de export.
  - Las ops auto quedan como op en la pila: se resuelven en cada render y en cada foto, y el
    slider manual suma encima.
- **Historial por foto, por snapshots:**
  - Cada entrada guarda la pila completa (pocos KB), una etiqueta y un `group_id` opcional.
  - Undo/redo mueve un cursor. Un cambio nuevo descarta lo que se podía rehacer.
  - Máximo 200 entradas por foto; la entrada 0 ("Original") no se poda.
  - Un lote usa el mismo `group_id` en todas las fotos y se deshace junto donde sigue siendo
    el último cambio.
- **Sin SQLite en v0.1:** el JSON y la caché en disco por hash alcanzan para los proyectos
  previstos (decenas a cientos de fotos).

## Alternativas consideradas
- **SQLite como almacenamiento principal:** hace falta recién con búsqueda y catálogos
  grandes. Agrega migraciones y un formato no legible a mano. Queda para cuando haga falta un
  índice.
- **Historial global del proyecto:** un Ctrl+Z que deshace un cambio en otra foto que no se
  está viendo confunde. Los lotes se cubren con `group_id`.
- **Pila en orden libre (el orden en que se agregaron las ops):** el mismo conjunto de
  ajustes daría resultados distintos según el historial, y un slider no correspondería a un
  único valor.
- **Historial por diferencias en lugar de snapshots:** ahorra poco (las pilas son chicas) y
  complica deshacer y saltar.

## Consecuencias
- El orden canónico queda fijo en el formato. Cambiarlo altera cómo se ven los proyectos
  existentes y obliga a una nueva `schema_version`.
- Mover un slider temprano en el orden recalcula toda la cadena de la preview. Lo cubre el
  presupuesto de arrastre a menor resolución del diseño de M3 (§8) y #42.
- `project.json` crece con el historial: 200 entradas × ~1 KB × N fotos. Con 500 fotos son
  ~100 MB en el peor caso. Si se vuelve un problema, se poda más o se pasa a SQLite.
- Un solo proceso escribe el proyecto (la app a través del engine). No hay bloqueo entre
  procesos.
