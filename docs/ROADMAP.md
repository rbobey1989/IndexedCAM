# Plan de desarrollo

Una fase cada vez; cada fase cierra con código, tests y docs. La lógica matemática no depende de FreeCAD; los adaptadores geométricos usan objetos de su API y se verifican también dentro de FreeCAD.

| Fase | Issues | Entregable | Estado |
| --- | --- | --- | --- |
| 0 | — | Registro básico del Workbench y ciclo de pruebas en FreeCAD | Hecha |
| 1 | #1, #10 | Cinemática normal → B/C (`Machine/bc_head.py`) + tests | Hecha |
| 2 | #2 | `FaceAnalyzer` (FreeCAD): normal representativa, centro, área y orientación | Hecha |
| 3 | #6 | `BCMachine`: límites (B −90..90, C ±360), vector de herramienta, validación | Hecha |
| 4 | #3 | `OrientationSolver`: normal → orientación válida para la máquina (elige solución dentro de límites) | Hecha |
| 5 | #4 | Modelo `Setup` (nombre, normal, WCS, B, C, operaciones, metadatos) | Pendiente |
| 6 | #7/#8 (duplicadas: cerrar una) | `SetupManager`: crear/renombrar/borrar/ordenar en el documento | Pendiente |
| 7 | #5 | Triada XYZ local con Coin3D | Pendiente |
| 8 | #9 | Comando "Face Orientation" + registro del Workbench (`InitGui.py`) | Pendiente |
| 9 | #11 | Investigación de integración con CAM (sin tocar el core) | Pendiente |

## Decisiones

- Solver puro devuelve B∈[0,180], C∈[−180,180); los límites físicos los valida `BCMachine` (fase 3).
- El Setup guarda solo B y C (A ausente), aunque `ARCHITECTURE.md` y `MVP.md` mencionan A/B/C: actualizar esos docs en la fase 5.
- B se mantiene en −90..90 (físicamente simétrico); `OrientationSolver` traduce la salida 0..180 usando (−B, C+180). Normales con nz<0 son inalcanzables.
- `FaceAnalyzer` devuelve el centro de masa y una normal unitaria evaluada en el punto medio del rango paramétrico; para caras curvas son datos representativos, no una normal constante en toda la cara.
