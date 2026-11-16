# Spike #4 — Encode por hardware AMD AMF vs software (resultados)

**Fecha:** 2026-11-16 · **Equipo:** RX 6600 XT (RDNA2, 8 GB), Ryzen 5 3600 · **FFmpeg:** n9.0.2 LGPL
(BtbN) · Script: [`amf_bench.py`](amf_bench.py) · Datos: [`results.json`](results.json)

## Material
Clip de referencia de **20 s, 1080p30, sin pérdida (FFV1 en NUT)**, armado con 4 fotos CC0 de
`tests/fixtures` con paneo/zoom: cielo nocturno con ruido de ISO alto, interior cálido,
contraluz y retrato con luz de escenario. Calidad medida con **libvmaf** (modelo vmaf_v0.6.1),
PSNR-Y y SSIM contra la referencia, cuadro a cuadro.

## Resultados

| Mbps objetivo | encoder | fps* | Mbps real | VMAF | VMAF mín | PSNR-Y | SSIM |
|---|---|---|---|---|---|---|---|
| 6 | h264_amf speed | 108 | 5.54 | 93.08 | 82.8 | 34.41 | 0.9916 |
| 6 | h264_amf balanced | 108 | 5.56 | 93.06 | 82.8 | 34.42 | 0.9916 |
| 6 | h264_amf quality | 111 | 5.56 | 93.09 | 82.8 | 34.44 | 0.9916 |
| 6 | hevc_amf speed | 111 | **7.21** | 95.42 | 82.8 | 35.54 | 0.9944 |
| 6 | hevc_amf quality | 110 | **6.94** | 94.97 | 82.1 | 35.57 | 0.9943 |
| 6 | av1_amf | ❌ no soportado por RDNA2 | | | | | |
| 6 | libopenh264 (CPU) | 73 | 5.55 | 93.19 | 83.5 | 39.96 | 0.9927 |
| 6 | libsvtav1 preset 8 (CPU) | 56 | 4.83 | **97.37** | **94.1** | 45.44 | 0.9991 |
| 12 | h264_amf speed | 116 | 11.37 | 95.03 | 87.5 | 35.30 | 0.9938 |
| 12 | h264_amf balanced | 110 | 11.39 | 95.04 | 87.5 | 35.31 | 0.9939 |
| 12 | h264_amf quality | 101 | 11.34 | 94.99 | 87.5 | 35.32 | 0.9939 |
| 12 | hevc_amf speed | 115 | 12.53 | 96.14 | 89.6 | 36.01 | 0.9949 |
| 12 | hevc_amf quality | 109 | 12.37 | 95.89 | 89.3 | 36.06 | 0.9949 |
| 12 | av1_amf | ❌ no soportado por RDNA2 | | | | | |
| 12 | libopenh264 (CPU) | 67 | 10.89 | 95.23 | 87.2 | 41.52 | 0.9947 |
| 12 | libsvtav1 preset 8 (CPU) | 58 | 9.12 | **97.76** | **94.7** | 46.50 | 0.9993 |

\* **Los fps de AMF en esta tabla están limitados por la lectura de la referencia**: decodificar
el FFV1 solo ya da 117 fps. Medido aparte, desde YUV crudo en memoria:

| encoder (6 Mbps, desde YUV crudo) | fps | × tiempo real |
|---|---|---|
| **h264_amf** | **293** | **9.8×** |
| **hevc_amf** | **304** | **10.1×** |
| libopenh264 (CPU) | 93 | 3.1× |

## Conclusiones
1. **AMF funciona en la RX 6600 XT** para H.264 y HEVC, a unas 10 veces el tiempo real en 1080p30.
   En un export real la velocidad la va a limitar el pipeline de efectos y la decodificación,
   no el encoder.
2. **Calidad de h264_amf ≈ OpenH264 por CPU al mismo bitrate** (VMAF 93.1 vs 93.2 a 6 Mbps;
   95.0 vs 95.2 a 12 Mbps), y AMF es 3 veces más rápido. OpenH264 da más PSNR, pero VMAF, que es
   la métrica perceptual, los iguala.
3. **Los presets de AMF (speed/balanced/quality) casi no cambian nada** en este contenido
   (±0.05 VMAF). Se aplican (generan archivos distintos), pero no compensa usar "quality".
4. **hevc_amf se pasa del bitrate objetivo** a 6 Mbps (7.2 en lugar de 6), así que parte de su
   ventaja de VMAF viene de usar más bits. A 12 Mbps lo respeta mejor.
5. **AV1 por hardware no existe en RDNA2** (confirmado: `av1_amf` no produce paquetes). Lo que
   sí existe es **SVT-AV1 por CPU (preset 8): la mejor calidad por bit con diferencia** (VMAF 97.4
   con 4.8 Mbps contra 93 de H.264 con 5.5 Mbps), a 1.9 veces el tiempo real. Sirve para un
   preset de "archivo chico / máxima calidad" a cambio de más tiempo de export.

## Propuesta para `EXPORT_PRESETS.md` (a decidir en M4)
| Preset | Encoder | Fallback sin AMF |
|---|---|---|
| Rápido / compatible (MP4 H.264) | `h264_amf -quality balanced` | `libopenh264` |
| Alta eficiencia (MP4 HEVC) | `hevc_amf` | — (ocultar el preset) |
| Archivo chico / máxima calidad (AV1) | `libsvtav1 -preset 8` | igual (es CPU) |

## Lecciones de medición (para los tests de M4)
- **Al comparar con VMAF, emparejar los cuadros en una base de tiempo común y entera**
  (`settb=1/30,setpts=N`). Con los timestamps originales o con `setpts=N/FRAME_RATE/TB` entre
  bases distintas (1/61440 vs 1/15360), libvmaf comparaba algunos cuadros contra su vecino: daba
  VMAF ~83 y mínimo ~31 **incluso casi sin pérdida**. Validación: una copia sin pérdida tiene
  que dar PSNR infinito en todos los cuadros.
- Guardar las referencias en NUT, no en MKV: MKV redondea los timestamps a 1 ms.
- Durante una decodificación apareció **una vez** un `slice CRC mismatch` en la referencia FFV1.
  No se reprodujo en 5 decodificaciones posteriores (hashes idénticos con y sin hilos). Fue un
  error transitorio; conviene vigilar si se repite (equipo sin RAM ECC).

## Limitaciones
- Contenido sintético (paneo/zoom sobre fotos), no video de cámara real con movimiento complejo.
- Solo 1080p30, 8 bits, un único equipo. Faltan 4K, 10 bits y HDR.
- No se probó la decodificación por hardware (D3D11VA) ni el encode con efectos en el pipeline.

## Reproducir
```powershell
uv run --no-project --python 3.12 tests/fixtures/fetch_fixtures.py   # desde la raíz
cd engine
uv run python spikes/video/amf_bench.py --bitrates 6 12              # ~10 min
```
