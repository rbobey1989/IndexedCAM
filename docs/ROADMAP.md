# Plan de desarrollo

Una fase cada vez; cada fase cierra con código, tests y docs. Núcleo geométrico puro (sin FreeCAD) para poder testear con `pytest`.

| Fase | Issues | Entregable | Estado |
| --- | --- | --- | --- |
| 1 | #1, #10 | Cinemática normal → B/C (`Machine/bc_head.py`) + tests | Hecha |
| 2 | #6 | `BCMachine`: límites (B −90..90, C ±360), vector de herramienta, validación | Pendiente |
| 3 | #3 | `OrientationSolver`: normal → orientación válida para la máquina (elige solución dentro de límites) | Pendiente |
| 4 | #2 | `FaceAnalyzer` (FreeCAD): normal, centro, área de una cara | Pendiente |
| 5 | #4 | Modelo `Setup` (nombre, normal, WCS, B, C, operaciones, metadatos) | Pendiente |
| 6 | #7/#8 (duplicadas: cerrar una) | `SetupManager`: crear/renombrar/borrar/ordenar en el documento | Pendiente |
| 7 | #5 | Triada XYZ local con Coin3D | Pendiente |
| 8 | #9 | Comando "Face Orientation" + registro del Workbench (`InitGui.py`) | Pendiente |
| 9 | #11 | Investigación de integración con CAM (sin tocar el core) | Pendiente |

## Decisiones

- Solver puro devuelve B∈[0,180], C∈[−180,180); los límites físicos los valida `BCMachine` (fase 2).
- El Setup guarda solo B y C (A ausente), aunque `ARCHITECTURE.md` y `MVP.md` mencionan A/B/C: actualizar esos docs en la fase 5.
- Inconsistencia a resolver en fase 3: con B∈[−90,90] una normal con nz<0 solo es alcanzable con C+180 y B negativo.
