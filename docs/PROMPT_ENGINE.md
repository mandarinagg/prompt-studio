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
`pstudio eval [archivos|carpetas] --provider rules [-v] [--json reporte.json]` corre los casos de
`evals/prompts/*.toml` contra un proveedor (#16). El código está en
`engine/src/pstudio/prompting/evals.py`.

**Formato.** Los casos van en **TOML**, no en YAML como decía el borrador. TOML viene con
Python (`tomllib`), así que no suma una dependencia, y se lee igual de bien. Cada caso es un
bloque `[[cases]]`:

| Clave | Para qué |
|---|---|
| `id`, `prompt` | identificador único y pedido del usuario |
| `descriptors` | lo que el proveedor "ve" de la foto (mismo formato que `prompting/descriptors.py`) |
| `expect` | `ops` · `unsupported` · `clarification` · `clarification_or_ops` · `unsupported_or_ops` · `any` |
| `require` | ops necesarias; una lista adentro = alternativas (alcanza con una) |
| `require_if_ops` | con `clarification_or_ops`: si no pregunta, estas ops tienen que estar |
| `forbid` | ops que no deben aparecer |
| `sign` | `{"op.campo" = "+" o "-"}`: signo del valor si la op aparece |
| `values` | valor exacto (`"crop.aspect_ratio" = "1:1"`, `"export.format" = "webp"`) |
| `abs` | valor absoluto ±0.5 (`"rotate.degrees" = 90` acepta 90 y −90) |
| `max`, `min` | límites de un valor |
| `max_ops` | máximo de ops en el plan |
| `tags` | libre, para agrupar |

Una clave desconocida o un id repetido es un error: un caso mal tipeado no puede pasar por
"siempre correcto".

**Métricas por proveedor.**
- % válido al primer intento y % válido con el reintento.
- % correcto: válido y sin fallas de los criterios.
- Latencia por pedido (intentos sumados): mediana, p90 y máximo.

El proveedor se mide **sin** el respaldo de reglas, para que un LLM flojo no parezca bueno
gracias a las reglas.

**Casos.** `evals/prompts/spike5.toml` trae los 20 casos del spike #5.
