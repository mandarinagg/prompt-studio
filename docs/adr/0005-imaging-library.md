# ADR-0005 — Librería de imagen: pyvips (libvips) como motor de píxeles

- **Estado:** Propuesto
- **Fecha:** 2026-11-16
- **Evidencia:** spike #2, [`engine/spikes/imaging/RESULTS.md`](../../engine/spikes/imaging/RESULTS.md)

## Contexto
El engine necesita un pipeline float32 lineal que cumpla los objetivos de `PRODUCT_SPEC.md` §7 en
el equipo objetivo (Ryzen 5 3600, 16 GB): preview de 1 ajuste < 150 ms y export de 24 MP con
10 operaciones < 3 s. Además debe convivir en RAM con modelos de IA (M6).

## Decisión
- **pyvips (libvips 8.18, wheel `pyvips-binary`)** es el motor de píxeles para la decodificación,
  el proxy (shrink-on-load), las operaciones del catálogo, la preview y el export.
- **OpenCV** (`opencv-python-headless`) es una dependencia opcional para algoritmos puntuales que
  libvips no tiene (p. ej. denoise no-local). Intercambia datos con libvips vía numpy.
- **Pillow** no se usa para procesar píxeles; solo se admite para leer cabeceras y EXIF.

## Motivos (medido en el spike)
| 24 MP | Pillow+numpy | OpenCV | pyvips |
|---|---|---|---|
| Preview de 1 ajuste | 53–57 ms | 56–57 ms | **11–15 ms** |
| Export con 10 ops | 6.8–7.5 s ❌ | 3.0–3.5 s ⚠️ | **1.5–1.9 s** ✅ |
| Pico de RAM | 1.9 GB | 1.3 GB | **0.3 GB** (≈ constante hasta 58 MP) |

## Consecuencias
- Las operaciones del catálogo se implementan como grafos lazy de libvips; cada op sigue siendo
  una función pura `(imagen, params) -> imagen`.
- La caché incremental por operación es **obligatoria**: la cadena completa de 10 ops sobre el
  proxy tarda 149–186 ms, justo en el límite.
- Los tests deben desactivar la caché de operaciones de libvips (`pyvips.cache_set_max(0)`) al
  medir rendimiento.
- El preset de export debe fijar el submuestreo de croma (4:4:4 vs 4:2:0) de forma explícita;
  el valor por defecto de libvips depende de Q.
- **Licencias:** libvips es LGPL-2.1 y se enlaza dinámicamente (DLL del wheel), lo que es
  compatible con ADR-0004. Hay que registrarlo en el inventario de licencias. OpenCV es Apache-2.0.
- **Empaquetado:** las DLL de libvips deben entrar en el sidecar; se verifica en el spike #3.

## Alternativas
- **OpenCV como motor:** viable para la preview, pero el export de 24 MP queda en el límite o por
  encima de 3 s y usa de 4 a 9 veces más memoria.
- **Pillow + numpy:** numpy usa un solo hilo y Pillow no opera en float32 para filtros; no cumple
  el objetivo de export.
