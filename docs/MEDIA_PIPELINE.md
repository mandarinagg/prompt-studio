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

- **Proxy:** `make_proxy(ruta)` decodifica el original (solo lectura, con `revalidate`), lo
  reduce a 2048 px de lado largo (lanczos3, alpha premultiplicado) y lo deja en memoria junto
  con el SHA-256 del original y `scale` (px del proxy por px del original).
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

**Criterio "< 30 ms al cambiar la última op": se cumple solo si esa op es barata.** El costo
es el de la etapa que se recalcula más 1–4 ms de la caché (claves, desalojo). Con cada op al
final de la cadena de 10 (límite 512 MiB):

| última op | ms |
|---|---|
| exposure / white_balance / saturation | 12–16 ✅ |
| vignette | 40–45 ❌ |
| vibrance | 51–64 ❌ |
| sharpen | 54–57 ❌ |
| una curva tonal (contrast) | 70–80 ❌ |
| denoise | 150–157 ❌ |

Para bajar de 30 ms en esas ops hay que abaratar las ops mismas (p. ej. la máscara radial de
vignette o la cantidad de pasadas de las curvas), no la caché. Mientras denoise no sea la op
que cambia y esté antes de ella, no se recalcula: su costo (≈ 165 ms por etapa en el proxy)
solo se paga al moverla a ella o a algo anterior.

## Video (M4)
Proxies (720p H.264 all-intra para scrubbing) → timeline OTIO → filtergraph FFmpeg → encode
(AMF H.264/HEVC o VP9 por software). Progreso parseando `-progress pipe:1`; cancelación matando el proceso.

> Librería de imagen: pyvips (ADR-0005).
