# PROMPT STUDIO

## Editor profesional local de fotos y videos controlado mediante prompts

**Tipo:** Aplicación de escritorio y motor multimedia local\
**Modalidad:** Edición visual + operaciones reproducibles mediante
código\
**Interfaz:** Prompts, controles visuales y timeline\
**Procesamiento:** Local-first

## 1. Visión

Crear una herramienta que permita importar fotos y videos, describir
cambios en lenguaje natural, convertir esas instrucciones en operaciones
de edición reproducibles, previsualizar, ajustar, comparar versiones y
exportar.

No debe ser un simple wrapper de FFmpeg. Debe combinar: - Edición
visual. - Automatización mediante código. - Interpretación de prompts. -
Previsualización. - Parámetros editables. - Historial y reversión. -
Exportación de calidad.

Los archivos se procesan localmente por defecto. Ningún medio se envía a
la nube sin consentimiento explícito.

## 2. Objetivos

-   Edición fotográfica desde prompts.
-   Corrección de exposición, color, contraste y balance.
-   Recorte, redimensionamiento y formatos.
-   Máscaras y ajustes selectivos.
-   Eliminación/reemplazo de fondo cuando exista modelo local
    compatible.
-   Texto, títulos y subtítulos.
-   Cortar, unir y ordenar clips.
-   Transiciones y ajustes de audio.
-   Adaptar formatos para diferentes canales.
-   Exportar con perfiles configurables.
-   Guardar proyectos y operaciones editables.

## 3. Principios

1.  Local-first.
2.  Nunca sobrescribir originales.
3.  Edición no destructiva siempre que sea viable.
4.  Previsualizar antes de exportar.
5.  El prompt se convierte en plan estructurado, no en código
    arbitrario.
6.  Parámetros inspeccionables y editables.
7.  Informar uso de CPU/GPU/modelos.
8.  Funciones clásicas disponibles aunque no haya IA.
9.  No prometer funciones no probadas en el hardware objetivo.
10. Guardar proyectos reabribles.

## 4. Experiencia de usuario

### Espacio de trabajo

-   Biblioteca de medios.
-   Visor de imagen/video.
-   Panel de propiedades.
-   Campo de prompt.
-   Timeline de video.
-   Capas y máscaras cuando corresponda.
-   Historial de operaciones.
-   Comparación antes/después.
-   Cola de render.
-   Exportación.

Modos iniciales: Foto y Video. Proyecto mixto puede quedar para una fase
posterior.

### Flujo de prompt

Ejemplo: "Mejorá la iluminación, corregí el balance de blancos, reducí
el ruido y prepará una versión cuadrada para catálogo sin alterar el
producto".

1.  Analizar archivo y metadatos.
2.  Interpretar prompt.
3.  Generar plan estructurado.
4.  Validar operaciones disponibles.
5.  Mostrar cambios y parámetros.
6.  Generar preview.
7.  Permitir ajustes.
8.  Aplicar al proyecto no destructivamente.
9.  Exportar copia.

Si una operación requiere un modelo no instalado, informar y ofrecer
alternativa.

## 5. Plan de edición estructurado

El LLM produce un objeto validado, no código ejecutable. Ejemplo
conceptual:

``` json
{
  "asset": "image_001",
  "operations": [
    {"type": "white_balance", "temperature": 5200, "tint": 2},
    {"type": "denoise", "strength": 0.25},
    {"type": "crop", "aspect_ratio": "1:1", "anchor": "center"}
  ],
  "export": {"format": "webp", "quality": 90}
}
```

Los valores son ilustrativos. El esquema real debe ser versionado,
tipado y validado.

## 6. Módulos

### 6.1 Biblioteca

-   Importar imagen, video y audio.
-   Preview y metadatos.
-   Clasificación por proyecto.
-   Búsqueda y filtros.
-   Detección de medios faltantes.
-   Referencias a originales sin duplicarlos innecesariamente.

### 6.2 Fotografía

Funciones iniciales: - Exposición, brillo, contraste. - Altas luces y
sombras. - Temperatura, matiz, saturación y vibrancia. - Curvas/niveles
si el motor lo permite. - Crop, perspectiva y rotación. - Resize,
nitidez y denoise. - Viñeta. - Máscaras y correcciones locales. -
Conversión y exportación por lotes.

IA opcional: - Segmentación y eliminación de fondo. - Selección de
sujeto. - Inpainting/eliminación de objetos. - Upscaling y
restauración. - Extensión o generación de fondo.

Cada modelo debe declarar licencia, tamaño, memoria requerida, tiempo
estimado y si procesa localmente o en nube.

### 6.3 Video

Funciones iniciales: - Importar varios clips. - Cortar, recortar, unir y
reordenar. - Relación de aspecto, escala y posición. - Corrección básica
de color. - Transiciones. - Títulos y textos. - Subtítulos importados. -
Volumen y fades. - Extraer audio. - Renderizar y exportar.

Avanzadas: - STT local para subtítulos. - Tracking. - Máscaras. -
Eliminación de fondo. - Estabilización. - Detección de escenas. -
Reencuadre inteligente. - Clips destacados.

Priorizar estabilidad del timeline y render antes de añadir IA avanzada.

### 6.4 Motor de prompts

-   Detectar foto/video.
-   Identificar archivo objetivo.
-   Traducir instrucciones a operaciones conocidas.
-   Pedir aclaración ante ambigüedad relevante.
-   Explicar cambios antes de ejecutarlos.
-   Undo/redo y versiones.
-   Guardar el plan estructurado.

No ejecutar Python, shell, JavaScript ni código arbitrario producido por
un LLM. El modelo solo puede producir operaciones declarativas de un
catálogo cerrado.

### 6.5 Preview

-   Proxies de baja resolución para video.
-   Render temporal para foto.
-   Antes/después.
-   Indicador de calidad aproximada.
-   Reproducción.
-   Actualización al cambiar parámetros.
-   Cancelación.
-   Caché.

Una preview de baja resolución nunca debe presentarse como export final.

### 6.6 Timeline y capas

Video: pistas, clips, duración, transiciones, overlays, controles de
reproducción, zoom, navegación y undo/redo.

Foto: capas de ajuste, máscaras, texto, orden, visibilidad y parámetros
editables.

### 6.7 Exportación

Perfiles configurables: original, alta calidad, web, catálogo, vertical,
cuadrado y horizontal. Documentar resolución, codec, bitrate, formato,
perfil de color y audio. No fijar presets como estándar sin probarlos.
Exportar copias.

## 7. Arquitectura técnica propuesta

Seleccionar tras pruebas: - Desktop: Tauri + React + TypeScript o
Electron si el timeline/compatibilidad lo justifica. - Video: FFmpeg. -
Imagen: OpenCV, Pillow y/o libvips. - Workers de procesamiento
desacoplados. - Proyectos: JSON versionado + SQLite para
índice/metadatos. - Preview: proxies y caché local. - IA: adaptadores
para modelos locales compatibles. - Aceleración: detectar backend real;
no asumir CUDA. - Job manager local con cancelación y progreso.

Evaluar librerías profesionales de timeline antes de construir un editor
completo desde cero. Revisar licencias, mantenimiento y compatibilidad.

## 8. Diagnóstico de hardware

En primer inicio, comprobar: - Sistema operativo. - CPU. - RAM
disponible. - GPU y backend de aceleración. - Espacio libre. - FFmpeg y
codecs. - Compatibilidad de modelos.

El usuario mencionó anteriormente Ryzen 5 3600, RX 6600 XT y 16 GB RAM,
pero verificar el equipo actual antes de decidir.

Perfiles: - Compatible: CPU y herramientas clásicas. - Acelerado: GPU si
backend compatible. - IA local: modelos probados para memoria y
backend. - IA externa: opt-in, con aviso de transferencia.

No descargar modelos grandes automáticamente.

## 9. Seguridad y privacidad

-   Procesamiento local por defecto.
-   No transferir medios sin consentimiento.
-   No ejecutar código arbitrario de IA.
-   Validar rutas y prevenir path traversal.
-   Limitar directorios de trabajo.
-   No sobrescribir originales.
-   Descargar modelos desde fuentes verificadas.
-   Revisar licencias.
-   No instalar plugins sin confirmación.
-   Registrar errores sin contenido privado innecesario.

## 10. Formato de proyecto

Guardar: - Versión de esquema. - Referencias a medios y rutas. -
Metadatos. - Operaciones. - Capas y timeline. - Parámetros. -
Referencias a modelos. - Presets. - Historial. - Estado de render.

Debe reabrirse y advertir si falta un medio o modelo. No incrustar
videos completos por defecto.

## 11. Roadmap

**Fase 0:** diagnóstico hardware, stack, FFmpeg, motor de imagen,
licencias y formatos.\
**Fase 1:** editor fotográfico base, ajustes, crop, resize, historial y
export.\
**Fase 2:** prompts de foto, catálogo de operaciones, plan validado,
preview y undo.\
**Fase 3:** video básico, timeline, cortes, unión, texto, audio y
render.\
**Fase 4:** prompts de video y aplicación al timeline.\
**Fase 5:** IA local: segmentación, upscaling, denoise y subtítulos
según hardware.\
**Fase 6:** máscaras avanzadas, tracking, color, batch y plantillas.

## 12. Criterios de aceptación del MVP

-   Funciona offline para edición clásica.
-   Importa formatos compatibles.
-   No modifica originales.
-   Ajustes básicos de foto.
-   Secuencia simple de video.
-   Prompts se traducen a operaciones estructuradas.
-   Usuario revisa plan antes de ejecutar.
-   Operaciones no soportadas se identifican.
-   Preview, progreso y cancelación.
-   Proyectos guardables y reabribles.
-   No ejecuta código arbitrario.
-   No envía medios a nube sin permiso.
-   Tests y documentación.

## 13. Prompt maestro para Claude Code

Actuá como arquitecto de software, ingeniero multimedia y especialista
en aplicaciones de edición profesional.

Vamos a construir PROMPT STUDIO: una aplicación de escritorio que edita
fotos y videos mediante prompts, con procesamiento local y operaciones
reproducibles.

Leé este documento completo. Tu primera tarea es investigar y
planificar, no programar inmediatamente.

1.  Inspeccioná el equipo actual: OS, CPU, RAM, GPU, aceleración y
    espacio.
2.  Evaluá FFmpeg y motores de imagen.
3.  Compará frameworks de escritorio y opciones de timeline.
4.  Investigá licencias y mantenimiento de dependencias.
5.  Diseñá arquitectura local-first.
6.  Definí catálogo inicial de operaciones.
7.  Diseñá el esquema estructurado del motor de prompts.
8.  Definí preview, caché, cola de render y cancelación.
9.  Proponé MVP, pruebas, riesgos y roadmap.

Restricciones: - No sobrescribir originales. - No ejecutar código
arbitrario generado por IA. - No enviar medios a nube sin
consentimiento. - No asumir CUDA. - No instalar modelos grandes sin
aprobación. - No afirmar que una función es profesional sin probarla con
material real.

Presentá diagnóstico y plan. Esperá aprobación antes de implementar.

## 14. Documentación que debe mantenerse

-   `README.md`
-   `docs/PRODUCT_SPEC.md`
-   `docs/ARCHITECTURE.md`
-   `docs/MEDIA_PIPELINE.md`
-   `docs/PROMPT_ENGINE.md`
-   `docs/EDIT_OPERATIONS.md`
-   `docs/VIDEO_TIMELINE.md`
-   `docs/AI_MODELS.md`
-   `docs/HARDWARE_COMPATIBILITY.md`
-   `docs/PRIVACY_AND_SECURITY.md`
-   `docs/EXPORT_PRESETS.md`
-   `docs/ROADMAP.md`
-   `docs/TESTING.md`
-   `docs/INSTALLATION.md`
-   `docs/KNOWN_LIMITATIONS.md`

**Regla final:** el prompt se traduce a una edición controlable,
verificable y reversible. La IA propone; el motor validado ejecuta.
