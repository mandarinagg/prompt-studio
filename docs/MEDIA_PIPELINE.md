# Pipeline de medios

## Foto
decode (pyvips; ICC → lineal float32) → ops en orden → encode (ICC de salida, EXIF según política).
- **Proxy:** lado largo 2048 px para preview; mismo código que export.
- **Caché:** clave = hash(asset, versión del motor, ops[0..i]); límite de tamaño configurable.
- **Lote:** cola de jobs, un worker por núcleo físico, cancelable.

## Video (M4)
Proxies (720p H.264 all-intra para scrubbing) → timeline OTIO → filtergraph FFmpeg → encode
(AMF H.264/HEVC o VP9 por software). Progreso parseando `-progress pipe:1`; cancelación matando el proceso.

> Elección final de librería de imagen pendiente del spike de M0.
