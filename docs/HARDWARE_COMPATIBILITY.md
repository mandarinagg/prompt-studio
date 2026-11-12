# Compatibilidad de hardware

## Equipo de desarrollo (verificado 2026-11-12)
| Componente | Valor | Implicancia |
|---|---|---|
| OS | Windows 11 Pro (26200) | Windows es plataforma primaria |
| CPU | AMD Ryzen 5 3600, 6c/12t, AVX2 | Pipeline CPU viable; paralelizar por tiles |
| RAM | 16 GB | Limitar caché en RAM (~2 GB); modelos IA de a uno |
| GPU | AMD Radeon RX 6600 XT (RDNA2, 8 GB VRAM) | **Sin CUDA**. Vulkan, DirectML, AMF |
| Disco C: | 56 GB libres | Ajustado: caché y modelos en ruta configurable |
| Disco F: | 47 GB libres | Candidato para `models/` y `cache/` |

## Herramientas (estado 2026-11-12)
| Herramienta | Estado |
|---|---|
| git, gh | Instalados |
| Node 26 / npm 11 / pnpm 10 | Instalados |
| Python 3.15 | Instalado, **demasiado nuevo** para wheels de ML → usar 3.12 vía `uv` |
| Rust / cargo | **Falta** (requerido por Tauri) |
| FFmpeg | **Falta** |

## Backends de aceleración en esta GPU
| Uso | Backend recomendado | Notas |
|---|---|---|
| Encode video | FFmpeg `h264_amf`, `hevc_amf` | RDNA2 **no codifica AV1**; decodifica AV1 sí |
| LLM local | llama.cpp / Ollama con **Vulkan** | 7–8B Q4 ≈ 5 GB VRAM |
| STT | whisper.cpp con Vulkan | Modelos small/medium |
| Upscaling | Real-ESRGAN ncnn-vulkan | |
| Segmentación / ONNX | ONNX Runtime + DirectML | Verificar estado de soporte vigente de DirectML/WinML |
| ROCm (HIP) en Windows | No recomendado para v0.x | Soporte parcial; reevaluar más adelante |

## Perfiles en la app
- **Compatible:** CPU + herramientas clásicas (siempre disponible).
- **Acelerado:** encode AMF / ops en GPU si están verificadas.
- **IA local:** solo modelos probados con esta memoria y backend.
- **IA externa:** opt-in, con aviso de qué se transfiere.

Ningún modelo grande se descarga automáticamente.
