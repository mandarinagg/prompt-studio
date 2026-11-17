# Registro de modelos de IA

Ningún modelo se integra sin una fila completa y verificada aquí. Licencias a **confirmar en la
fuente oficial** antes de integrar.

| Modelo | Uso | Licencia | Tamaño | VRAM/RAM | Backend | Local/Nube | Estado |
|---|---|---|---|---|---|---|---|
| **Qwen3-8B Q4_K_M** (GGUF oficial `Qwen/Qwen3-8B-GGUF`, commit `7c41481`) | Plan desde prompt | **Apache-2.0** (verificado en LICENSE y model card, 2026-11-16) | 5.03 GB (SHA-256 `d98cdcbd…5785`) | ~5.3 GiB VRAM con ctx 4096 (medido en #17; 4.7 GiB con ctx 2048 en el spike) | llama.cpp b12359 (v1.0.0, MIT) Vulkan | Local | Integrado: proveedor `local_llm` (#17); no viaja en el instalador |
| Whisper (small/medium) | Subtítulos | MIT (verificar) | 0.5–1.5 GB | 2–5 GB | whisper.cpp Vulkan | Local | M6 |
| Real-ESRGAN | Upscaling | BSD-3 (verificar) | ~65 MB | 2 GB | ncnn-vulkan | Local | M6 |
| BiRefNet / RMBG | Quitar fondo | verificar (RMBG tiene restricciones) | 0.2–1 GB | 2–4 GB | ONNX DirectML | Local | M6 |
| SAM 2 | Selección de sujeto | Apache-2.0 (verificar) | 0.2–0.9 GB | 4 GB | ONNX DirectML | Local | M7 |
| Claude (API) | Plan desde prompt | Términos comerciales | — | — | HTTPS | **Nube, opt-in, solo texto** | M2 |
