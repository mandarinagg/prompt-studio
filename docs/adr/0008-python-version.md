# ADR-0008 — Python 3.14.10 en desarrollo y en distribución

- **Estado:** Aceptado (2026-11-16)
- **Fecha:** 2026-11-16
- **Issue:** #24
- **Actualiza:** ADR-0002 (decía Python 3.12) y ADR-0006 (embebible 3.12.10)

## Contexto
python.org publica binarios (y el paquete embebible del sidecar, ADR-0006) solo mientras una
rama recibe correcciones de bugs. La rama 3.12 ya solo recibe parches de seguridad en código
fuente: el último embebible es el 3.12.10, mientras que el desarrollo usaba 3.12.16. El runtime
distribuido no iba a recibir parches de seguridad y además no coincidía con el de desarrollo.

## Decisión
- **Python 3.14**, fijado a la **misma versión de parche** en los dos lados:
  - desarrollo: `engine/.python-version` = `3.14.10` (uv, `--no-bin`; no toca el Python del
    sistema);
  - distribución: `python-3.14.10-embed-amd64.zip`, con SHA-256 tomado de la API de python.org
    (`90905e64…4159`) y verificado en `build_embed.py`.
- `requires-python = ">=3.14,<3.15"`.
- Cada actualización de parche cambia los dos valores juntos.

## Evidencia (2026-11-16)
Wheels de Windows x64 en PyPI para lo que se necesita hasta M6:

| paquete | 3.14 | 3.15 |
|---|---|---|
| pyvips-binary 8.18.7 | ✅ (abi3) | ✅ (abi3) |
| numpy 2.5.5, pydantic-core 2.50.4, cffi 2.1.1, pillow 13 | ✅ | ✅ |
| opencv-python-headless 5.0 | ✅ (abi3) | ✅ (abi3) |
| **onnxruntime-directml 1.24.4** (IA local, M6) | ✅ | ❌ |
| onnxruntime 1.32 | ✅ | ❌ |

Con 3.14.10: `ruff` y los 13 tests pasan, los pipelines del spike #2 dan el mismo resultado y
el embebible 3.14.10 arranca así (mediana de 10):

| | 1ª respuesta | + libvips | + leer foto 24 MP |
|---|---|---|---|
| embebible 3.12.10 (ADR-0006) | 79 ms | 108 ms | 110 ms |
| **embebible 3.14.10** | 95 ms | 126 ms | 128 ms |

Unos 18 ms más, dentro de un objetivo de arranque de 3 s. `python.exe` y `python314.dll` tienen
firma Authenticode válida de la Python Software Foundation. El runtime pesa 83 MB (antes 81).

## Alternativas consideradas
- **Quedarse en 3.12.10:** sin parches de seguridad en binarios y con una versión distinta a la
  de desarrollo. Descartado.
- **3.13:** sale de la fase de correcciones de bugs (y de binarios) en pocos meses. Descartado.
- **3.15:** sin wheels de onnxruntime(-directml), lo que bloquea M6. Reevaluar cuando 3.14 se
  acerque al fin de sus binarios (~octubre de 2027).

## Consecuencias
- El código puede usar la sintaxis de 3.14. Ruff con `target-version = "py314"` ya aplica
  PEP 758 (`except A, B:` sin paréntesis).
- Revisar este ADR antes de octubre de 2027.
