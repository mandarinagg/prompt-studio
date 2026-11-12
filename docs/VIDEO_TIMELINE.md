# Timeline de video (M4)

- **Modelo:** OpenTimelineIO (pistas, clips, gaps, transiciones, efectos). Permite intercambio
  con NLEs (DaVinci, Premiere) a futuro.
- **Render:** traducción OTIO → filtergraph FFmpeg (trim, concat, xfade, drawtext, afade, volume).
- **UI:** componente propio en React (pistas, zoom, playhead, snapping). Evaluar librerías de
  timeline existentes en un spike antes de M4 (licencia, mantenimiento, rendimiento).
- **Prioridad:** estabilidad de timeline y render antes de IA.
