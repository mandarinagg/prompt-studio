# ADR-0007 — LLM local: llama-server + Qwen3-8B con salida restringida por JSON Schema

- **Estado:** Aceptado (2026-11-16)
- **Fecha:** 2026-11-16
- **Evidencia:** spike #5, [`engine/spikes/llm/RESULTS.md`](../../engine/spikes/llm/RESULTS.md)
- **Concreta:** ADR-0003 (proveedores de plan), que dejaba abierto "llama.cpp/Ollama".

## Contexto
El proveedor `local_llm` tiene que convertir un prompt en un `EditPlan` válido, sin red, en
una RX 6600 XT (Vulkan, sin CUDA) y en menos de 8 s (`PRODUCT_SPEC.md` §7).

## Decisión
- **Runtime:** `llama-server` de llama.cpp (binario oficial `win-vulkan-x64`, MIT), lanzado por
  el engine como proceso hijo en `127.0.0.1`, con `-c 2048 -np 1 --jinja`. La versión se fija
  por tag de build y SHA-256.
- **Modelo por defecto:** Qwen3-8B Q4_K_M, GGUF oficial (`Qwen/Qwen3-8B-GGUF`, Apache-2.0,
  5.03 GB), con el modo thinking desactivado.
- **Salida:** siempre con `response_format: json_schema`, generado desde los modelos Pydantic
  (la fuente única). Después, validación Pydantic con reglas que la gramática no puede expresar
  (ops sin repetir, máximo de ops), un reintento con el error y, si vuelve a fallar, caída a
  `rules`.
- **Distribución:** el modelo **no** viaja en el instalador. Se descarga aparte, solo con
  aprobación explícita del usuario, a una carpeta configurable, y se verifica su SHA-256.
- **Perfil:** `local_llm` se ofrece solo si hay GPU Vulkan con ≥ 6 GB libres. En CPU tarda
  ~30 s por plan, así que en ese caso no se ofrece por defecto.

## Alternativas consideradas
- **Sin restricción de salida (solo prompt):** 0/20 planes válidos. Descartado.
- **Esquema pegado en el prompt, sin gramática:** 20/20 válidos, pero con un prompt 6 veces
  más largo y 25 s en el primer pedido. Descartado.
- **Ollama:** suma un servicio residente y su propio almacén de modelos, y su backend Vulkan
  no se probó. llama-server da control directo de versión, flags y gramática.
- **Otros modelos 7–8B** (Llama 3.1: licencia más restrictiva; Mistral, Gemma): no medidos.
  Quedan para la ampliación de evals de M2.

## Consecuencias
- Estructura del plan garantizada; la corrección semántica medida es de ~75% (15/20). Por eso
  M2 implementa un proveedor **híbrido**: `rules` resuelve los pedidos de significado fijo
  (proporciones, B/N, rotaciones, tamaños, formato) y el LLM los difusos.
- Hay que mantener un binario externo (~38 MB) y vigilar regresiones de rendimiento de Vulkan
  entre builds. Por ejemplo, el contexto reservado frena la generación (8192 → 30 tok/s,
  2048 → 46).
- El texto libre del LLM (`explanation`, `alternative`) se muestra como no confiable: no
  ejecuta nada, pero puede contener sugerencias equivocadas.

## Actualización (#17, 2026-11-17)
Al integrar el proveedor, el contexto pasó de `-c 2048` a `-c 4096`: el prompt de sistema con
el catálogo completo ocupa ~1600 tokens (el del spike, ~620) y con 2048 se cortaban los planes
largos y el reintento. Medido en la RX 6600 XT, 4096 genera igual de rápido que 2048 con este
prompt (36.5 contra 37.0 tok/s) y usa ~5.3 GiB de VRAM. Detalle y resultados en
[PROMPT_ENGINE.md](../PROMPT_ENGINE.md#proveedor-local_llm-17).

## Decisión al cerrar M2 (2026-11-17)
Medido con `pstudio eval` sobre los mismos casos, el LLM local integrado (#17) da 99.3% de
planes válidos y 88.1% correctos (87.5% en el set ciego `holdout.toml`), con mediana de 3.5 s.
Las reglas (#15) dan ~90% a ciegas, medido dos veces con sets independientes, en ~1.5 ms. Hoy
el LLM no suma precisión. Por eso:
- `--provider auto` usa las reglas;
- el LLM queda disponible y opt-in (`--provider local_llm`);
- el híbrido propuesto arriba se mide en #53 antes de activarlo, con un set ciego nuevo.

El runtime elegido (llama-server + Qwen3-8B, Vulkan) no cambia.
