# Pipeline de medios

## Foto
decode (pyvips; ICC → lineal float32) → ops en orden → encode (ICC de salida, EXIF según política).
Implementado en `engine/src/pstudio/render/io.py` (#10).

### Decode
- Formatos: JPEG, PNG, WebP y TIFF. Se valida la extensión **y** el decodificador real que usó
  libvips (un `.png` que en realidad es un GIF se rechaza).
- Se calcula el SHA-256 del original antes de leerlo. La apertura usa `revalidate`, porque
  libvips cachea por nombre de archivo y, si el original cambia en disco, devolvería los
  píxeles viejos.
- Se aplica la orientación EXIF (`autorot`).
- Espacio de trabajo: **scRGB float32** (RGB lineal, primarios sRGB, D65), sin recortar a 0…1:
  los colores fuera de la gama sRGB (p. ej. Display P3) se conservan como valores negativos o
  mayores que 1. El alpha viaja como 4.ª banda en 0…1.
- Sin perfil o con perfil sRGB → fórmulas de libvips (ida y vuelta exacta en 8 bits). Otro
  perfil (P3, Adobe RGB, CMYK) → LittleCMS (`icc_import`, intent relativo). Con las fotos de
  prueba, LittleCMS y las fórmulas difieren hasta 0.015 en lineal, por eso sRGB no pasa por ICC.

### Encode
- sRGB o Display P3, con el perfil de salida siempre embebido; 8 bits, o 16 bits en PNG/TIFF.
- JPEG: 4:4:4 desde Q90, Huffman optimizado. Si hay alpha, se aplana sobre blanco **en luz
  lineal**. WebP Q100 = sin pérdida.
- Metadatos: `keep` (todo) o `strip` (solo el perfil ICC). `strip_gps` queda para #14.
- **Originales protegidos:** se rechaza escribir sobre el original, aunque la ruta esté escrita
  de otra forma o sea un hardlink, y sobre cualquier ruta protegida. Primero se escribe un
  temporal y después se renombra, y al final se verifica que el hash del original no cambió.

### Identidad decode → encode (medido con las 8 fotos de `tests/fixtures`)
- **Sin pérdida (PNG/TIFF/WebP Q100): igualdad bit a bit**, también en las fotos reales.
- **Con pérdida:** la salida es idéntica bit a bit a re-guardar el original directamente con
  libvips con las mismas opciones. El viaje por float32 lineal no agrega pérdida; toda la
  pérdida es del códec. SSIM del JPEG contra el original (recorte central de 1024 px):

| foto | tamaño | perfil | Q90 | Q95 | Q100 |
|---|---|---|---|---|---|
| backlit-tree | 8257×5504 | sRGB | 0.9716 | 0.9820 | 0.9991 |
| candle-lowlight | 6000×4000 | sRGB | 0.9756 | 0.9836 | 0.9992 |
| daylight-landscape | 8064×6048 | sRGB | 0.9936 | 0.9970 | 0.9999 |
| product-white | 9708×6000 | sRGB | 0.9917 | 0.9945 | 0.9991 |
| stage-portrait | 4640×6960 (EXIF 8) | sin perfil | 0.9924 | 0.9951 | 0.9978 |
| starry-night-noise | 6000×4000 | sRGB | 0.9640 | 0.9880 | 0.9998 |
| warm-living-room | 5472×3648 | sin perfil | 0.9913 | 0.9980 | 0.9991 |
| warm-restaurant | 5472×3648 | sin perfil | 0.9936 | 0.9984 | 0.9991 |

  El criterio "SSIM > 0.999" de #10 se cumple con JPEG Q100 en 7 de 8 fotos (stage-portrait,
  con mucho ruido, da 0.9978) y no se cumple con Q95. Es un límite del JPEG, no del pipeline.
  Para "máxima calidad" conviene ofrecer TIFF/PNG o WebP sin pérdida (#14).
- **Proxy:** lado largo 2048 px para preview; mismo código que export.
- **Caché:** clave = hash(asset, versión del motor, ops[0..i]); límite de tamaño configurable
  (ver "Preview con caché incremental").
- **Lote:** cola de jobs, un worker por núcleo físico, cancelable.

### Preview con caché incremental (#31)
Implementado en `engine/src/pstudio/render/preview.py` (API de librería; la app la usa por RPC
desde M3).

- **Proxy:** `make_proxy(ruta, lado)` decodifica el original (solo lectura, con `revalidate`)
  ya reducido a `lado` px de lado largo (2048 por defecto; la app usa 1024 al arrastrar) y lo
  deja en memoria junto con el SHA-256 del original y `scale` (px del proxy por px del
  original). Desde #42 usa `decode(reduce_to=lado)`: un JPEG se decodifica ya reducido por
  libjpeg (×2/×4/×8, *shrink-on-load*) mientras queden ≥ 2·lado px, el resto lo hace lanczos3
  en lineal (alpha premultiplicado) y la orientación EXIF se aplica sobre la imagen chica. Esa
  primera reducción promedia en gamma (YCbCr), no en lineal: en las 8 fotos de prueba el proxy
  difiere del de la foto entera en 0.04–1.4 niveles de 8 bits de media (p99.9 ≤ 27; el peor
  caso es la textura fina contra el cielo de backlit-tree). A 2048 px las fotos de ≤ 32 MP no
  se reducen al decodificar y el proxy es el mismo de antes.
- **Etapas:** el plan se recorre en las mismas etapas que `apply_plan` (`plan_stages` en
  `ops/__init__.py`): un grupo de curvas tonales consecutivas fundidas en una LUT, una op
  automática o cualquier otra op sola; las ops neutras no cuentan. `apply_plan` y la preview
  usan el mismo código por etapa, así que la salida es **idéntica bit a bit** con y sin caché
  (verificado en tests y con las fotos de `tests/fixtures`).
- **Clave** de la etapa *k*: SHA-256 del JSON canónico de {versión del motor, SHA-256 del
  original, ancho×alto×bandas del proxy, `scale`, ops no neutras hasta el final de la etapa
  *k*}. Cambiar una op invalida su etapa y todas las siguientes; lo anterior se reutiliza.
- **Ops automáticas:** la copia chica que miden (analysis.py) se guarda en la entrada mientras
  quede alguna op automática más adelante. Una entrada sin esa copia no sirve para un plan que
  todavía la necesita y se trata como ausente.
- **Memoria:** caché en RAM con límite configurable (`PreviewCache(max_bytes=…)`, 512 MiB por
  defecto) y desalojo LRU. Cada entrada pesa ancho × alto × bandas × 4 bytes: 33.5 MB con un
  proxy de 2048×1365 RGB, o sea 16 entradas (dos variantes de una cadena de 8 etapas). Al
  reutilizar un prefijo se marcan como recientes todas sus etapas, así lo que se desaloja
  primero son las variantes viejas y no el prefijo en uso.
- **El export no usa esta caché:** siempre recalcula desde el original con `apply_plan`.

Medido con tres fotos de 24 MP (6000×4000: `candle-lowlight`, `starry-night-noise` y otra)
→ proxy 2048×1365, Ryzen 5 3600, libvips 8.18, cadena de 10 ops (exposure, white_balance,
contrast, highlights, shadows, saturation, vibrance, denoise, sharpen, vignette = 8 etapas):

| caso | tiempo (mediana) |
|---|---|
| abrir el proxy (`make_proxy`, decode JPEG incluido) | 470–660 ms |
| cadena completa sin caché (`apply_plan` + materializar) | 810–900 ms |
| cadena completa con caché, en frío (cambia la 1.ª op) | 480–550 ms |
| cambia la última op (vignette) | 50–58 ms (+5–10 ms a sRGB 8 bits) |
| cambia sharpen (recalcula sharpen + vignette) | 116–137 ms |
| cambia una op intermedia (saturation: recalcula también denoise) | 420–450 ms |
| cambia denoise | 315–365 ms |

En frío la caché es *más rápida* que `apply_plan`: materializar cada etapa evita que los
desenfoques de sharpen recalculen por tiles toda la cadena anterior (denoise incluido).

**Criterio "< 30 ms al cambiar la última op"** (medición de M1, antes de #42): se cumplía
solo si esa op era barata (exposure/white_balance/saturation 12–16 ms; vignette 40–45;
vibrance 51–64; sharpen 54–57; curva tonal 70–80; denoise 150–157). El costo es el de la etapa
que se recalcula más 1–4 ms de la caché, así que #42 abarató las ops mismas.

### Preview rápida (#42)
Bench reproducible: `cd engine && uv run python scripts/bench_preview.py` (usa
`tests/fixtures/photos`). Cadena de 10 de la app: exposure, contrast, highlights, shadows,
whites, blacks, white_balance, saturation, vibrance, vignette (las 5 curvas son una etapa).
Cada op se mide como **última** de la cadena (las extra van en lugar de exposure), con el
prefijo en caché y un valor distinto por cuadro; mediana de 7 cuadros. Foto backlit-tree
(8257×5504, 45 MP), Ryzen 5 3600, libvips 8.18.7, 12 hilos, 2026-11-20, con el equipo en uso
(los números varían ±10–20% entre corridas).

| op como última | antes 1024 px | antes 2048 px | ahora 1024 px | ahora 2048 px |
|---|---:|---:|---:|---:|
| exposure | 3.9 | 10.7 | 5.1 | 10.1 |
| contrast | 29.0 | 50.6 | 13.9 | 21.4 |
| highlights | 32.4 | 54.2 | 12.1 | 19.8 |
| shadows | 31.7 | 55.9 | 15.2 | 22.9 |
| whites | 27.2 | 59.1 | 12.4 | 20.5 |
| blacks (la mitad de los cuadros levanta el negro) | 30.6 | 51.9 | 19.2 | 33.1 |
| white_balance | 5.3 | 13.6 | 7.1 | 11.5 |
| saturation | 5.3 | 13.2 | 6.9 | 11.4 |
| vibrance | 29.4 | 55.4 | 21.7 | 28.7 |
| vignette | 21.2 | 39.7 | 8.0 | 13.1 |
| sharpen (radio 1.5: a 1024 px queda < 0.3 px y no hace nada) | 0.2 | 54.6 | 0.2 | 53.3 |
| denoise | 57.6 | 105.1 | 48.7 | 99.3 |
| auto_exposure | 41.2 | 47.5 | 3.9 | 10.1 |
| auto_white_balance | — ¹ | — ¹ | 4.2 | 11.5 |
| **cambia la 1.ª op: toda la cadena** | **96.5** | **196.4** | **52.3** | **141.4** |

¹ La primera versión del bench repetía el valor de la op y medía un acierto de la caché.

`make_proxy` en frío (decode + reducción + SHA-256 del original), mediana de 3, ms:

| foto | MP | antes 1024 | antes 2048 | ahora 1024 | ahora 2048 |
|---|---:|---:|---:|---:|---:|
| backlit-tree | 45 | 789 | 1274 | 488 | 576 |
| candle-lowlight | 24 | 330 | 461 | 197 | 352 |
| daylight-landscape | 49 | 900 | 3331 | 527 | 779 |
| product-white | 58 | 1650 | 2346 | 180 | 286 |
| stage-portrait | 32 | 285 | 322 | 194 | 373 |
| starry-night-noise | 24 | 422 | 563 | 324 | 477 |
| warm-living-room | 20 | 204 | 264 | 120 | 261 |
| warm-restaurant | 20 | 168 | 237 | 116 | 257 |

A 2048 px las fotos de 20–32 MP no se reducen al decodificar, así que la diferencia con
"antes" en esas filas es ruido de la medición. Se probó también abrir en modo secuencial de
libvips: fue 1.3–2.2× más lento y se descartó.

Qué cambió:
- **Curvas tonales** (`ops/_tone.py`): la LUT guarda la razón Y'/Y y se indexa con **los bits
  del float32 de Y** (exponente + 10 bits de mantisa → 1024 puntos por octava, de 2^-32 a
  2^31; los 13 bits bajos interpolan). Por píxel ya no hay potencias ni `ifthenelse`:
  luminancia, desplazamiento de bits, dos `maplut` y una multiplicación. Cambios de resultado,
  todos dentro de las golden (no se regeneró ninguna ni se tocó su tolerancia): por encima de
  Y ≈ 4.6 la curva se evalúa de verdad (antes se extendía con la ganancia del último punto);
  un píxel con Y ≤ 0 (fuera de gama) recibe el cambio del negro puro (antes también se le
  sumaba −Y); y si la curva no levanta el negro, donde Y ≤ 1e-6 se usa Y'/Y sin pasar de 1 en
  vez de sumar gris (la diferencia es < Y'(1e-6): sigue siendo negro). Solo blacks > 0
  necesita la segunda banda (gris sumado), que cuesta ~10 ms más a 2048 px.
- **vibrance:** k = 1 + s·(mín/máx)^(1/2.2) sale de una LUT con el mismo índice por bits, sin
  potencia ni `ifthenelse`.
- **vignette:** la máscara radial se calcula una vez por (ancho, alto, midpoint) y se guarda en
  memoria (≤ 4, solo en tamaños de preview); al mover amount solo cambia `exp(k·f)`. Mismos
  bytes que antes.
- **Ops automáticas:** la medición de la copia de análisis queda guardada en el estado del
  prefijo; mover su strength no vuelve a medir (antes ~35 ms por cuadro).
- **denoise:** en tamaños de preview materializa los desenfoques del filtro guiado (mismos
  bytes, 58 → 49 ms a 1024 px); a resolución completa no, por memoria.
- **Proxy:** shrink-on-load (ver arriba). El export no cambió de tiempo: 3.2 s ahora contra
  3.4 s antes con la cadena de M1 sobre candle-lowlight (24 MP), en este mismo equipo.
- La preview sigue dando **los mismos bytes** que `apply_plan` sobre el proxy.

**Lo que no llega a 30 ms a 2048 px, medido:**
- **denoise (≈ 100 ms) y sharpen (≈ 53 ms):** son desenfoques sobre la luminancia más
  potencias por píxel. Cada pasada de una banda a 2048 px cuesta 7–15 ms en este equipo, aun
  en memoria (materializar 33 MB nuevos incluye los fallos de página de Windows), y el filtro
  guiado necesita al menos cuatro. No se probó un filtro distinto: cambiaría el resultado del
  export.
- **blacks levantando el negro (≈ 33 ms)** y **la cadena entera a 2048 px (≈ 140 ms).**

**Qué tiene que hacer la UI (#58):**
- Mientras se arrastra, pedir la preview a **1024 px**: la cadena entera tarda ≈ 52 ms y cada
  op suelta ≤ 22 ms, salvo denoise (≈ 49 ms). Al soltar, refinar a 2048 (o al tamaño del
  visor).
- **Render progresivo para denoise y sharpen:** al mover su slider, o algo anterior a ellos,
  mostrar primero la preview del plan **sin** esas ops (su prefijo suele estar en caché) y
  después la completa. El engine no necesita nada nuevo: es un `preview.render` con la pila
  sin esas ops, seguido del pedido normal; "gana el último" descarta lo viejo.
- Al abrir una foto, pedir primero 1024 px: 116–527 ms en las fotos de prueba (las de 45–49 MP
  quedan justo en el límite de 500 ms). Mientras tanto se puede mostrar la miniatura.

## Video (M4)
Proxies (720p H.264 all-intra para scrubbing) → timeline OTIO → filtergraph FFmpeg → encode
(AMF H.264/HEVC o VP9 por software). Progreso parseando `-progress pipe:1`; cancelación matando el proceso.

> Librería de imagen: pyvips (ADR-0005).
