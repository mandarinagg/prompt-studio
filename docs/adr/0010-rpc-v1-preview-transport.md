# ADR-0010 — RPC v1 y transporte de la preview

- **Estado:** Propuesto
- **Fecha:** 2026-11-19
- **Issue:** #56
- **Diseño:** `docs/superpowers/specs/2026-11-19-m3-app-escritorio-design.md` §6 y §8

## Contexto
La app necesita abrir proyectos, editar la pila, pedir planes y ver previews y miniaturas por
el canal stdio del spike #3. Ese canal solo tenía `ping`, `engine.version` e `image.info`.

El diseño pide cuatro cosas:
- tipos TS generados desde Pydantic;
- eventos del engine reenviados como eventos de Tauri;
- relanzar el engine si se cae;
- la preview escrita en `cache/` y mostrada por el protocolo de assets. Si el transporte pasa
  de 15 ms, se prueba base64 por stdio.

## Decisión
- **Métodos tipados:**
  - Cada método se registra con un modelo Pydantic de params (con `extra="forbid"`) y un tipo
    de resultado.
  - El registro genera `engine/schema/rpc-1.schema.json`
    (`pstudio schema --rpc`).
  - De ese archivo sale `app/src/engine/contract.gen.ts` (`pnpm gen:types`, con
    `json-schema-to-typescript`).
  - Hay un test en el engine y otro en el CI de la app que fallan si alguno de los dos queda
    desactualizado.
- **Métodos de v1:**
  - `project.create|open|info|import|relink`.
  - `asset.state|history|set_stack|apply_plan|undo|redo|jump|reset|undo_group`.
  - `job.export|cancel|list` (#60, ADR-0011): export de una foto o un lote en la cola de
    trabajos, a `Exportadas/` junto al proyecto (o a `out_dir`), nunca sobrescribe. Reemplaza
    al `asset.export` síncrono de #59, que bloqueaba el bucle RPC mientras duraba.
  - `plan.create`, con los proveedores `auto|rules|local_llm`. `cloud` queda afuera hasta que
    exista el consentimiento (#64).
  - `plan.draft` (#59): recalcula el borrador pila ⊕ plan cuando el usuario cambia casillas,
    valores o la pila. No guarda nada.
  - `preview.render` y `thumbnail.get`.
  - Además, `ping`, `engine.version` e `image.info`.
- **Eventos:** son notificaciones JSON-RPC sin `id`: `thumbnail.ready` y
  `job.progress|done|failed` (#60):
  - todas las escrituras a stdout pasan por un lock, porque las miniaturas y los jobs corren en
    otros hilos;
  - Rust las reenvía como el evento Tauri `engine-event {method, params}`.
- **Engine caído:**
  - Las llamadas en curso fallan enseguida con "el motor se reinició", sin esperar al timeout.
  - Rust relanza el engine como mucho 3 veces por minuto y emite `engine-restarted`. Si se
    pasa del límite, emite `engine-failed`.
  - La UI reabre el proyecto. No se pierde nada, porque el proyecto se guarda solo.
- **Cambios desde la terminal:**
  - Antes de guardar, la sesión compara `project.json` con lo que cargó (mtime + tamaño).
  - Si otro programa lo cambió, recarga el proyecto, devuelve el error `-32002` y no escribe
    encima.
- **Transporte de la preview:**
  - El engine escribe un JPEG Q85 en `cache/preview/`. Solo queda la última preview de cada
    foto.
  - Rust la lee con `read_cache`, que solo acepta archivos dentro de la caché del proyecto
    abierto (resuelve `..` y enlaces antes de comparar).
  - Rust la manda como bytes por IPC binario y la UI la muestra con un blob URL.
  - **No se habilita el protocolo de assets ni se manda base64 por stdio.**
- **Descriptores para `plan.create`:**
  - Se miden sobre el proxy de preview que ya está en memoria y se cachean por foto.
  - No se hashea ni se decodifica el original en cada pedido.

## Mediciones
Las mediciones se hicieron el 2026-11-19, con Ryzen 5 3600, WebView2 y `pnpm tauri dev`,
sobre fotos de `tests/fixtures/photos` (24–53 MP). Son medianas de 11 renders.

**Engine por stdio real:**

| | 1024 px (arrastre) | 2048 px |
|---|---|---|
| Op temprana, recalcula toda la cadena (render + encode) | 64–69 + 6 ms; 71–76 ms de punta a punta | 119–170 + 15 ms; 137–186 ms |
| Op al final de la cadena | 23 + 6 ms; 30 ms | 37–46 + 15 ms; 54–62 ms |
| base64 del JPEG en Python | 0.2–0.4 ms (+33% de tamaño) | 0.6–1.5 ms |
| Primer render (crea el proxy) | 235–865 ms | 555–1303 ms |

**En la app, desde que llega la respuesta hasta que la imagen está decodificada:**

| | 1024 px | 2048 px |
|---|---|---|
| Protocolo de assets | 9.9–11.2 ms | 14.1–17.7 ms |
| IPC binario + blob, medido después del protocolo de assets | 4.9–6.4 ms | 9.6–13.7 ms |
| IPC binario + blob, medido solo, después de un relanzamiento | 12.0 ms | 20.3 ms |

La primera comparación medía el IPC siempre en segundo lugar y la segunda corrida no lo
confirmó. **No está demostrado que un transporte sea más rápido que el otro:** los dos están
en 10–20 ms. El costo grande está en el engine: el render y el encode JPEG, que tarda 15 ms a
2048 px.

**`plan.create` con la foto abierta:** 63 ms el primer pedido y 1–2 ms los siguientes. Antes
costaba 150–620 ms por pedido. Los descriptores del proxy dan los mismos planes por reglas que
los del original: 56 de 56 (8 fotos × 7 pedidos). Los números difieren en centésimas.

Hubo una corrida que tardó 15 s y no se pudo repetir: el camino viejo dio 0.25–0.30 s en
todas las corridas posteriores. Fue probablemente un arranque en frío (primer import, o el
antivirus revisando la foto de 36 MB). No se le atribuye a ningún cambio.

**Relanzamiento:** se mató el árbol de procesos del engine durante el banco. La UI recibió
`engine-restarted` a los 2.8 s y reabrió el proyecto en 0.5 s, con la foto intacta.

## Alternativas consideradas
- **Protocolo de assets limitado a `cache/`:**
  - Es lo que proponía el diseño y rinde lo mismo.
  - Pero agrega un protocolo de archivos al WebView, con su scope (feature
    `protocol-asset`).
  - Con `read_cache` la regla "solo la caché del proyecto abierto" queda en una función de
    Rust con test, y el WebView no puede pedir rutas por su cuenta.
- **Base64 por stdio:**
  - Ahorra escribir el archivo, pero suma un 33% de tamaño y dos parseos JSON de 0.2–0.6 MB
    (en Rust y en el WebView).
  - Su costo mínimo ya es el del IPC binario, que no mejoró al protocolo de assets. No se
    adopta.
- **Tipos TS escritos a mano:** rompen la regla "nada se tipa dos veces" y se desincronizan
  sin que nada avise.

## Consecuencias
- El presupuesto de arrastre (< 100 ms a ≈1024 px) se cumple con margen. La preview refinada
  a 2048 px, con una op temprana, tarda 140–190 ms; la mejora es #42. (Después de #42, en el
  bench del engine: 52 ms a 1024 y 141 ms a 2048 con la cadena entera; ver MEDIA_PIPELINE.md.)
- Para bajar el transporte conviene atacar el encode y la resolución: renderizar al tamaño
  real del visor, que en un monitor de 1080p es menor a 2048 px, o un JPEG más liviano
  mientras se arrastra. Cambiar el canal no ayuda.
- Los blob URL se liberan del lado de la UI (`URL.revokeObjectURL`), que es responsabilidad
  del store de #58.
- Un método nuevo implica: modelo Pydantic, `pstudio schema --rpc` y `pnpm gen:types`. El CI
  falla si falta alguno de los dos.
- `json-schema-to-typescript` es una dependencia nueva, solo de desarrollo.
