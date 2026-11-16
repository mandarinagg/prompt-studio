# Spike #3 — Sidecar Python dentro de Tauri 2 (resultados)

**Fecha:** 2026-11-16 · **Equipo:** Ryzen 5 3600, 16 GB, Windows 11 25H2 (26200.9974)
**Decisiones:** [ADR-0001](../../../docs/adr/0001-desktop-stack.md) (aceptado),
[ADR-0006](../../../docs/adr/0006-sidecar-packaging.md) (empaquetado del sidecar)

## Qué se construyó
- `pstudio rpc`: servidor JSON-RPC 2.0 sobre stdio (`engine/src/pstudio/rpc.py`, con 13 tests).
  Métodos: `ping`, `engine.version`, `image.info`.
- App Tauri 2 + React mínima (`app/`). Rust lanza el engine sin ventana de consola, empareja las
  respuestas por `id`, nunca bloquea el hilo de UI y apaga el engine cerrando stdin.
- Tres formas de empaquetar el engine, medidas con
  [`measure_startup.py`](measure_startup.py) y [`measure_app.py`](measure_app.py).

## 1. Empaquetado del engine (proceso aislado, mediana de 10)

| variante | tamaño | 1ª respuesta | + libvips cargado | + leer foto 24 MP | 1ª ejecución |
|---|---|---|---|---|---|
| dev (`python -m pstudio`) | — | 95 ms | 125 ms | 127 ms | 136 ms |
| PyInstaller onedir | 82 MB | 234 ms | 250 ms | 253 ms | 1720 ms |
| PyInstaller onefile | 35 MB | 1119 ms | 1368 ms | 1371 ms | 3026 ms |
| **Python embebible (python.org)** | **81 MB** | **79 ms** | **108 ms** | **110 ms** | **116 ms** |

**Smart App Control (SAC) bloqueó el exe de PyInstaller** (`WinError 4551`; evento
CodeIntegrity 3077 a las 00:58:48). Minutos después, el mismo archivo se ejecutó: la decisión
de SAC depende de una consulta de reputación en la nube y no es determinista. En cambio, el
`python.exe` y el `python312.dll` del paquete embebible tienen **firma válida de la Python
Software Foundation** y no se bloquearon nunca.

## 2. App completa (Tauri release + engine embebido)

| | valor |
|---|---|
| `prompt-studio.exe` | 4.2 MB |
| **Instalador NSIS** (incluye engine + libvips) | **23.7 MB** |
| Tamaño instalado | 85 MB |
| Instalación silenciosa (`/S`, por usuario, sin admin) | 9 s |
| Primer build release (desde cero) | 7 min; `target/` ocupa 1.4 GB |

Arranque, mediana de 15 corridas (desde que se lanza el proceso):

| | build local (`target/release`) | app instalada |
|---|---|---|
| Engine lanzado | 459 ms | 712 ms |
| **UI lista** (WebView2 + React montado) | **522 ms** | **796 ms** |
| **Engine listo** (responde `ping`) | **578 ms** | **945 ms** |
| Proceso completo hasta cerrar | 690 ms | 1205 ms |

Objetivo de `PRODUCT_SPEC.md` §7, arranque de la app < 3 s: ✅ con margen.

- En una primera tanda hubo corridas de ~4.3 s justo después de compilar. Las tandas siguientes
  fueron estables (p90 ≤ 1.05 s). Hipótesis no verificada: Defender escaneando archivos nuevos.
- Al cerrar la app no quedan procesos `python.exe` huérfanos (verificado). La desinstalación
  silenciosa borra la carpeta y la entrada de "Agregar o quitar programas".
- Hoy el engine se lanza recién en `setup` (~450 ms). Lanzarlo antes, en paralelo con la
  creación del WebView, adelantaría el "engine listo" unos 400 ms. Queda para M3.

## 3. Hallazgo bloqueante para el desarrollo: SAC y Rust
Con SAC activado **no se puede compilar Tauri**: Cargo ejecuta los build scripts de las
dependencias (p. ej. `serde`) y SAC los bloquea (`os error 4551`). Un exe de Rust simple sin
build scripts sí corrió. Solución adoptada: el autor desactivó SAC en la máquina de desarrollo
(en 25H2 ≥ 26200.8116 se puede reactivar sin reinstalar).

**Consecuencia para el producto:** los usuarios con SAC activado van a necesitar un
**instalador firmado** con un certificado de confianza. Es un requisito para v0.1.

## Limitaciones del spike
- Python embebible **3.12.10**: la rama 3.12 ya solo recibe parches de seguridad, sin binarios
  oficiales (el último embebible es el 3.12.10; uv usa 3.12.16). Hay que decidir si se pasa a 3.14.
- Sin firma de código, sin actualizaciones automáticas y sin prueba en un equipo limpio sin WebView2.
- Un solo equipo.

## Reproducir
```powershell
cd engine
uv run python packaging/build_embed.py                 # runtime embebido -> engine/dist/embed
uv run python spikes/sidecar/measure_startup.py       # requiere también los builds de PyInstaller
cd ../app; pnpm install; pnpm tauri build              # requiere SAC desactivado
cd ../engine; uv run python spikes/sidecar/measure_app.py
```
