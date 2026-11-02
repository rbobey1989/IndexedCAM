# Plan de desarrollo

Una fase cada vez; cada fase cierra con código, tests y docs. La lógica matemática no depende de FreeCAD; los adaptadores geométricos usan objetos de su API y se verifican también dentro de FreeCAD.

| Fase | Issues | Entregable | Estado |
| --- | --- | --- | --- |
| 0 | — | Registro básico del Workbench y ciclo de pruebas en FreeCAD | Hecha |
| 1 | #1, #10 | Cinemática normal → B/C (`Machine/bc_head.py`) + tests | Hecha |
| 2 | #2 | `FaceAnalyzer` (FreeCAD): normal representativa, centro, área y orientación | Hecha |
| 3 | #6 | `BCMachine`: límites (B 0..180, C ±360), vector de herramienta, validación | Hecha |
| 4 | #3 | `OrientationSolver`: normal → orientación válida para la máquina (elige solución dentro de límites) | Hecha |
| 5 | #4 | Modelo `Setup` (nombre, normal, WCS, B, C, operaciones, metadatos) | Hecha |
| 6 | #7 (#8 cerrada como duplicada) | `SetupManager`: crear/renombrar/borrar/ordenar en el documento | Hecha |
| 7 | #5 | Triada XYZ local con Coin3D | Hecha |
| 8 | #9 | Comando "Face Orientation" + registro del Workbench (`InitGui.py`) | Hecha |
| 9 | #11 | Investigación de integración con CAM (sin tocar el core): ver [CAM_INTEGRATION.md](CAM_INTEGRATION.md) | Hecha |
| 10 | #12 | Puente Setup ↔ Job CAM (Job único, clon local por Setup, alturas por operación) | Pendiente |
| 11 | #13 | Comando "Asignar operación" tras Face Orientation | Pendiente |
| 12 | #14 | Programa: secuencia de pasos encadenados | Pendiente |
| 13 | #15 | Envolvente de herramienta/cabezal en la máquina | Pendiente |
| 14 | #16 | `TransitionPlanner` (retirada, giro, aproximación) | Pendiente |
| 15 | #17 | `CollisionChecker` | Pendiente |
| 16 | #18 | Visualización de herramienta/movimientos y reproductor | Pendiente |
| 17 | #19 | Postprocesador `indexedcam_post.py` | Pendiente |

## Decisiones

- Solver puro devuelve B∈[0,180], C∈[−180,180); los límites físicos los valida `BCMachine` (fase 3).
- El Setup guarda solo B y C (A ausente), los docs `ARCHITECTURE.md` y `MVP.md` ya no mencionan A.
- B por defecto 0..180 (coincide con la salida del solver; C decide la dirección y B solo la inclinación). Los límites son configurables: una máquina limitada a 90° usa `AxisLimits(0, 90)` y entonces las normales con nz<0 son inalcanzables.
- `FaceAnalyzer` devuelve el centro de masa y una normal unitaria evaluada en el punto medio del rango paramétrico; para caras curvas son datos representativos, no una normal constante en toda la cara.
