# Catálogo de operaciones — Foto v1

Cada operación es una función pura `(imagen float32 lineal, params) → imagen`, con
parámetros acotados y valor neutro (no-op). Orden de aplicación = orden del plan, y **cada op
aparece una sola vez** por plan.

Fuente única: `engine/src/pstudio/schema/plan.py` (Pydantic). JSON Schema versionado en
`engine/schema/edit-plan-1.0.schema.json` (`pstudio schema`). Validar un plan:
`pstudio validate plan.json`. Un test verifica que esta tabla y el código tengan las mismas ops.
Un parámetro omitido toma el valor por defecto, que es el neutro cuando existe.

| op | Parámetros | Rango | Neutro |
|---|---|---|---|
| `exposure` | `ev` | −5 … +5 | 0 |
| `auto_exposure` | `strength` (def. 1) | 0 … 1 | — |
| `contrast` | `amount` | −100 … 100 | 0 |
| `highlights` | `amount` | −100 … 100 | 0 |
| `shadows` | `amount` | −100 … 100 | 0 |
| `whites` / `blacks` | `amount` | −100 … 100 | 0 |
| `white_balance` | `temperature_shift`, `tint_shift` | −100 … 100 | 0 |
| `auto_white_balance` | `method` (def. `gray_world`) | `gray_world` \| `white_patch` | — |
| `saturation` / `vibrance` | `amount` | −100 … 100 | 0 |
| `crop` | `aspect_ratio` **o** `rect` {x, y, width, height}; `anchor` (def. `center`) | 1:1, 4:5, 5:4, 3:2, 2:3, 4:3, 3:4, 16:9, 9:16; `rect` en fracciones 0 … 1; anchor: center, subject_or_center, top, bottom, left, right | — |
| `rotate` | `degrees` | −180 … 180 | 0 |
| `straighten` | `degrees` | −45 … 45 | 0 |
| `resize` | `width` y/o `height`, `fit` (def. `contain`) | 1 … 16384; fit: contain, cover, exact (cover y exact piden ambos lados) | — |
| `sharpen` | `amount`, `radius` (def. 1.0) | 0 … 100, 0.5 … 5 | 0 |
| `denoise` | `strength` | 0 … 1 | 0 |
| `vignette` | `amount`, `midpoint` (def. 50) | −100 … 100, 0 … 100 | 0 |

## Implementación de las ops tonales (#11)
`engine/src/pstudio/ops/tonal.py`. Son globales (sin máscaras espaciales en v1) y monótonas:
nunca invierten el orden de los tonos.
- `exposure`: multiplica la luz lineal por 2^ev (exacto, como en cámara).
- Las demás son curvas sobre la luminancia en escala perceptual `p = Y^(1/2.2)` y se aplican
  como razón `RGB · Y'/Y`, así que **no cambian tono ni saturación**.
  - `contrast`: curva S alrededor del gris medio (18 %), que queda fijo, igual que el negro y el
    blanco.
  - `shadows`: hasta ±3 EV en las sombras profundas, que se apaga hasta 0 en el gris medio.
    Medios y altas luces no cambian (en un contraluz levanta el árbol de 9/255 a 41/255 sin
    tocar el cielo).
  - `highlights`: actúa sobre los tonos altos (pico en p ≈ 2/3); el negro y el blanco quedan
    fijos.
  - `whites` / `blacks`: mueven el punto blanco o el punto negro.
- Rendimiento: las curvas consecutivas de un plan se componen en **una sola LUT** (65 536 puntos
  con interpolación lineal). 6 ops tonales cuestan 118 ms en un proxy de 2048 px; un export de
  24 MP con decode + 6 ops + JPEG, 0.73 s (Ryzen 5 3600).
- Pendiente: reglas del proveedor `rules` y evals para estas ops (M2, #15/#16).

## Implementación de las ops de color (#12)
`engine/src/pstudio/ops/color.py` y los analizadores en `engine/src/pstudio/analysis.py`.
- `white_balance`: adaptación cromática en el espacio de conos (Bradford), como una cámara.
  `temperature_shift` ±100 corre ≈ 1 EV la relación rojo/azul; `tint_shift` ±100 mueve el
  verde ±0.5 EV. El gris conserva su luminancia.
- `saturation`: escala la distancia de cada color al gris de igual luminancia (−100 = blanco y
  negro, +100 = el doble). La luminancia no cambia.
- `vibrance`: igual, pero pesado por lo apagado que está cada color (saturación medida en
  escala perceptual): sube marrones y verdes apagados y casi no toca rojos ya saturados ni
  piel.
- `auto_white_balance`: estima el iluminante y lo lleva a neutro con la misma adaptación,
  como máximo ±1 EV por cono.
  - `gray_world` promedia solo los píxeles poco saturados. Con todos, una pared roja o un
    mantel "son" el iluminante y la foto se tiñe del color opuesto: pasaba en las fotos de
    restaurante y escenario de `tests/fixtures`.
  - `white_patch` toma el 1 % más luminoso sin recortar.
- `auto_exposure`: banda muerta para la clave de la escena (media geométrica de Y entre 0.10
  y 0.45).
  - Si la clave está por debajo de la banda, aclara hasta el borde, pero sin llevar a blanco
    recortado el p99 de lo que hoy no lo está.
  - Si está por encima, oscurece solo si la foto está lavada, es decir, sin tonos profundos
    (p1 > 0.10). Así no grisea una foto de producto sobre fondo blanco.
  - Como máximo ±2 EV, escalado por `strength`.
- **Analizadores deterministas** (`pstudio analyze foto.jpg` imprime el JSON).
  - Qué miden: histograma de 64 bins en escala perceptual, percentiles, clave, fracción
    recortada en blancos y negros, gris promedio y "parche blanco".
  - Cómo: sobre la imagen reducida a ≤ 512 px por bloques, sin contar píxeles transparentes.
  - Preview (2048 px) y export (full) dan lo mismo: en las 8 fotos de prueba la clave difiere
    ≤ 3 % (≈ 0.04 EV) y el balance estimado, < 0.002.
  - Dentro de un plan, las ops automáticas miden una copia chica que pasa por las mismas ops
    (`apply_plan`), en lugar de recalcular la imagen entera.
- Probado sobre las fotos de `tests/fixtures`:
  - `auto_exposure` da 0 EV en el paisaje de día y en el producto sobre blanco, +0.52 EV en el
    living cálido y +0.28 EV en el retrato de escenario (frenado por las luces).
  - `auto_white_balance` no invierte los colores dominantes de ninguna foto.
- Rendimiento (Ryzen 5 3600, proxy 2048 px de una foto de 24 MP):
  - Preview de una op: 11–62 ms (las automáticas, ~52 ms con el análisis incluido).
  - Export de 24 MP con 10 ops (4 de color + 6 tonales) más decode y JPEG: **1.9 s**.
  - Ambos dentro de los objetivos del spec (< 150 ms y < 3 s).
- Pendiente: reglas del proveedor `rules` y evals (M2).

## Export
`preset` (original, high_quality, web, catalog_square, social_vertical, story_9x16), y
opcionalmente `format` (jpeg, png, webp, tiff), `quality` (1–100), `color_space` (sRGB,
Display P3) y `metadata` (keep | strip | strip_gps). Lo que no se indica sale del preset o de la
fuente. Ver `EXPORT_PRESETS.md`.

## Agregar una operación
1. Modelo Pydantic + rango + neutro. 2. Implementación pura. 3. Golden test.
4. Regla del proveedor `rules` + casos en `evals/`. 5. Actualizar esta tabla.
