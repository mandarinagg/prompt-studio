# #55 Proyecto, pila de ajustes e historial (engine) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar al engine el proyecto `.pstudio` (assets por referencia, guardado atómico), la
pila de ajustes por foto (una op por tipo, orden canónico, fusión de planes), el historial con
undo/redo y lotes, y el CLI `pstudio project …`. Es la base del RPC (#56) y de la app.

**Architecture:** Nuevo subpaquete `pstudio.project`. Los modelos Pydantic (fuente única del
formato) van en `pstudio/schema/project.py`. La lógica pura (pila, historial) no toca disco;
`store.py` es lo único que lee y escribe `project.json`. El export reutiliza
`pstudio.export.apply_file`.

**Tech Stack:** Python 3.14, Pydantic v2, pyvips, pytest, argparse (CLI existente en
`pstudio/__init__.py`).

**Spec:** `docs/superpowers/specs/2026-11-19-m3-app-escritorio-design.md` (§5). Issue #55.

## Global Constraints
- Rama `feat/55-proyecto-engine`; PR que diga `Closes #55`.
- Nunca escribir sobre originales: todo export pasa `protected=` con las rutas de **todos** los
  assets del proyecto, y los tests verifican el SHA-256 de los originales.
- Identificadores en inglés; mensajes al usuario y docs en español.
- Sin dependencias nuevas.
- `uv run pytest`, `uv run ruff check .` y `uv run ruff format --check .` en verde antes de
  cada commit.
- Formato del proyecto: carpeta `<Nombre>.pstudio/` con `project.json` (`schema_version`
  `"1.0"`) y `cache/`. Guardado: escribir `project.json.tmp` y `os.replace`.
- Importa solo `.jpg .jpeg .png .tif .tiff .webp` (sin importar mayúsculas).
- Historial: 200 entradas como máximo por foto; la entrada 0 ("Original", pila vacía) nunca se
  poda.

## Review Focus
1. **Fusión que se pasa del rango** ("más luz" con la exposición en +4.8): se recorta al límite
   del esquema, sin error de validación. → Task 2, `test_merge_clamps_to_schema_bounds`.
2. **`project.json` corrupto o de otra versión:** error claro en español, no una traza ni un
   proyecto vacío que pise el archivo. → Task 4, `test_open_rejects_corrupt_and_future_versions`.
3. **Importar la misma foto dos veces** (o la misma por dos rutas): se omite y se informa, no
   se duplica. → Task 4, `test_add_skips_duplicates_by_hash`.
4. **Exportar a una carpeta con un archivo del mismo nombre, o a la carpeta de los
   originales:** sufijo `_2`, `_3`…; nunca sobrescribe y los originales mantienen su hash. →
   Task 5, `test_export_never_overwrites_and_keeps_originals`.
5. **Undo de un lote cuando una foto cambió después:** deshace solo las que no cambiaron y
   devuelve cuáles se saltearon. → Task 3, `test_undo_group_skips_assets_changed_later`.

---

### Task 1: Modelos del proyecto

**Files:**
- Create: `engine/src/pstudio/schema/project.py`
- Modify: `engine/src/pstudio/schema/__init__.py` (exportar los modelos nuevos)
- Test: `engine/tests/test_project_model.py`

**Interfaces:**
- Produces (todos `extra="forbid"`, **no** frozen, salvo `HistoryEntry`, que es frozen):
  - `PROJECT_SCHEMA_VERSION = "1.0"`
  - `HistoryEntry(label: str (max 200), stack: EditPlan, group_id: str | None = None, at: datetime)`
  - `Asset(id: str, path: str, size: int, sha256: str (64 hex), imported_at: datetime, history: list[HistoryEntry], cursor: int = 0)`
    - property `stack -> EditPlan` = `history[cursor].stack`
    - `Asset.new(id, path, size, sha256) -> Asset`: historial con una sola entrada
      `HistoryEntry(label="Original", stack=EditPlan())`.
  - `Project(schema_version: Literal["1.0"], name: str, created_at: datetime, assets: list[Asset], export_dir: str | None = None)`
    - `Project.asset(asset_id: str) -> Asset`: lanza `KeyError` con el mensaje
      `"no existe la foto {id}"`.
  - `project_json_schema() -> dict` (como `json_schema()` del plan).

- [ ] **Step 1: Tests**
  - `test_new_asset_starts_with_original_entry`: `Asset.new(...)` → `len(history) == 1`,
    `history[0].label == "Original"`, `stack.operations == []`, `cursor == 0`.
  - `test_project_roundtrip_json`: un `Project` con 1 asset y 2 entradas →
    `Project.model_validate_json(p.model_dump_json()) == p`.
  - `test_cursor_out_of_range_is_invalid`: `cursor=5` con 1 entrada → `ValidationError`
    (validador del modelo: `0 <= cursor < len(history)`).
  - `test_unknown_field_rejected`: un campo extra → `ValidationError`.
- [ ] **Step 2:** `uv run pytest tests/test_project_model.py -v` → FAIL (import).
- [ ] **Step 3:** Implementar los modelos.
- [ ] **Step 4:** Los mismos tests → PASS.
- [ ] **Step 5:** Commit `feat(project): modelos Project/Asset/HistoryEntry (#55)`.

### Task 2: Pila de ajustes (orden canónico y fusión)

**Files:**
- Create: `engine/src/pstudio/project/__init__.py`, `engine/src/pstudio/project/stack.py`
- Test: `engine/tests/test_project_stack.py`

**Interfaces:**
- Produces:
  - `CANONICAL_ORDER: tuple[str, ...] = ("straighten", "rotate", "crop", "denoise", "auto_white_balance", "white_balance", "auto_exposure", "exposure", "contrast", "highlights", "shadows", "whites", "blacks", "saturation", "vibrance", "sharpen", "vignette")`.
    Todos los `OP_NAMES` menos `resize`.
  - `normalize(stack: EditPlan) -> EditPlan`: una op por tipo (si hay repetidas, gana la
    última), en `CANONICAL_ORDER`, sin ops `is_noop()` ni `resize`. Solo conserva
    `operations`; los demás campos quedan en su valor por defecto.
  - `merge(stack: EditPlan, plan: EditPlan) -> MergeResult`
  - `@dataclass(frozen=True) MergeResult(stack: EditPlan, export_hint: Resize | None)`
  - `ADDITIVE: dict[str, frozenset[str]]`: los campos que se suman.
    - `exposure: {ev}`
    - `contrast`, `highlights`, `shadows`, `whites`, `blacks`, `saturation`, `vibrance`:
      `{amount}`
    - `white_balance: {temperature_shift, tint_shift}`
    - `vignette: {amount}`; `sharpen: {amount}`; `denoise: {strength}`

    El resto de los campos, y las ops `auto_*`, `crop`, `rotate` y `straighten`, reemplazan.

- [ ] **Step 1: Tests**
  - `test_normalize_orders_and_dedupes`: `[vibrance 20, exposure 0.3, exposure 0.5, crop 1:1]`
    → `ops == ["crop", "exposure", "vibrance"]` y `exposure.ev == 0.5`.
  - `test_normalize_drops_noops_and_resize`.
  - `test_merge_adds_relative_values`: pila `exposure 0.3` + plan `exposure 0.4` → `ev ≈ 0.7`.
  - `test_merge_clamps_to_schema_bounds`: `ev 4.8 + 0.4 → 5.0`; `saturation 90 + 30 → 100`;
    `denoise 0.9 + 0.3 → 1.0`; `vignette -20 + 20` → `0`, que es no-op y se elimina. Los límites salen del `ge`/`le` del
    campo en el modelo Pydantic, no de constantes copiadas.
  - `test_merge_replaces_geometry_and_auto`: `crop 1:1` + `crop 4:5` → `4:5`;
    `auto_exposure 0.5` + `auto_exposure 1.0` → `1.0`.
  - `test_merge_moves_resize_to_export_hint`: un plan con `resize 1080` → no está en la pila y
    `export_hint.width == 1080`.
  - `test_merge_keeps_auto_and_manual_together`: `auto_exposure` + `exposure 0.2` → ambas en
    la pila, `auto_exposure` antes.
  - Para cada op de `CANONICAL_ORDER`, `normalize` de una pila con esa op en valores no
    neutros la conserva. Es un test parametrizado y cubre que la tupla no tenga typos.
- [ ] **Step 2:** `uv run pytest tests/test_project_stack.py -v` → FAIL.
- [ ] **Step 3:** Implementar. Fusión: para cada op del plan, si la pila ya tiene ese tipo y
  existe la entrada en `ADDITIVE`, se suman esos campos y se recortan a sus límites; el resto
  de los campos se toma del plan. Sin ese tipo en la pila, la op del plan entra tal cual.
  Después `normalize`.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(project): pila de ajustes con orden canónico y fusión (#55)`.

### Task 3: Historial (undo/redo, saltos, lotes)

**Files:**
- Create: `engine/src/pstudio/project/history.py`
- Test: `engine/tests/test_project_history.py`

**Interfaces:**
- Consumes: `Asset`, `HistoryEntry`, `Project` (Task 1); `normalize` (Task 2).
- Produces (mutan el `Asset` o `Project` recibido):
  - `MAX_ENTRIES = 200`
  - `push(asset: Asset, stack: EditPlan, label: str, group_id: str | None = None) -> bool`.
    Normaliza; si queda igual a `asset.stack`, devuelve `False` y no hace nada. Si no, corta
    las entradas posteriores al cursor, agrega, mueve el cursor y poda: si
    `len > MAX_ENTRIES`, borra la entrada 1 (nunca la 0) y ajusta el cursor.
  - `undo(asset) -> bool`, `redo(asset) -> bool`: `False` en los extremos.
  - `jump(asset, index: int) -> None`: `IndexError` si está fuera de rango.
  - `undo_group(project: Project, group_id: str) -> UndoGroupResult`
  - `@dataclass UndoGroupResult(undone: list[str], skipped: list[str])` con los ids de las
    fotos. Se deshace solo en las fotos cuya entrada **actual** tiene ese `group_id`; las
    que tienen esa entrada más atrás van a `skipped`.

- [ ] **Step 1: Tests**
  - `test_push_undo_redo_cycle`: push A, push B; undo → A; undo → Original; `undo` → False;
    redo → A.
  - `test_push_after_undo_discards_redo_branch`.
  - `test_push_identical_stack_is_noop`: devuelve `False` y el historial no cambia.
  - `test_history_is_capped_keeping_original`: 250 pushes → `len == 200`,
    `history[0].label == "Original"` y el cursor apunta a la última.
  - `test_jump_moves_cursor_without_truncating`.
  - `test_undo_group_reverts_all_assets`: 3 fotos con el push del grupo `g1` →
    `undone == [a, b, c]` y todas vuelven a su pila anterior.
  - `test_undo_group_skips_assets_changed_later`: en la foto b, un push posterior a `g1` →
    `undone == [a, c]`, `skipped == [b]` y la pila de b no cambia.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(project): historial con undo/redo y deshacer lote (#55)`.

### Task 4: Almacenamiento (crear, abrir, guardar, importar, faltantes, reubicar)

**Files:**
- Create: `engine/src/pstudio/project/store.py`
- Test: `engine/tests/test_project_store.py` (fotos sintéticas con `imaging.synthetic_rgb` +
  `to_vips(...).write_to_file(tmp_path / "x.jpg")`)

**Interfaces:**
- Consumes: modelos (Task 1); `pstudio.render.sha256_file`.
- Produces:
  - `class ProjectError(Exception)`: mensaje en español para el usuario.
  - `PROJECT_SUFFIX = ".pstudio"`, `PROJECT_FILE = "project.json"`, `CACHE_DIR = "cache"`
  - `IMPORTABLE = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"})`
  - `create(parent: Path, name: str) -> Path`: crea `parent/<name>.pstudio/` con `cache/` y
    un `project.json` vacío. `ProjectError` si el nombre está vacío, tiene más de 100
    caracteres, contiene `<>:"/\|?*` o caracteres de control, o si la carpeta ya existe.
  - `open_project(path: Path) -> Project`: acepta la carpeta `.pstudio` o su
    `project.json`. `ProjectError` si falta, es JSON inválido o tiene otra `schema_version`.
    En ningún caso escribe.
  - `save(path: Path, project: Project) -> None`: escritura atómica (tmp + `os.replace`),
    UTF-8, con indentación.
  - `add_assets(project: Project, paths: list[Path], *, recursive: bool = False) -> AddResult`
  - `@dataclass AddResult(added: list[str], duplicates: list[Path], unsupported: list[Path])`.
    Las rutas se guardan absolutas y resueltas. Los duplicados se detectan por SHA-256 contra
    el proyecto y dentro del mismo lote. Las carpetas aportan sus archivos importables en
    orden alfabético. Ids: `uuid4().hex[:12]`.
  - `missing(project: Project) -> list[str]`: ids cuyo archivo no existe.
  - `relink(project: Project, asset_id: str, new_path: Path) -> None`: `ProjectError`
    (`"el archivo no es la misma foto"`) si el hash no coincide; si coincide, actualiza la
    ruta.

- [ ] **Step 1: Tests**
  - `test_create_makes_folder_and_rejects_bad_names` (parametrizado: `""`, `"a/b"`,
    `"x:y"`, 101 caracteres, y que la carpeta ya exista).
  - `test_save_open_roundtrip` y `test_save_is_atomic`: con `os.replace` parcheado para que
    falle, el `project.json` anterior queda intacto.
  - `test_open_rejects_corrupt_and_future_versions`: JSON truncado → `ProjectError`;
    `schema_version "9.0"` → `ProjectError`; el archivo no se modifica (mismo hash).
  - `test_add_skips_duplicates_by_hash`: la misma foto por dos rutas (copia) → 1 agregada y
    1 en `duplicates`; un `.txt` va a `unsupported`.
  - `test_add_does_not_touch_originals`: SHA-256 antes y después iguales.
  - `test_missing_and_relink`: se borra el archivo → aparece en `missing`; `relink` a una
    copia idéntica funciona y a otra foto lanza `ProjectError`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(project): crear/abrir/guardar atómico, importar y reubicar (#55)`.

### Task 5: Exportar fotos del proyecto

**Files:**
- Create: `engine/src/pstudio/project/export.py`
- Test: `engine/tests/test_project_export.py`

**Interfaces:**
- Consumes: `Project`, `missing` (Task 4); `pstudio.export.apply_file`, `EXTENSIONS`,
  `resolve`; `pstudio.schema.Export`.
- Produces:
  - `export_assets(project: Project, asset_ids: list[str], out_dir: Path, preset: ExportPreset = "original") -> list[Result]`
    (`Result` de `pstudio.export`). Para cada foto: `apply_file(asset.stack, source,
    dest, cli=Export(preset=preset), protected=<rutas de todos los assets>)`. El destino es
    `out_dir/<nombre sin extensión>_<preset>`; si el archivo final ya existe, se agrega `_2`,
    `_3`… hasta encontrar uno libre (se calcula con la extensión que resuelve el preset). Una
    foto faltante o un error de decodificación queda como `Result(error=...)` en español y
    el resto del lote sigue. Crea `out_dir` si no existe.

- [ ] **Step 1: Tests**
  - `test_export_applies_stack`: la pila con `exposure +1` hace la salida más clara que la
    fuente (luminancia media mayor).
  - `test_export_never_overwrites_and_keeps_originals`: dos exports seguidos a la misma
    carpeta → `_original.jpg` y `_original_2.jpg`; exportar con `out_dir` = la carpeta de los
    originales no pisa nada; SHA-256 de los originales sin cambios.
  - `test_export_missing_asset_reports_error_and_continues`: 2 fotos, 1 faltante → 1 con
    `dest` y 1 con `error`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(project): exportar fotos del proyecto como copias (#55)`.

### Task 6: CLI `pstudio project`, ADR-0009 y documentación

**Files:**
- Create: `engine/src/pstudio/project/cli.py` (los `_cmd_*` y `add_parser(sub)`)
- Modify: `engine/src/pstudio/__init__.py`: registrar `project` con
  `project.cli.add_parser(sub)`.
- Create: `docs/adr/0009-project-format.md` (plantilla `0000-template.md`)
- Modify: `docs/EDIT_OPERATIONS.md` (sección "Orden canónico de la pila" con
  `CANONICAL_ORDER` y las reglas de fusión), `docs/ARCHITECTURE.md` (project/: JSON sin
  SQLite en v0.1; remite a ADR-0009).
- Test: `engine/tests/test_project_cli.py` (vía `pstudio.main([...])` y `capsys`)

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: los subcomandos de `pstudio project` (`PROJ` = carpeta `.pstudio`). Salida
  legible por defecto y `--json` en `list` y `show`. Códigos: 0 si salió bien, 1 si la
  entrada es inválida (plan inválido, no hay nada que deshacer), 2 si es un error de
  archivo o del proyecto (`ProjectError`).

  | Subcomando | Qué hace |
  |---|---|
  | `new DIR NAME` | imprime la ruta creada |
  | `add PROJ PATHS… [--recursive]` | resumen agregadas/duplicadas/no soportadas |
  | `list PROJ [--json]` | id, nombre de archivo, `editada`/`falta` |
  | `show PROJ ASSET [--json]` | pila (JSON) + historial con `▶` en el cursor |
  | `edit PROJ ASSET --plan FILE [--replace] [--label TXT]` | fusiona (o reemplaza con `--replace`) y hace push; la etiqueta por defecto es `"Pedido: {source_prompt}"` o `"Plan aplicado"`; si hubo `export_hint`, lo avisa |
  | `undo PROJ ASSET` / `redo PROJ ASSET` | |
  | `relink PROJ ASSET PATH` | |
  | `export PROJ [ASSETS…] -o DIR [--preset P]` | sin ASSETS exporta todas; imprime cada destino o error |

  Cada comando que modifica algo hace `save` al final.

- [ ] **Step 1: Tests**: un flujo de punta a punta con fotos sintéticas: `new` → `add` (2) →
  `edit` con un plan `exposure 0.5` → `show --json` (ev 0.5) → `undo` → `show` (pila vacía)
  → `redo` → `export -o out --preset web` (archivos `.webp` creados, originales con el mismo
  hash). También `undo` sin historial → código 1, y `list` de una carpeta inexistente →
  código 2 con el mensaje en stderr.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar el CLI. **Step 4:** PASS, y además la suite
  completa: `uv run pytest` (559+ tests), `uv run ruff check .`, `uv run ruff format --check .`.
- [ ] **Step 5:** Escribir ADR-0009: la decisión (JSON atómico, sin SQLite en v0.1, pila
  canónica, fusión aditiva, historial por foto con snapshots, `group_id`), las alternativas
  (SQLite, historial global, pila en orden libre) y las consecuencias. Actualizar
  `EDIT_OPERATIONS.md` y `ARCHITECTURE.md`.
- [ ] **Step 6:** Prueba con material real: crear un proyecto en `%TEMP%` con 3 fotos de
  `tests/fixtures/photos`, aplicar un plan de `pstudio plan "más luz y colores vivos" foto`,
  undo/redo y exportar `web`. Mirar las salidas y anotar los tiempos en el PR.
- [ ] **Step 7:** Commit `feat(project): CLI pstudio project + ADR-0009 (#55)` y abrir el PR
  `Closes #55`.
