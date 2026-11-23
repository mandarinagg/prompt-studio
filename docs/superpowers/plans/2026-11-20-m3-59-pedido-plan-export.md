# #59 Pedido, panel de plan y export simple — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En el editor, escribir un pedido ("más luz"), ver el plan como borrador aplicado en la preview, ajustarlo (casillas, valores), aplicarlo o descartarlo, y exportar la foto actual con un preset.

**Architecture:** El engine sigue siendo la única fuente de la fusión pila ⊕ plan: un método nuevo `plan.draft` la recalcula cuando el usuario cambia casillas o valores (no se porta `merge` a TS). El export simple es un método síncrono `asset.export` sobre `project.export.export_assets` (la cola de jobs es #60). En la app, el borrador vive en el store del editor y se renderiza con el mismo loop "gana el último".

**Tech Stack:** Python 3.14 + Pydantic (engine `pstudio.rpc`), React 19 + TS + zustand vanilla + Radix (app), vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-19-m3-app-escritorio-design.md` §5 (fusión), §6 (RPC), §7 (Pedido, Plan, Exportar, Atajos, Accesibilidad), §8 (plan por reglas → borrador < 150 ms).

## Global Constraints
- CLAUDE.md: el LLM nunca produce código; solo EditPlan del catálogo. Nunca escribir sobre originales (el export pasa todas las fotos del proyecto como `protected`; test de hash). Ningún medio sale del equipo: `plan.create` por RPC sigue sin `cloud`.
- No agregar dependencias (ni npm ni Python). "Abrir carpeta" queda para la cola (#61): acá se muestra la ruta del archivo exportado.
- Contrato: Pydantic → `uv run pstudio schema --rpc --out schema/rpc-1.schema.json` → `pnpm gen:types`. Nada se tipa a mano en dos lados.
- UI en español, palabras simples; código en inglés. Estados nunca solo por color; foco siempre visible; todo con teclado.
- No tocar la app mientras corre `pnpm tauri dev` (lo corre el usuario al final).
- Un commit por tarea; mensajes en español como los del repo; terminan con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. Un plan con **solo** `unsupported` o solo `clarification` (sin operations): no debe mostrarse "Aplicar" activo ni borrador vacío que parezca un cambio.
2. El usuario mueve un slider, hace undo o cambia de foto (←/→) con un borrador abierto: el borrador se descarta al cambiar de foto; con slider/undo se recalcula sobre la pila nueva (`plan.draft`) para que lo que se ve sea siempre pila ⊕ plan.
3. Respuesta vieja de `plan.create` (el usuario mandó otro pedido o descartó mientras "Pensando…"): se ignora (contador de generación, como el loop de preview).
4. Valor editado fuera de rango o vacío en una fila del plan: se recorta al rango del slider equivalente; vacío vuelve al valor del plan.
5. Export a un nombre ocupado: nunca sobrescribe (`_2`), y el original queda con el mismo hash; export con la foto faltante da un error legible, no una excepción.

---

### Task 1: Engine — `plan.draft` y `asset.export`

**Files:**
- Modify: `engine/src/pstudio/rpc/methods_media.py` (plan.draft), `engine/src/pstudio/rpc/methods_project.py` (asset.export)
- Regenerate: `engine/schema/rpc-1.schema.json`, `app/src/engine/contract.gen.ts`
- Test: `engine/tests/test_rpc_*.py` (seguir el archivo de tests RPC existente que cubre `plan.create` / `asset.apply_plan`)
- Doc: donde el repo documente la lista de métodos RPC (buscar `asset.apply_plan` en `docs/`), agregar los dos.

**Interfaces (produce):**
- `plan.draft` params `{asset: str, plan: EditPlan}` → `{draft: EditPlan, export_hint: Resize | None}`. Usa `merge(asset.stack, plan)`; no escribe nada.
- `asset.export` params `{asset: str, preset: ExportPreset = "web", out_dir: str | None = None}` → `{path: str, out_dir: str, ms: float}`. `out_dir` por defecto: `<carpeta que contiene el .pstudio>/Exportadas`. Error de `export_assets` (`Result.error`) → `RpcError(ENGINE_ERROR, error)`.

- [ ] Tests primero: draft suma sobre la pila (exposure 0.3 en pila + plan 0.4 → 0.7) sin modificar la pila guardada; draft con resize devuelve `export_hint`; export crea el archivo en `Exportadas/`, segundo export da `_2`, hash del original igual; export con archivo faltante → error RPC con "falta el archivo"; contrato incluye ambos métodos. Verlos fallar.
- [ ] Implementar. Ruling permitido: export síncrono bloquea el bucle RPC mientras dura (segundos en 45 MP); se acepta para #59 y se anota para #60.
- [ ] Regenerar esquema y tipos; `uv run pytest`, `uv run ruff check . && uv run ruff format --check .`, `pnpm typecheck` en app. Commit.

### Task 2: App — estado del borrador en el store del editor

**Files:**
- Create: `app/src/state/draft.ts` (lógica pura) + `app/src/state/draft.test.ts`
- Modify: `app/src/state/editor.ts`, `app/src/state/editor.test.ts`

**Interfaces:**
- Consumes: `plan.create`, `plan.draft`, `asset.apply_plan` (Task 1 / existentes), `createPreviewLoop`, `requestAfter` del editor.
- Produces (store del editor):
  - estado `plan: PlanState | null` con `{prompt, status: "thinking"|"ready"|"error", result?: PlanCreated, rows: PlanRow[], draft: EditPlan | null, error?: string}`; `PlanRow = {index, op: Operation, included: boolean, edited?: number}`.
  - acciones `ask(prompt: string)`, `answer(text: string)` (re-pide con `${prompt} ${text}`), `toggleRow(index)`, `editRow(index, value)`, `applyPlan()`, `discardPlan()`.
  - `effectivePlan(state): EditPlan` en `draft.ts`: el plan con solo las filas incluidas y los valores editados (campo principal de la op: `ev`, `amount`, `temperature_shift`/`tint_shift`, `strength`, `degrees`).
- Reglas:
  - Mientras hay `plan.draft`, lo que se renderiza como "after" es `draft` (no `stack`). Al descartar/aplicar vuelve a `stack`.
  - `ask` usa contador de generación; respuestas viejas se ignoran. `discardPlan` durante "thinking" cancela (ignora la respuesta).
  - `toggleRow`/`editRow` y cualquier cambio de `stack` (commit, undo, redo, resetAll) con un plan abierto → `plan.draft` sobre la pila actual (también "gana el último").
  - `open` de otra foto o `close` → descarta el plan.
  - `applyPlan` → `asset.apply_plan` con `effectivePlan` y `label: "Pedido: <prompt>"`, actualiza `saved`/`stack`, limpia `plan`. Plan sin operations incluidas → no-op.
- [ ] Tests primero (vitest, api falsa como en `editor.test.ts`): effectivePlan filtra y edita; ask muestra borrador y pide preview del draft; respuesta vieja ignorada; toggle recalcula vía `plan.draft`; apply llama `asset.apply_plan` y deja de mostrar draft; cambiar de foto descarta; undo con plan abierto recalcula draft. Verlos fallar, implementar, verde. Commit.

### Task 3: App — caja de pedido y panel del plan

**Files:**
- Create: `app/src/editor/PromptBox.tsx`, `app/src/editor/PlanPanel.tsx`
- Modify: `app/src/editor/EditorScreen.tsx` (panel derecho: pedido arriba, plan, después `AdjustPanel`; atajos Ctrl+K y `/` enfocan el pedido), `app/src/editor/Viewer.tsx` (chip "Vista previa del plan — sin aplicar" mientras hay borrador), `app/src/styles/editor.css`

- Pedido: `<textarea>` con label "¿Qué querés hacer?"; Enter envía, Shift+Enter salto de línea; vacío muestra ejemplos clicables: "Más luz", "Colores más vivos", "Enderezar", "Recorte cuadrado para Instagram", "Más nítida", "Foto más cálida". Esc en el campo lo desenfoca (no cierra el editor; ya lo cubre `isTyping`).
- "Pensando…" (solo si tarda > 150 ms, para no parpadear con reglas) con botón "Cancelar".
- Plan: `explanation` si hay; una fila por op con casilla (label = nombre del ajuste, reusar `ADJUSTMENTS`/`adjustmentLabel`), el cambio editable (`<input type="number">` con paso del ajuste) y al lado en gris "→ resultado" leído del `draft` (`getValue(draft, adj)`). Ops sin slider (crop, rotate, auto_*) muestran texto fijo sin campo ("Recorte 1:1", "Luz automática").
- `unsupported`: fila ámbar con ícono y texto "No disponible: <request>. <reason>. <alternative>" (no solo color).
- `clarification`: la pregunta en lugar del plan + campo de respuesta (Enter → `answer`).
- `errors` / `warnings` del resultado: texto debajo.
- Botones "Aplicar" (primario, deshabilitado sin filas incluidas) y "Descartar".
- [ ] Sin tests de componentes (el repo no los tiene); la lógica está en Task 2. `pnpm typecheck` y `pnpm test` verdes. Commit.

### Task 4: App — export de la foto actual

**Files:**
- Create: `app/src/editor/ExportDialog.tsx`
- Modify: `EditorScreen.tsx` (botón "Exportar…" en la topbar y Ctrl+E), `editor.css`

- Diálogo (Radix Dialog de `ui/Dialog.tsx`): tarjetas de presets con textos del §7: Web — liviana para subir (`web`, preseleccionado), Cuadrada 1080 — catálogo (`catalog_square`), Vertical 4:5 (`social_vertical`), Historia 9:16 (`story_9x16`), Original (`original`), Máxima calidad (`high_quality`). Si el plan aplicado dejó `export_hint`, mencionarlo ("El pedido sugiere achicar a … px") sin cambiar el preset.
- Texto: "Se guarda una copia en la carpeta Exportadas, junto al proyecto. La foto original no se toca."
- "Exportar" → `asset.export`; mientras tanto "Exportando…" y el botón deshabilitado; al terminar toast "Exportada: <nombre>" (ruta completa en el diálogo, seleccionable) y se cierra. Error → mensaje en el diálogo.
- Si el plan está abierto sin aplicar, el diálogo avisa "El plan sin aplicar no se incluye".
- [ ] `pnpm typecheck`, `pnpm test`, engine `uv run pytest` verdes. Commit.

### Cierre
- Revisión de toda la rama (superpowers:requesting-code-review) con este Review Focus; arreglar Critical/Important con test primero.
- No abrir PR ni pushear: lo hace el controlador después de la prueba real del usuario (hito: recorrido completo con fotos reales).
