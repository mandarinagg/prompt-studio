# Registro de modelos de IA

Ningún modelo se integra sin una fila completa y verificada aquí. Licencias a **confirmar en la
fuente oficial** antes de integrar.

| Modelo | Uso | Licencia | Tamaño | VRAM/RAM | Backend | Local/Nube | Estado |
|---|---|---|---|---|---|---|---|
| LLM 7–8B instruct Q4 (a elegir) | Plan desde prompt | por verificar | ~5 GB | ~6 GB VRAM | llama.cpp Vulkan | Local | Spike M0 |
| Whisper (small/medium) | Subtítulos | MIT (verificar) | 0.5–1.5 GB | 2–5 GB | whisper.cpp Vulkan | Local | M6 |
| Real-ESRGAN | Upscaling | BSD-3 (verificar) | ~65 MB | 2 GB | ncnn-vulkan | Local | M6 |
| BiRefNet / RMBG | Quitar fondo | verificar (RMBG tiene restricciones) | 0.2–1 GB | 2–4 GB | ONNX DirectML | Local | M6 |
| SAM 2 | Selección de sujeto | Apache-2.0 (verificar) | 0.2–0.9 GB | 4 GB | ONNX DirectML | Local | M7 |
| Claude (API) | Plan desde prompt | Términos comerciales | — | — | HTTPS | **Nube, opt-in, solo texto** | M2 |
