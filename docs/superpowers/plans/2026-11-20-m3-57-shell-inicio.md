# #57 Shell, sistema de diseño y pantalla de inicio — plan

> Ejecución inline (superpowers:executing-plans), revisión final de toda la rama.

**Objetivo:** reemplazar el banco de pruebas de `App.tsx` por la app real: tokens de diseño,
componentes base accesibles, store, pantalla de inicio (nuevo, abrir, recientes, arrastrar
fotos para crear un proyecto) y una pantalla de proyecto mínima que #61 convierte en biblioteca.

**Spec:** `docs/superpowers/specs/2026-11-19-m3-app-escritorio-design.md` §7 (Inicio,
principios, accesibilidad), §8 (arranque < 3 s), §9 (tecnología).

## Restricciones globales
- CLI-first: los recientes viven en el engine (`pstudio project recent`), la UI los consume.
- Deps nuevas (livianas, §9): `zustand`, `@radix-ui/react-{dialog,tooltip,tabs,slider}`,
  `@tauri-apps/plugin-dialog` + crate `tauri-plugin-dialog` (selector nativo de carpetas),
  `vitest` (dev). Ninguna otra.
- Sin fuentes descargadas: tipografía del sistema (Segoe UI Variable).
- Textos de UI en español simple; nunca se mencionan issues ni jerga.
- Los tests del engine nunca escriben en el `%APPDATA%` real (`PSTUDIO_CONFIG_DIR`).

## Review focus
1. `recent.json` dañado o ilegible → lista vacía, la app arranca igual.
2. Un reciente que ya no existe → se ve como "no encontrado", se puede quitar, abrirlo da un
   mensaje claro y no rompe la pantalla.
3. Fallar al escribir recientes nunca hace fallar abrir/crear un proyecto.
4. Arrastrar una carpeta de fotos con un `.pstudio` adentro no importa la caché del proyecto.
5. Motor relanzado con un proyecto abierto → la app lo reabre sola; motor caído del todo → aviso
   persistente, sin pantallas rotas.

## Tareas
### 1. Engine: recientes, `project.close`, import sin `.pstudio`
- `pstudio/recent.py`: `config_dir()` (env `PSTUDIO_CONFIG_DIR`, si no `%APPDATA%/PROMPT
  STUDIO`, si no `~/.config/prompt-studio`), `touch(path, name)`, `list_recent() ->
  list[RecentProject{path,name,opened_at,exists}]` (máx. 10, sin duplicados por ruta
  normalizada), `forget(path)`. Escritura atómica; archivo dañado = lista vacía.
- RPC: `recent.list` → `RecentList{items}`, `recent.forget{path}` → `RecentList`,
  `project.close` → `null`. `project.open/create` registran el reciente (errores de disco se
  ignoran).
- CLI: `pstudio project recent [--json]`.
- `store._expand`: con `recursive`, se saltean carpetas `*.pstudio`.
- Tests: `test_recent.py` (orden, tope, dedupe, dañado, forget, exists), RPC
  (open registra, close, fallo de escritura no rompe), import recursivo con proyecto adentro.
  `conftest.py` autouse aísla `PSTUDIO_CONFIG_DIR`. Contrato y `contract.gen.ts` regenerados.

### 2. App: base (tokens, componentes, store) y tests
- `src/styles/tokens.css` + `base.css`: grises neutros, un acento, escala tipográfica y de
  espacios, foco visible, `prefers-reduced-motion`.
- `src/ui/`: `Button`, `IconButton`, `Dialog`, `Tooltip`, `Tabs`, `Slider` (etiqueta, valor
  editable, doble clic restablece, Shift = paso grande), `Icon` (SVG inline), `Toasts`.
- `src/lib/paths.ts`: `baseName`, `parentDir`, `isProjectPath`, `suggestProjectName`,
  `classifyDrop(paths) → {kind:"open",path} | {kind:"create",photos,name}`.
- `src/state/app.ts`: `createAppStore(api)` (zustand) con `engine`, `project`, `recents`,
  `toasts`, `newProject` (borrador del diálogo); acciones `boot`, `openProject`,
  `createProject`, `closeProject`, `forgetRecent`, `onRestarted`, `onFailed`, `notify`.
- vitest: `paths.test.ts`, `app.test.ts` con un `api` falso.

### 3. App: pantallas y shell
- `StartScreen` (acciones, recientes, zona de arrastre), `NewProjectDialog` (nombre, ubicación
  con "Cambiar…", ruta final visible), `ProjectScreen` (barra superior + lista de fotos
  provisoria), `EngineBanner`. Atajos: Ctrl+N, Ctrl+O.
- Banco de #56 → `src/dev/bench.ts` (solo con `PSTUDIO_BENCH_*`).
- Ventana 1280×800 (mín. 960×640), plugin dialog + permiso `dialog:allow-open`.
- CI: `pnpm test` en el job `types`.
- Verificación real: `pnpm tauri dev` contra el engine del venv, capturas de inicio, diálogo,
  proyecto creado arrastrando fotos de `tests/fixtures`, reciente faltante, relanzamiento.
