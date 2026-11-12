# ADR-0004 — Licencia MIT y FFmpeg LGPL

- **Estado:** Propuesto (cambiable mientras haya un único autor)
- **Fecha:** 2026-11-12

## Decisión
Código del proyecto bajo MIT. Para distribución se usa un build LGPL de FFmpeg (sin
x264/x265, enlazado como proceso externo) y encoders AMF/OpenH264. Toda dependencia y
modelo registra su licencia antes de integrarse.

## Alternativas
GPL-3.0 (permitiría x264 y MLT, pero obliga a todo derivado a ser GPL); Apache-2.0 (similar a MIT con cláusula de patentes).
