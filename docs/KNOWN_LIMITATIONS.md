# Limitaciones conocidas

- Sin CUDA en el equipo objetivo (AMD RX 6600 XT): la IA usa Vulkan/DirectML o CPU.
- Sin encode AV1 por hardware (RDNA2).
- 16 GB de RAM: un modelo de IA cargado a la vez.
- v0.1 no soporta RAW, HEIC, máscaras locales ni video.
- El proveedor de reglas solo entiende prompts simples; los complejos necesitan LLM.
- Los objetivos de rendimiento son hipótesis hasta cerrar M0.
