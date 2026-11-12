# Estrategia de pruebas

| Nivel | Qué | Herramienta |
|---|---|---|
| Esquema | Planes válidos/ inválidos, rangos, versiones | pytest + Pydantic |
| Operaciones | Neutro = identidad; monotonía (más EV → más brillo) | pytest + numpy |
| Golden images | Resultado ≈ referencia (SSIM ≥ 0.995 / PSNR) | pytest + scikit-image |
| Preview vs export | Export reducido ≈ preview (SSIM > 0.99) | pytest |
| Integridad | Hash de originales sin cambios tras toda operación | pytest |
| Prompts (evals) | % plan válido/correcto por proveedor | `evals/` runner |
| Rendimiento | Objetivos de `PRODUCT_SPEC.md` §7 | pytest-benchmark |
| UI (M3) | Componentes y flujo prompt→plan→export | Vitest + Playwright |

Fixtures en `tests/fixtures/`: solo medios con licencia libre (CC0) y documentados en
`tests/fixtures/SOURCES.md`. Los archivos pesados no se commitean: se descargan con un script.
