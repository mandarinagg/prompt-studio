# ADR-0006 — Empaquetado del sidecar: Python embebible oficial, no PyInstaller

- **Estado:** Propuesto
- **Fecha:** 2026-11-16
- **Evidencia:** spike #3, [`engine/spikes/sidecar/RESULTS.md`](../../engine/spikes/sidecar/RESULTS.md)
- **Complementa:** ADR-0002 (engine Python sidecar), que dejaba el empaquetado abierto
  ("PyInstaller/Nuitka → spike en M0").

## Contexto
La app Tauri debe incluir el engine Python y lanzarlo como proceso hijo. En el equipo objetivo
está activo Smart App Control (SAC), que bloquea ejecutables sin firma y sin reputación.

## Decisión
- El sidecar se distribuye como el **paquete embebible oficial de python.org** (`python.exe` y
  `pythonXY.dll` firmados por la PSF) más `lib/` con `pstudio` y sus dependencias instaladas
  desde wheels, sin bootloader propio. Lo arma `engine/packaging/build_embed.py`, que verifica
  el SHA-256 del zip.
- Viaja como **recurso** del bundle de Tauri (`engine/`). Rust lo lanza como
  `engine/python/python.exe -I -m pstudio rpc`.
- La ruta de imports la fija `pythonXY._pth`. `-I` aísla el proceso del `PYTHONPATH` y de los
  paquetes del Python del sistema.

## Motivos (medido)
| | PyInstaller onedir | PyInstaller onefile | **Embebible** |
|---|---|---|---|
| Tamaño | 82 MB | 35 MB | 81 MB |
| Engine listo (libvips cargado) | 250 ms | 1368 ms | **108 ms** |
| Bloqueado por SAC | **sí** (1ª vez) | no observado | no (binarios firmados) |

El bootloader de PyInstaller tiene mala reputación en antivirus porque lo usa mucho malware.
El embebible es además más simple de depurar: es el mismo Python con los mismos wheels que en desarrollo.

## Consecuencias
- **Versión de Python:** python.org solo publica binarios embebibles mientras una rama recibe
  correcciones de bugs. Para 3.12 el último es el **3.12.10**. Hay que decidir si nos quedamos
  ahí o pasamos a 3.14 (issue de seguimiento).
- Las DLL nativas de los wheels (libvips, numpy) no están firmadas; hasta ahora SAC las acepta
  por reputación. Hay que volver a verificarlo con cada actualización de dependencias.
- El instalador final igual debe estar **firmado** para usuarios con SAC (issue de seguimiento).
- Si alguna vez se necesita ocultar el código fuente, esta opción no sirve (el `.py` viaja
  legible). Para un proyecto MIT público no es un problema.

## Alternativas
- **PyInstaller onedir/onefile:** más lento y bloqueado por SAC (ver tabla).
- **Nuitka:** compila a C y produce otro exe único sin firma, con el mismo riesgo frente a SAC.
  No se probó.
- **python-build-standalone (el Python de uv):** funciona, pero no está firmado.
