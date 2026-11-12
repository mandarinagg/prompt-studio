# Catálogo de operaciones — Foto v1 (borrador)

Cada operación es una función pura `(imagen float32 lineal, params) → imagen`, con
parámetros acotados y valor neutro (no-op). Orden de aplicación por defecto = orden del plan.

| op | Parámetros | Rango | Neutro |
|---|---|---|---|
| `exposure` | `ev` | −5 … +5 | 0 |
| `auto_exposure` | `strength` | 0 … 1 | — |
| `contrast` | `amount` | −100 … 100 | 0 |
| `highlights` | `amount` | −100 … 100 | 0 |
| `shadows` | `amount` | −100 … 100 | 0 |
| `whites` / `blacks` | `amount` | −100 … 100 | 0 |
| `white_balance` | `temperature_shift`, `tint_shift` | −100 … 100 | 0 |
| `auto_white_balance` | `method` | `gray_world` \| `white_patch` | — |
| `saturation` / `vibrance` | `amount` | −100 … 100 | 0 |
| `crop` | `aspect_ratio` \| `rect`, `anchor` | `"1:1"`, `"4:5"`, `"9:16"`… | — |
| `rotate` | `degrees` | −180 … 180 | 0 |
| `straighten` | `degrees` | −45 … 45 | 0 |
| `resize` | `width`, `height`, `fit` | 1 … 16384 | — |
| `sharpen` | `amount`, `radius` | 0 … 100, 0.5 … 5 | 0 |
| `denoise` | `strength` | 0 … 1 | 0 |
| `vignette` | `amount`, `midpoint` | −100 … 100, 0 … 100 | 0 |

## Export
`format` (jpeg, png, webp, tiff), `quality` (1–100), `color_space` (sRGB, Display P3),
`metadata` (keep | strip | strip_gps), `preset`. Ver `EXPORT_PRESETS.md`.

## Agregar una operación
1. Modelo Pydantic + rango + neutro. 2. Implementación pura. 3. Golden test.
4. Regla del proveedor `rules` + casos en `evals/`. 5. Actualizar esta tabla.
