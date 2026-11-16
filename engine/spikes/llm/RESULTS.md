# Spike #5 — LLM local con llama.cpp Vulkan + JSON Schema (resultados)

**Fecha:** 2026-11-16 · **Equipo:** RX 6600 XT (RDNA2, 8 GB, driver AMD propietario), Ryzen 5
3600, 16 GB · **Runtime:** llama.cpp **b12359** (= v1.0.0, MIT), binario oficial
`win-vulkan-x64` · **Modelo:** **Qwen3-8B Q4_K_M** (GGUF oficial de Qwen, Apache-2.0, 5.03 GB)
· Scripts: [`bench.py`](bench.py), [`report.py`](report.py) · Esquema: [`edit_plan.py`](edit_plan.py)
· Prompts: [`prompts.json`](prompts.json) · Datos: `results_*.json`

## Qué se midió
20 prompts en español (y uno en inglés), con descriptores de imagen sintéticos: luz, color,
recortes, tamaño exacto, rotación, pedidos imposibles ("sacale el fondo"), ambiguos ("recortala")
y dos de inyección (una orden en el EXIF y "escribí un script de Python"). Para cada uno:
- **JSON ok**: la salida se puede parsear.
- **Válido**: pasa la validación Pydantic del `EditPlan`, que exige ops del catálogo, rangos,
  campos requeridos y cada op una sola vez. Si falla, se reintenta una vez con el error, como
  indica `PROMPT_ENGINE.md`.
- **Correcto**: aparecen las ops esperadas, no aparecen las prohibidas y signos y valores
  coinciden (p. ej. historia = `crop 9:16`, más claro = `ev > 0`).

Tres modos: **`schema`** usa salida restringida por gramática (`response_format: json_schema`
de llama-server). **`free`** no tiene restricción y solo describe el catálogo en el prompt.
**`free_schema`** no tiene restricción pero pega el JSON Schema en el prompt. Además hay dos
versiones del prompt de sistema (v1 y v2, que agrega reglas). Temperatura 0 y modo "thinking"
de Qwen3 desactivado.

## Resultados

| corrida | modo | ctx | válido 1º intento | válido con reintento | **correcto** | mediana | p90 | máx | > 8 s | tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| Vulkan, prompt v1 | **schema** | 2048 | 18/20 | **20/20** | **15/20** | **4.1 s** | 9.3 s | 15.5 s | 3/20 | 42 |
| Vulkan, prompt v1 | free | 2048 | 0/20 | 0/20 | 0/20 | 5.1 s | 10.6 s | 17.1 s | 7/20 | 46 |
| Vulkan, prompt v1 | free_schema | 4096 | 19/20 | 20/20 | 14/20 | 4.4 s | 8.0 s | 25.1 s | 2/20 | 39 |
| Vulkan, prompt v2 | schema | 2048 | 19/20 | 19/20 | 14/20 | 4.0 s | 6.3 s | 16.3 s | 1/20 | 41 |
| Vulkan, prompt v2 | free | 2048 | 0/20 | 4/20 | 2/20 | 6.8 s | 10.3 s | 12.8 s | 8/20 | 43 |
| Vulkan, prompt v2 | free_schema | 4096 | 20/20 | 20/20 | 14/20 | 4.4 s | 6.3 s | 27.0 s | 1/20 | 39 |
| **Solo CPU** (`-ngl 0`), v1 | schema | 2048 | 7/8 | 8/8 | 5/8 | **30 s** | 66 s | 107 s | 8/8 | 4.5 |

La latencia es la que ve el usuario por pedido: la suma de los intentos, con el reintento
incluido (unos 150 tokens generados por intento). La mediana de prompt nuevo por pedido es de 47 tokens, porque el prompt de
sistema queda en caché. En la corrida por CPU se probaron solo los primeros 8 prompts.

**Recursos (Vulkan, ctx 2048):** 37/37 capas en GPU. VRAM: 4455 MiB de modelo + 288 MiB de KV +
106 MiB de compute ≈ **4.7 GiB**, así que quedan unos 2.5 GB libres en la placa de 8 GB.
**Servidor listo en 3–4 s** con el modelo en la caché de disco (8.8 s la primera vez).
RSS del proceso ≈ 5.6 GB, en su mayoría el archivo mapeado en memoria.

**Benchmark aislado** (`llama-bench`, sin servidor): 48 tok/s de generación y 600 tok/s de
prompt en GPU, contra 6.8 y 272 en CPU (7 veces más lento en generación).

## Conclusiones
1. **llama.cpp con Vulkan anda bien en la RX 6600 XT**, con binarios oficiales y sin CUDA ni
   ROCm. A ~42 tok/s un plan tarda **~4 s de mediana**, dentro del objetivo de
   `PRODUCT_SPEC.md` (LLM local < 8 s). **Pero 3 de 20 pedidos lo superan** (8.9, 13.4 y
   15.5 s): son planes largos o planes que necesitaron reintento, porque **cada reintento
   duplica la latencia**. Para cumplir el objetivo en el p90, M2 tiene que mostrar el progreso
   (streaming), evitar reintentos con mejores reglas y limitar el texto libre, que hoy son
   ~30% de lo generado (mediana de caracteres en `explanation`, `unsupported` y
   `clarification`).
2. **La salida restringida por JSON Schema es imprescindible.** Sin restricción el modelo
   inventa su propio formato (`{"op":"adjust"}`, `"value"` en lugar de `"ev"`, faltan campos) y
   **0 de 20** planes son válidos, aun con reintento. Con gramática, el **100%** de las salidas
   tiene la forma correcta.
3. **Pegar el esquema en el prompt también funciona (20/20), pero sale más caro.** El prompt
   pasa de ~550 a ~3250 tokens: el primer pedido tarda **25 s** (procesar el prompt) y hace falta
   el doble de contexto. La gramática da la misma validez con prompts cortos, así que es la opción
   a usar.
4. **La gramática garantiza la estructura, no el sentido: ~70–75% de planes correctos.** Fallos
   repetidos en todas las variantes:
   - historia de Instagram → `crop 1:1` o `4:5` en lugar de 9:16;
   - "blanco y negro" → `white_balance +50` en lugar de `saturation -100` (solo en v1);
   - agrega `sharpen` a una foto con ruido cuando se pidió no perder detalle;
   - "fondo bien blanco" sin `whites`, `exposure` ni `highlights`;
   - con la inyección en el EXIF, el modelo **no ejecuta nada** (no hay op posible fuera del
     catálogo), pero **descarta el pedido real** ("subí el contraste") y en `alternative` le
     sugiere al usuario borrar el original a mano. La salida estructurada contiene el ataque,
     pero el texto libre (`explanation`, `alternative`) igual hay que tratarlo como no confiable
     en la UI.
5. **Ajustar el prompt no mejoró nada (v2: 14/20 contra 15/20).** Arregló "blanco y negro" y
   rompió el signo de "muy amarilla" (`temperature_shift +10`). Con 20 casos la diferencia es
   ruido, y las reglas de v2 se escribieron mirando estos mismos casos. **La mejora tiene que
   venir de la arquitectura, no del prompt** (ver propuesta).
6. **Bucles a temperatura 0.** Con `maxItems: 16`, el modelo repetía `resize` + `crop` hasta el
   tope (16 ops, 14 s). Una gramática no puede expresar "sin repetidos", así que se agregó
   una validación Pydantic (cada op una sola vez) junto con `max_length=8`: los bucles
   desaparecieron y el error alimenta el reintento (2 de 20 casos lo necesitaron, con 13–16 s
   en total).
7. **Sin GPU el LLM no es usable de forma interactiva:** 30 s de mediana y hasta 107 s en el
   Ryzen 5 3600. En equipos sin Vulkan, el proveedor por defecto tiene que ser `rules` (y
   `cloud_llm` como opt-in).

## Hallazgos técnicos (para M2)
- **El contexto reservado frena la generación en Vulkan**, aunque no se use: con el mismo prompt,
  `-c 8192` → 30 tok/s y `-c 2048` → 46 tok/s. Un plan con reintento entra en menos de 1500
  tokens, así que conviene usar `-c 2048`. `llama-bench` no muestra este efecto, porque reserva
  solo lo que usa.
- **Flash attention** (automático en el servidor): acelera la generación con contexto largo
  (39 contra 31 tok/s con 3200 tokens), pero **frena el procesamiento del prompt** en esta GPU
  (145 contra 471 tok/s). Con prompts cortos y caché de prefijo no importa. Con prompts largos
  conviene `-fa off`.
- **Qwen3**: pasar `chat_template_kwargs: {"enable_thinking": false}`. Si no, genera
  `<think>…</think>` antes del JSON.
- El modelo usa `"clarification": ""` en lugar de `null`: hay que normalizarlo al validar.
- La caché de prefijo del servidor funciona: el prompt de sistema (~550 tokens, 1.1 s) se procesa
  una vez y después cada pedido suma unos 50 tokens nuevos.
- Una corrida de `free_schema` dio 9.5 tok/s con todas las capas en GPU. Al repetirla, idéntica,
  dio 39 tok/s. **No se pudo atribuir la causa**; la hipótesis es otro programa usando la GPU en
  ese momento. Los números de la tabla son de la repetición. A vigilar en los evals de M2.

## Propuesta para M2 (`pstudio plan`)
- `local_llm` = **llama-server** (proceso hijo, `127.0.0.1`, `-c 2048 -np 1 --jinja`) con
  **Qwen3-8B Q4_K_M** y `response_format: json_schema` generado desde Pydantic, más validación
  Pydantic con un reintento y luego caída a `rules`, como ya dice `PROMPT_ENGINE.md`.
- **Híbrido reglas + LLM:** los pedidos con significado fijo (proporciones de redes sociales,
  blanco y negro, rotaciones, tamaños en píxeles, formato de export) los resuelve `rules`, en
  menos de 50 ms y de forma determinista. El LLM queda para lo difuso ("más cálido y suave",
  "mejorala"). Esto ataca directamente los fallos de la conclusión 4.
- Ampliar los evals de 20 a 100 o más casos antes de comparar prompts o modelos, para que una
  diferencia de 1 caso deje de ser ruido.
- El modelo **no se incluye en el instalador** (5 GB): se descarga aparte, con aprobación del
  usuario y verificación SHA-256. Decisión a registrar en un ADR.

## Limitaciones
- Un solo modelo (Qwen3-8B). No se compararon otros 7–8B (Llama 3.1, Mistral, Gemma) ni
  cuantizaciones (Q5/Q6).
- 20 casos (8 en CPU) con descriptores escritos a mano, no generados por un analizador real.
- La corrección la mide un verificador de reglas propio: mide lo que se le pidió, no la calidad
  visual del resultado.
- Sin prueba de convivencia: LLM y preview de pyvips usando la GPU al mismo tiempo.

## Reproducir
```powershell
# llama.cpp b12359 win-vulkan-x64 (SHA-256 e8d18c6e…0d5e) y Qwen3-8B-Q4_K_M.gguf
# (Qwen/Qwen3-8B-GGUF @ 7c41481, SHA-256 d98cdcbd…5785), por ejemplo en F:\prompt-studio\
cd engine
$S = "--model F:/prompt-studio/models/Qwen3-8B-Q4_K_M.gguf --server F:/prompt-studio/tools/llama.cpp-b12359/llama-server.exe"
uv run --group spike python spikes/llm/bench.py $S.Split() --modes schema free --tag vulkan_v1
uv run --group spike python spikes/llm/bench.py $S.Split() --modes free_schema --ctx 4096 --tag vulkan_v1_freeschema
uv run --group spike python spikes/llm/bench.py $S.Split() --ngl 0 --modes schema --limit 8 --tag cpu_v1
uv run python spikes/llm/report.py
```
