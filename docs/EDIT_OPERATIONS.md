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

## Export
`preset` (original, high_quality, web, catalog_square, social_vertical, story_9x16), y
opcionalmente `format` (jpeg, png, webp, tiff), `quality` (1–100), `color_space` (sRGB,
Display P3) y `metadata` (keep | strip | strip_gps). Lo que no se indica sale del preset o de la
fuente. Ver `EXPORT_PRESETS.md`.

## Agregar una operación
1. Modelo Pydantic + rango + neutro. 2. Implementación pura. 3. Golden test.
4. Regla del proveedor `rules` + casos en `evals/`. 5. Actualizar esta tabla.
