# Spike #2 — pyvips vs OpenCV vs Pillow (resultados)

**Fecha:** 2026-11-16 · **Equipo:** Ryzen 5 3600 (6c/12t), 16 GB, Windows 11 · **Decisión:** ver
[ADR-0005](../../../docs/adr/0005-imaging-library.md)

Versiones: Python 3.12.16, numpy 2.5.5, Pillow 13.0.0, OpenCV 5.0.0, libvips 8.18.7.

## Qué se midió
El mismo pipeline en RGB lineal float32 implementado con cada librería
([`pipelines.py`](pipelines.py)): exposición, balance de blancos, contraste, saturación, nitidez
(unsharp mask) y viñeta. Cadenas: **1 op**, **4 ops** (las del issue: exposición + WB + contraste +
nitidez) y **10 ops** (objetivo de `PRODUCT_SPEC.md` §7).

- `open_proxy`: decodificar + reducir a 2048 px + pasar a lineal (al abrir una foto).
- `preview_N`: aplicar la cadena al proxy en RAM y convertir a sRGB 8 bits. **Peor caso**: sin la
  caché incremental de la arquitectura; se recalcula toda la cadena en cada cambio.
- `export_N`: decodificar a resolución completa + cadena + JPEG q92 a disco.
- Mediana de 15 rondas (preview) / 3 rondas (export); un proceso por backend e imagen; caché de
  operaciones de libvips desactivada.

**Equivalencia verificada** ([`check_equivalence.py`](check_equivalence.py)): desde la misma
entrada, OpenCV y pyvips difieren de la referencia como máximo en 1 nivel de 255
(PSNR 56–∞ dB) en las tres cadenas.

## Resultados (mediana, ms)

| imagen | MP | backend | open_proxy | preview 1 op | preview 4 ops | preview 10 ops | export 4 ops | export 10 ops | pico RAM |
|---|---|---|---|---|---|---|---|---|---|
| candle-lowlight | 24.0 | Pillow+numpy | 280 | 53 | 319 | 728 | 4060 | 6841 | 1900 MB |
| | | OpenCV | 167 | 57 | 136 | 248 | 1624 | 2965 | 1265 MB |
| | | **pyvips** | 221 | **11** | **88** | **149** | **776** | **1513** | **288 MB** |
| starry-night-noise | 24.0 | Pillow+numpy | 398 | 57 | 367 | 720 | 4224 | 7514 | 1900 MB |
| | | OpenCV | 275 | 56 | 151 | 285 | 2084 | 3546 | 1265 MB |
| | | **pyvips** | 330 | **15** | **79** | **171** | **1085** | **1894** | **306 MB** |
| backlit-tree | 45.4 | Pillow+numpy | 516 | 57 | 361 | 643 | 9932 | 14648 | 3538 MB |
| | | OpenCV | 460 | 60 | 148 | 266 | 3525 | 6990 | 2329 MB |
| | | **pyvips** | 540 | **12** | **101** | **165** | **1911** | **3723** | **326 MB** |
| product-white | 58.2 | Pillow+numpy | 280 | 50 | 294 | 592 | 11721 | 32296 | 4457 MB |
| | | OpenCV | 330 | 100 | 232 | 468 | 4701 | 11854 | 2961 MB |
| | | **pyvips** | 319 | **18** | **121** | **186** | **1993** | **3764** | **319 MB** |

Datos crudos (incluye p90 y mínimos): [`results.json`](results.json).

## Contra los objetivos (fotos de 24 MP)

| Objetivo | Meta | Pillow+numpy | OpenCV | pyvips |
|---|---|---|---|---|
| Preview de 1 ajuste | < 150 ms | ✅ 53–57 | ✅ 56–57 | ✅ **11–15** |
| Export con 10 ops | < 3 s | ❌ 6.8–7.5 s | ⚠️ 3.0–3.5 s | ✅ **1.5–1.9 s** |
| Pico de memoria | (16 GB en total) | 1.9 GB | 1.3 GB | **0.3 GB** |

## Conclusiones
1. **pyvips gana en todo lo que importa.** Es 2× más rápido que OpenCV y 4–9× más rápido que
   Pillow+numpy al exportar, y usa **4–14× menos memoria**. Su memoria casi no crece con la
   resolución (288 → 319 MB de 24 a 58 MP) porque procesa por bloques; OpenCV y numpy cargan la
   imagen entera en float32 (≈ 12 bytes/píxel por copia).
2. **El export de pyvips fue además el más exigente:** a Q ≥ 90 libvips guarda la croma sin
   submuestreo (4:4:4, archivos ~20 % más grandes); Pillow y OpenCV usan 4:2:0. Con
   `subsample_mode="on"` el tamaño iguala al de los demás. Elegir 4:4:4 o 4:2:0 es una decisión
   del preset de export (`EXPORT_PRESETS.md`).
3. **La preview con 10 ops recalculando todo queda justo en el límite** (149–186 ms). La caché
   incremental por operación (ARCHITECTURE.md) es necesaria y no opcional: al mover el slider de la
   op *i* solo se recalcula desde *i*.
4. **Abrir una foto** (crear el proxy) cuesta 0.2–0.5 s con cualquier librería. Está dominado por
   la decodificación JPEG, así que conviene cachear el proxy en disco y no recrearlo en cada
   apertura.
5. **Pillow+numpy no sirve como motor**: numpy usa un solo hilo y Pillow no desenfoca en float32.
   Sí sirve para leer cabeceras/EXIF de forma barata.
6. **OpenCV queda como complemento** para algoritmos que libvips no tiene (p. ej. denoise
   no-local, detección), no como motor del pipeline. Nota: `cv2.imread` no admite rutas Unicode
   en Windows; hay que usar `cv2.imdecode(np.fromfile(...))`.

## Limitaciones del spike
- Medido solo con JPEG de 8 bits; RAW/16 bits queda para M7.
- Un único equipo (el objetivo). Caché de disco del SO caliente en todas las mediciones.
- Las implementaciones son de spike, no están optimizadas; la caché incremental no está
  implementada.

## Reproducir
```powershell
uv run --no-project --python 3.12 tests/fixtures/fetch_fixtures.py   # desde la raíz
cd engine
uv run --group spike python spikes/imaging/check_equivalence.py
uv run --group spike python spikes/imaging/run_all.py                 # ~5 min
```
