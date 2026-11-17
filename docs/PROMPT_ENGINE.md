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
| `local_llm` | Si hay modelo configurado | llama-server de llama.cpp (Vulkan) + Qwen3-8B, salida restringida por JSON Schema (ADR-0007) |
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
- `--provider auto` usa el LLM local si está configurado y, si no, las reglas. Si el
  proveedor falla, cae a las reglas y avisa por stderr.

## Proveedor `cloud` (#18): opt-in, solo texto
Está en `engine/src/pstudio/prompting/cloud.py`. Usa Claude a través del SDK oficial de
Anthropic, que es un extra opcional: `uv sync --extra cloud`.

**Cómo se activa.** Está apagado por defecto y nunca entra en `--provider auto`. Para usarlo
hacen falta las dos cosas:
- `PSTUDIO_CLOUD=1`;
- la clave en la variable de entorno `ANTHROPIC_API_KEY` (nunca en el repo).

Sin eso, el pipeline usa las reglas y lo avisa.

**Qué se envía.** Solo el pedido y los descriptores numéricos de la foto. No se envían la foto,
su ruta ni su nombre de archivo. `pstudio plan --provider cloud` muestra por stderr el texto
exacto antes de enviarlo.

**Cómo pide el plan.**
- Modelo `claude-opus-5-5` (se cambia con `PSTUDIO_CLOUD_MODEL`) con esfuerzo `low`: un plan
  es una tarea corta.
- La salida está restringida al JSON Schema del EditPlan (structured outputs). El esquema se
  adapta a lo que acepta la API: sin `minimum`/`maximum` y con `oneOf` convertido en
  `anyOf`. Los rangos los vuelve a validar el pipeline.
- Ante una negativa por seguridad hay respaldo del lado del servidor
  (`fallbacks: "default"`).

**Errores.** Un error de red, de clave o de límite de pedidos se informa y se cae a las reglas.
Una negativa o un plan inválido se reintentan una vez con el error como feedback, y después
también se cae a las reglas.

**Estado.** Los tests usan un cliente falso. Todavía **no se probó contra la API real**: en
este equipo no hay credencial. La medición con `pstudio eval --provider cloud` queda pendiente
de que haya una clave.

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
| **Segunda medición a ciegas:** set nuevo de otro agente (`holdout.toml`) | 40 | **90.0%** |
| Tras corregir 4 patrones más (alcance de "no cambies la saturación", "está pasada" + descriptores, "flatten/harsh", ancla en otra cláusula) | 151 | 100% |

En todas las etapas el 100% de los planes fue válido. Las dos mediciones a ciegas dan ~90%: es la mejor estimación de cómo le va a las reglas con
pedidos reales nuevos. El 100% es sobre casos ya vistos. Para volver a medir a ciegas hace
falta otro set de casos nuevos.

## Proveedor `local_llm` (#17)
Está en `engine/src/pstudio/prompting/local_llm.py`. Decisión y medición previa:
[ADR-0007](adr/0007-local-llm-runtime.md) y el
[spike #5](../engine/spikes/llm/RESULTS.md). Cómo instalar el runtime y el modelo:
[INSTALLATION.md](INSTALLATION.md#llm-local-opcional-proveedor-local_llm).

**Configuración** (variables de entorno o argumentos de `LocalLLMProvider`)

| Variable | Para qué |
|---|---|
| `PSTUDIO_LLAMA_SERVER` | ruta a `llama-server.exe` (llama.cpp, build Vulkan) |
| `PSTUDIO_LLM_MODEL` | ruta al `.gguf` (Qwen3-8B Q4_K_M) |
| `PSTUDIO_LLM_URL` | en lugar de las dos anteriores: un llama-server que ya está corriendo. Solo se aceptan direcciones de este equipo (`127.0.0.1`, `localhost`, `::1`) |
| `PSTUDIO_LLM_CTX` | contexto reservado (por defecto 4096) |
| `PSTUDIO_LLM_NGL` | capas en la GPU (por defecto 99 = todas; 0 = solo CPU, ~30 s por plan) |

Sin configuración, o con una ruta que no existe, el proveedor no está disponible
(`ProviderUnavailable`, con un mensaje que dice qué falta). `pstudio plan --provider auto` sigue
entonces con las reglas, y `pstudio eval --provider local_llm` termina con código 2.

**Qué hace**
- **Servidor.** Lanza `llama-server` como proceso hijo la primera vez que hace falta, en
  `127.0.0.1` y un puerto libre (nunca `0.0.0.0`). Flags: `-ngl 99 -c 4096 -np 1 --jinja
  -fa off --no-webui`. Espera `/health` y manda un pedido de calentamiento que deja el prompt
  de sistema en la caché del servidor. Después reutiliza el mismo proceso para todos los
  pedidos. Lo detiene `close()`, el `with` o el fin del proceso de Python (`atexit`). La salida
  del servidor va a un log temporal (`%TEMP%\pstudio-llama-server-*.log`), no a la consola.
- **Salida restringida.** Cada pedido va a `/v1/chat/completions` con `response_format:
  json_schema`, `temperature: 0`, `chat_template_kwargs: {enable_thinking: false}` (Qwen3 sin
  `<think>`) y `max_tokens: 640`. El esquema de la gramática (`grammar_schema()`) se **deriva**
  del EditPlan de Pydantic; no hay una segunda copia del catálogo. Cambios respecto del
  esquema de producción:
  - `op` va primero en cada op. En las ops que heredan `amount`, Pydantic pone `amount` antes
    que `op`, y la gramática obligaba al modelo a escribir el valor antes de elegir la op.
    Con eso casi nunca elegía `contrast`, `saturation`, etc.: "blanco y negro" salía como
    `white_balance` (bajó de 70% a 45% correcto en los 20 casos del spike).
  - Todos los campos son obligatorios (los opcionales se escriben `null`). Con campos
    opcionales el modelo omitía parámetros (`resize` sin tamaño, `exposure` sin `ev`) o el
    plan entero. La excepción es `crop.rect`: si se exige, el modelo completa `aspect_ratio`
    **y** `rect` a la vez, y eso es inválido.
  - Como máximo 8 ops (sin tope, a temperatura 0 el modelo repite ops en bucle) y topes de
    largo para el texto libre (explicación 300 caracteres, cada campo de `unsupported` 200).
  - Solo las ops implementadas en este equipo. Sin `schema_version`, `asset` ni
    `source_prompt`, que completa `validate`.

  La gramática fija la forma. Lo que no puede expresar (unicidad de ops, rangos de los float,
  `crop` con exactamente uno de `aspect_ratio` o `rect`) lo valida `make_plan`, como con
  cualquier proveedor.
- **Prompt de sistema** (`system_prompt()`), en español:
  - El catálogo se genera del esquema: nombres, rangos, enums y las descripciones de los
    campos.
  - Una guía escrita a mano (`GUIDE`) dice qué op usar para qué y con qué signo. Un test
    verifica que toda op que nombra exista.
  - Dice explícitamente que el pedido y los descriptores son **datos**, no instrucciones.
  - Mide ~1600 tokens. Por eso el contexto es de 4096 y no de 2048 como en el spike: con 2048
    no entraban un plan largo ni el reintento. Medido, 4096 genera igual de rápido (36.5
    contra 37.0 tok/s).
- **Reintento.** Si `make_plan` rechaza la respuesta, el segundo pedido lleva la respuesta
  anterior y el error de validación. Una respuesta cortada por `max_tokens` cuenta como intento
  fallido y no se reenvía. Un error HTTP del servidor (p. ej. contexto excedido) cuenta como
  intento fallido. Si el servidor no arranca, se cae o no responde, el proveedor no está
  disponible: no se reintenta y el pipeline usa las reglas.
- Devuelve el texto crudo; la validación es la de siempre (`make_plan`).

**Resultados medidos** (2026-11-17; RX 6600 XT por Vulkan, Ryzen 5 3600, llama.cpp b12359,
Qwen3-8B Q4_K_M; `pstudio eval --provider local_llm` sobre los 151 casos de `evals/prompts`,
sin respaldo de reglas)

| Prompt de sistema | Casos | Válido 1º intento | Válido | **Correcto** | Mediana | p90 | Máx | > 8 s |
|---|---|---|---|---|---|---|---|---|
| Spike #5 (prompt v1, esquema reducido del spike) | 20 | 90% | 100% | 75% | 4.1 s | 9.3 s | 15.5 s | 3/20 |
| v1 (primera versión del proveedor) | 151 | 97.4% | 99.3% | 85.4% | 3.6 s | 7.8 s | 18.4 s | 15/151 |
| **v3 (la que quedó)** | 151 | **96.0%** | **99.3%** | **88.1%** | **3.5 s** | 9.6 s | 18.5 s | 21/151 |
| v3, solo los 20 casos del spike | 20 | 100% | 100% | 80% | 3.6 s | 9.5 s | 11.4 s | 4/20 |
| v3, solo `holdout.toml` | 40 | 97.5% | 97.5% | 87.5% | 3.2 s | 7.6 s | 16.9 s | 4/40 |

- **Arranque en frío:** 6–13 s hasta el primer plan. Incluye lanzar el servidor, cargar el
  modelo en la GPU (~3.5 s con el archivo en la caché de disco) y procesar una vez el prompt
  de sistema. Después, cada pedido procesa solo sus ~60 tokens nuevos.
- **Recursos:** ~5.3 GiB de VRAM dedicada (contador de Windows por proceso, ctx 4096) y
  ~37 tok/s de generación. El servidor escucha solo en `127.0.0.1`.
- **Latencia:** la mediana está dentro del objetivo (< 8 s), pero el 14% de los pedidos lo
  supera. Son los planes largos y los 6 pedidos que necesitaron reintento: cada reintento
  duplica el tiempo.
- **Iteraciones del prompt.** Las mediciones intermedias usaron los 20 casos del spike.
  - **Gramática (no prompt):** con el esquema de producción tal cual, el modelo devolvía planes
    vacíos o solo con `clarification`. Al exigir todos los campos y poner `op` primero, la
    validez llegó al 100% en esos casos, y la corrección pasó de 45% a 70% con el mismo prompt
    del spike.
  - **v1:** catálogo generado del esquema más la guía de uso. Dio 85% en los 20 casos y 85.4%
    en los 151, contra 70% del prompt del spike con la misma gramática.
  - **v2:** reglas más duras contra las ops "de regalo". Dio 80% en los 20 casos y se descartó.
  - **v3:** se escribió mirando solo las fallas de v1 en `es`, `en` y el spike, sin ver
    `holdout.toml`. Agrega tres cosas:
    - el signo como efecto en la foto, con el sentido de `temperature_shift`, `tint_shift`,
      `blacks` y `vignette`, y "para corregir una dominante, el lado opuesto";
    - los metadatos de `export` ("sin GPS" = `strip_gps`);
    - preguntar si falta un dato imprescindible.

    Mejoró de 85.4% a 88.1% en total y de 82.5% a 87.5% en `holdout`. Es una diferencia de
    2 a 4 casos, cerca del ruido, y empeoró un poco la cola de latencia.
- **Fallas que quedan** (18 de 151):
  - **Ops agregadas sin que nadie las pida:** en pedidos que son solo de export ("para la web
    sin ubicación") o imposibles ("agregá a mi hermana"), el modelo llena `operations` hasta
    el tope de 8.
  - **Signos de color invertidos:** "más fría" sale con `temperature_shift` +50.
  - **Historia de Instagram como 4:5** en lugar de 9:16, como en el spike.
  - **No pregunta** cuando falta la medida ("cambiale el tamaño").
  - **`sharpen` junto a `denoise`.**
  - **Pedidos imposibles resueltos con ops** en lugar de `unsupported` (cielo, desenfocar el
    fondo).

  Los pedidos de significado fijo los resuelve mejor `rules` (100% en estos mismos casos, ya
  vistos). El híbrido reglas + LLM que propone el ADR-0007 sigue siendo el paso siguiente.
- **Limitaciones:**
  - Si el proceso de Python muere de golpe (sin `atexit`), el servidor puede quedar
    corriendo. En Windows no se usa todavía un Job Object que lo mate junto con el padre.
  - Las mediciones son de una sola máquina y un solo modelo.
  - El verificador de corrección es por reglas: mide lo que pide cada caso, no la calidad
    visual.

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
