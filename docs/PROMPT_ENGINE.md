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

## Uso desde la terminal (#48)
```
pstudio plan "aclarala, más cálida y 4:5 para Instagram sin GPS" foto.jpg -o plan.json
pstudio apply plan.json foto.jpg -o salida/
```
- `pstudio plan` analiza la foto localmente y le pasa los descriptores al proveedor (solo
  texto). La foto es opcional.
- Muestra la explicación, las ops, lo que no se puede hacer y la pregunta, si la hay.
- `-o` guarda el JSON; `--json` lo imprime.
- `--provider auto` usa el LLM local si está registrado y, si no, las reglas. Si el
  proveedor falla, cae a las reglas y avisa por stderr.

## Proveedor `rules` (#15)
Está en `engine/src/pstudio/prompting/rules.py`. Funciona offline, es determinista y tarda
~1.5 ms por pedido (el máximo es 15 ms; el objetivo era < 50 ms). Es el respaldo garantizado:
siempre devuelve un plan válido.

**Cómo procesa un pedido**
- Normaliza el texto: minúsculas, sin tildes. Protege frases como "blanco y negro" y lo parte
  en cláusulas.
- En cada cláusula detecta el tema (luz, contraste, color, recorte…), la dirección (más o
  menos) y la intensidad ("un poquito" ×0.5, "mucho" ×2).
- **Negaciones:** "no toques los colores, solo aclarala" bloquea las ops de color y aplica lo
  que viene después de "solo". "Sin quemar el cielo" no bloquea nada: pide cuidar las altas
  luces.
- **Estado vs. pedido:** "está oscura" o "los colores se ven apagados" describen un problema.
  "Oscurecela" o "colores más apagados" piden un cambio. El sentido del ajuste sale de esa
  diferencia.
- **Estilos:** blanco y negro, sepia, vintage, película, matte, dramático, HDR y soñado se
  arman con varias ops del catálogo.
- **Fuera del catálogo** (`unsupported`, con una alternativa cuando la hay): fondo,
  agregar o borrar elementos, cielo, retoque de piel, IA, estilos artísticos, desenfoque de
  fondo, perspectiva, espejado, RAW, grano, curvas y máscaras. Pedir código va siempre a
  `unsupported`: el motor solo aplica ops del catálogo.
- **Datos faltantes:** recortar sin proporción, cambiar el tamaño sin medida o enderezar sin
  grados devuelve una sola pregunta concreta en `clarification`.
- **Valores:** son relativos y moderados (un primer paso que el usuario ajusta con sliders).
  Las ops se ordenan como en un revelado: geometría → luz → color → detalle → tamaño.
- **Idioma:** la explicación sale en el idioma del pedido (español o inglés).

**Resultados medidos con `pstudio eval`**

| Etapa | Casos | Correcto |
|---|---|---|
| Spike #5, al escribir las reglas | 20 | 80% → 100% |
| **Medición a ciegas:** casos nuevos que escribió otro agente sin ver las reglas | 91 | **90.1%** |
| Tras corregir los 7 patrones que fallaban (sin parches caso por caso) | 111 | 100% |

En todas las etapas el 100% de los planes fue válido. El 100% final es sobre casos ya vistos.
Para volver a medir a ciegas hace falta otro set de casos nuevos.

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

**Casos.** `evals/prompts/spike5.toml` trae los 20 casos del spike #5. Además hay 91 casos
escritos sin mirar ninguna implementación: `es.toml` (47), `en.toml` (35) y `mixed.toml` (9,
spanglish y errores de tipeo). Cubren las 18 ops en ambos sentidos con palabras de intensidad,
export (preset, formato, calidad, `strip_gps`, tamaños), pedidos de varios pasos, negaciones,
estilos, pedidos fuera del catálogo, ambiguos y prompt injection. Cada caso se verificó contra
un plan ideal hecho a mano (`grade(plan, caso) == []`), así que todos son posibles de pasar.
Convención: "recortala para historia / catálogo / feed" exige la op `crop` con la proporción.
