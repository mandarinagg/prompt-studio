# ADR-0011 — Trabajos largos en un hilo del engine

- **Estado:** Propuesto
- **Fecha:** 2026-11-23
- **Issue:** #60
- **Diseño:** `docs/superpowers/specs/2026-11-19-m3-app-escritorio-design.md` §5, §6 y §8
- **Plan:** `docs/superpowers/plans/2026-11-23-m3-60-jobs.md`

## Contexto
El export simple de #59 (`asset.export`) era síncrono: con una foto de 45 MP bloqueaba el bucle
RPC varios segundos, y mientras tanto la preview y la edición no respondían. El diseño pide
exportar una foto o un lote en segundo plano, con progreso, cancelación que no deje archivos a
medias y la preview dentro de su presupuesto (< 100 ms a ≈1024 px) durante el export.

Había que elegir dónde corre el trabajo: un hilo dentro del proceso del engine o un proceso
aparte (con prioridad normal, baja o en "modo segundo plano" de Windows).

## Decisión
- **Un solo hilo worker** (daemon) en `pstudio.jobs.JobQueue`, que arranca con el primer job y
  los atiende en orden (FIFO). libvips ya paraleliza adentro de cada export; más hilos solo
  competirían con la preview.
- **Copia al encolar:** cada job lleva una copia de las fotos y sus pilas tomada en
  `job.export`. El usuario puede seguir editando; el worker nunca lee ni escribe
  `Session.project`. Todas las fotos del proyecto viajan como `protected`: ningún destino puede
  pisar un original.
- **Cancelación cooperativa:** entre fotos con una bandera y, a mitad de una foto, con la señal
  `eval` de libvips (`image.set_kill(True)`), que hace fallar `write_to_file`. `encode` escribe
  a un temporal y lo borra, así que de la foto en curso no queda nada. Las terminadas se
  conservan y se informan.
- **RPC:**
  - `job.export {assets (≥ 1), preset = "web", out_dir?}` → `JobInfo` en `queued`. Los ids
    desconocidos fallan antes de encolar. `out_dir` por defecto: `Exportadas/` junto a la
    carpeta del proyecto.
  - `job.cancel {job}` → `JobInfo`; id desconocido → error del engine.
  - `job.list` → `{jobs}`, los últimos 50.
  - Eventos `job.progress` (como mucho ~10 por segundo, más cada cambio de foto) y después
    exactamente uno de `job.done` (`status` `done` o `cancelled`) o `job.failed`. Todos llevan
    el `JobInfo` completo. Salen por el mismo `Notifier` con lock que `thumbnail.ready`.
  - `asset.export` se quita: `job.export` lo reemplaza.
- Cerrar la sesión (fin de stdin) cancela lo encolado y lo que corre, y espera al worker hasta
  10 s.

## Mediciones
2026-11-23, Ryzen 5 3600, fotos de `tests/fixtures/photos`. Preview de arrastre 1024 px
(`preview.render` por `handle_line`) mientras se exporta `daylight-landscape.jpg` con preset
`original`, 6 exports por modo:

| Worker | Export (mediana) | Preview mediana / p95 / p99 | Previews > 100 ms |
|---|---|---|---|
| Sin export | — | 7.5 / — / 11.8 ms | 0 de 2000 |
| Hilo | 3.2–3.4 s | 8.0–8.6 / 26–29 / 37–45 ms | 0–7 de ~1650 |
| Proceso | 4.6 s | 7.9 / 21.7 / 38.9 ms | 12 de 2223 |
| Proceso BELOW_NORMAL | 4.1–5.1 s | 8.0–8.5 / 18–20 / 21–23 ms | 1–10 de ~2400 |
| Proceso en modo segundo plano (CPU + disco bajos) | 5.0–5.3 s | 7.9–8.0 / 21–23 / 38–42 ms | 5–10 de ~2400 |

- El GIL no se traba: un hilo Python que duerme 1 ms nunca esperó más de 50 ms durante el
  export.
- Los picos de 100–900 ms son **escrituras al disco** del JPEG chico de la preview
  (`write_bytes`/`os.replace`/`unlink`) mientras el export escribe su archivo grande. Aparecen
  igual con hilo o proceso, con prioridad baja de CPU y de disco: los causa el sistema de
  archivos (probablemente el antivirus en tiempo real), no la elección del worker.
- Cancelar con `set_kill` desde la señal `eval`: `write_to_file` falla 15 ms después.

## Alternativas consideradas
- **Proceso aparte (prioridad normal):** la preview queda parecida (p95 22 ms contra 26–29 ms),
  pero el export tarda ~40 % más (4.6 s contra 3.2–3.4 s), hay que arrancar el proceso y pasarle
  el proyecto, y cancelar a mitad de foto exige una señal entre procesos. Los picos de > 100 ms
  no desaparecen.
- **Proceso con prioridad baja (BELOW_NORMAL o modo segundo plano):** mejora el p99 de la
  preview en algunas corridas, pero el export se vuelve más lento y variable (4.1–5.3 s) y los
  picos siguen, porque vienen del disco.
- **Seguir síncrono:** descartado; es justamente lo que #60 tiene que resolver.

## Consecuencias
- El export es ~30 % más rápido que en un proceso, sin costo de arranque, cancela a mitad de
  foto y comparte la memoria del proceso (proxies, caché de libvips).
- La preview se mantiene en 8 ms de mediana y < 50 ms de p99 durante un export. Quedan unos
  pocos picos de > 100 ms por las escrituras al disco de la preview.
- Un fallo nativo de libvips durante un export tumbaría el engine entero (con un proceso, solo
  el export). Rust lo relanza (ADR-0010) y el proyecto se guarda solo; se pierde el job.
- Un método o evento nuevo de jobs pasa por el contrato de siempre: `pstudio schema --rpc` y
  `pnpm gen:types`.

## Seguimiento
- **Preview por stdio:** mandar los bytes de la preview por el canal en vez de escribirla en
  `cache/preview/` evitaría los picos que quedan. No entra en #60; revisarlo junto con el
  transporte de ADR-0010.
