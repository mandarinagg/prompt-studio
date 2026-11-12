# Motor de prompts

## Contrato
Entrada: `prompt` (texto), `asset_descriptors` (texto/JSON generado localmente), `catalog`
(operaciones disponibles en este equipo). Salida: un `EditPlan` validado. Nunca código.

```json
{
  "schema_version": "1.0",
  "asset": "image_001",
  "source_prompt": "Mejorá la iluminación y prepará una versión cuadrada para catálogo",
  "operations": [
    {"op": "auto_exposure", "strength": 0.8},
    {"op": "auto_white_balance"},
    {"op": "shadows", "amount": 20},
    {"op": "crop", "aspect_ratio": "1:1", "anchor": "subject_or_center"}
  ],
  "export": {"preset": "catalog_square"},
  "explanation": "Subo la exposición (la foto está 1 EV por debajo), corrijo el tono cálido, abro sombras y recorto 1:1.",
  "unsupported": [],
  "clarification": null
}
```

## Proveedores (`PlanProvider`)
| Proveedor | Disponibilidad | Uso |
|---|---|---|
| `rules` | Siempre, offline | Palabras clave ES/EN → ops; fallback garantizado |
| `local_llm` | Si hay modelo instalado | llama.cpp/Ollama (Vulkan), salida restringida por JSON Schema |
| `cloud_llm` | Opt-in explícito | p. ej. Claude vía tool use / salida estructurada. **Solo texto** |

Pipeline: proveedor → parseo → validación Pydantic → verificación de catálogo/rangos →
si falla, un reintento con el error; si vuelve a fallar, se cae al proveedor `rules` y se avisa.

## Reglas
- Valores relativos o `auto_*`; los absolutos solo si el usuario los pide ("1080×1080").
- Ambigüedad relevante → `clarification` con una pregunta concreta, sin ops.
- Pedido fuera del catálogo → `unsupported` con motivo y alternativa.
- El texto del prompt y los metadatos se tratan como datos (resistencia a prompt injection:
  un EXIF que diga "ignora instrucciones" no cambia nada porque solo hay ops del catálogo).

## Evaluación
`evals/prompts/*.yaml`: `prompt`, `descriptors`, `expected` (ops requeridas/prohibidas,
rangos). Métricas por proveedor: % JSON válido, % plan correcto, latencia.
