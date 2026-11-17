# Perfiles de exportación

Implementados en `engine/src/pstudio/export.py` (#14). Toda exportación es una **copia**: el
motor se niega a escribir sobre un original y verifica su hash al terminar.

| Preset | Formato | Tamaño | Calidad | Color | Metadatos | Estado |
|---|---|---|---|---|---|---|
| `original` | igual a la fuente | original | 100 | P3 si la fuente es P3, si no sRGB | keep | probado (2 fotos) |
| `high_quality` | TIFF 16-bit si la fuente es de 16 bits; si no, JPEG 95 | original | 95 | P3 si la fuente es P3, si no sRGB | keep | probado (2 fotos) |
| `web` | WebP | lado largo 2048 (nunca agranda) | 85 | sRGB | strip_gps | probado (8 fotos) |
| `catalog_square` | JPEG | 1080×1080 (recorte centrado) | 90 | sRGB | strip | probado (2 fotos) |
| `social_vertical` | JPEG | 1080×1350 (4:5, recorte centrado) | 90 | sRGB | strip | probado (2 fotos) |
| `story_9x16` | JPEG | 1080×1920 (recorte centrado) | 90 | sRGB | strip | probado (2 fotos) |
| `video_1080p` (M4) | MP4 H.264 (AMF) + AAC | 1920×1080 | CQP a definir | BT.709 | — | borrador |

"Probado" = exportado desde las fotos de `tests/fixtures` (24–48 MP) y verificados tamaño,
formato, perfil ICC embebido y metadatos. No es una validación de calidad percibida por
usuarios.

## Precedencia
Cada ajuste (formato, calidad, espacio de color, metadatos) sale de lo primero que lo indique:
**opciones de la CLI > `export` del plan > preset > la fuente**. El preset por defecto es
`original`.

## Metadatos
- `keep`: todo (EXIF, XMP, IPTC) más el perfil ICC de salida.
- `strip_gps`: todo menos la ubicación. libvips reconstruye el EXIF sin el bloque GPS y
  conserva el resto (cámara, fecha, exposición). Si el XMP menciona GPS, se descarta entero.
  Probado con las fotos de prueba, que traen GPS real (14 campos en el paisaje).
- `strip`: solo el perfil ICC.

## Achicar antes del plan
Si el preset achica la salida (web, cuadrado, 4:5, 9:16), la fuente se reduce primero a
1.25× el tamaño final y el plan se aplica con `scale`, igual que en la preview. Después, un
Lanczos lleva al tamaño exacto.
- Lote web de las 8 fotos de prueba: **52.8 s → 14.4 s**.
- Contra procesar a tamaño completo, el resultado es casi igual en fotos normales (SSIM
  0.98–0.99).
- Donde hay mucho ruido de sensor (la foto nocturna: SSIM 0.72, diferencia media 8/255), el
  grano queda distinto. La diferencia aparece aun sin ops: reducir en dos pasos muestrea el
  ruido distinto que reducir en uno. El contenido es el mismo.

## Uso desde la terminal
```
pstudio apply plan.json foto.jpg -o salida/ --preset web
pstudio apply plan.json carpeta/ -o salida/ --preset social_vertical   # lote
pstudio apply plan.json carpeta/ -o salida/ -r --format png --metadata strip
```
- Opciones: `--preset`, `--format`, `--quality`, `--color-space`, `--metadata`, `-r` (incluye
  subcarpetas y conserva su estructura) y `--overwrite` (reemplaza exportaciones previas,
  nunca originales).
- Lote: los archivos que no son imágenes se omiten con aviso. Si dos entradas tienen el mismo
  nombre (`foto.jpg` y `foto.png`), las salidas se distinguen con la extensión de origen
  (`foto_jpg.webp`, `foto_png.webp`). Un archivo roto no frena el resto.
- Códigos de salida: 0 = todo bien, 1 = algún archivo falló, 2 = error de uso (plan inválido,
  entrada inexistente, opciones inválidas).

## Observaciones
- `original` con JPEG calidad 100 pesa unas 2× la fuente (retrato de 7.3 MB → 15.4 MB): es lo
  que cuesta no agregar pérdida. Para un tamaño razonable con calidad alta, usar
  `high_quality` (JPEG 95: 6.7 MB).
