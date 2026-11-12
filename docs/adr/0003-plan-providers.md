# ADR-0003 — Proveedores de plan: reglas, LLM local, LLM nube opt-in

- **Estado:** Propuesto
- **Fecha:** 2026-11-12

## Decisión
Interfaz `PlanProvider` con tres implementaciones: `rules` (siempre disponible), `local_llm`
(llama.cpp/Ollama con Vulkan y salida restringida por JSON Schema), `cloud_llm` (opt-in,
solo texto: prompt + descriptores). Todas devuelven un `EditPlan` que pasa la misma validación.
El LLM emite valores relativos o `auto_*`; el motor resuelve valores finales con analizadores deterministas.

## Consecuencias
Funciona offline desde el día uno; la calidad de prompts se mide con `evals/` por proveedor.
