# Privacidad y seguridad

- Procesamiento local por defecto; el proveedor `cloud_llm` está apagado de fábrica.
- Al activar nube: aviso de **qué** se envía (texto del prompt + descriptores; nunca píxeles
  salvo consentimiento por operación) y a **quién**.
- El LLM solo produce operaciones de un catálogo cerrado; nunca se ejecuta Python, shell ni JS generado.
- Rutas normalizadas y validadas; el engine solo escribe en el proyecto y en la carpeta de export.
- Originales en solo lectura; hash al importar y verificación antes/después de exportar.
- Comunicación UI↔engine por stdio, sin abrir puertos.
- Modelos solo desde fuentes verificadas, con hash y licencia registrados; nunca descarga automática.
- Logs sin rutas completas ni contenido de prompts salvo modo debug explícito.
- **Repo público:** nunca commitear medios personales, claves de API ni `.env`.
